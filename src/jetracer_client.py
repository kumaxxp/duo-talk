"""
JetRacer Data Fetcher - Jetsonからセンサーデータを取得

使用方法:
    client = JetRacerClient("http://192.168.x.x:8000")
    data = client.get_all_sensors()
    frame_desc = client.to_frame_description(data)
"""
import httpx
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any
import time
import os


def load_config(config_path: str = None) -> dict:
    """設定ファイルを読み込む

    Args:
        config_path: 設定ファイルのパス。Noneの場合はプロジェクトルートのconfig.yamlを使用

    Returns:
        設定辞書。ファイルが存在しない場合は空辞書
    """
    if config_path is None:
        # プロジェクトルートの config.yaml を探す
        project_root = Path(__file__).parent.parent
        config_path = project_root / "config.yaml"

    config_path = Path(config_path)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@dataclass
class JetRacerState:
    """JetRacerの状態"""
    # IMU
    temperature: float = 0.0
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 0.0
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0
    heading: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    calib_status: str = "Unknown"
    # PWM
    throttle: float = 0.0  # -1.0 ~ 1.0
    steering: float = 0.0  # -1.0 ~ 1.0
    throttle_raw: int = 1500  # μs
    steering_raw: int = 1500  # μs
    mode: str = "unknown"  # "manual", "auto", "no_signal"
    # 距離
    min_distance: int = 0  # mm
    max_distance: int = 0
    avg_distance: float = 0.0
    distance_grid: Optional[list] = None  # 8x8 grid
    # メタ
    timestamp: float = 0.0
    valid: bool = False
    error: Optional[str] = None


class JetRacerClient:
    """JetRacer HTTP APIクライアント"""

    def __init__(self, base_url: Optional[str] = None, timeout: float = None):
        """
        Args:
            base_url: JetRacer APIのURL。Noneの場合はconfig.yaml→環境変数の順で取得
            timeout: HTTPタイムアウト秒数。Noneの場合はconfig.yaml→デフォルト値(10.0)
        """
        config = load_config()
        jetracer_config = config.get("jetracer", {})

        if base_url is None:
            # config.yaml → 環境変数 → デフォルト値 の順で取得
            host = jetracer_config.get("host", os.getenv("JETRACER_HOST", "localhost"))
            port = jetracer_config.get("port", int(os.getenv("JETRACER_PORT", "8000")))
            base_url = f"http://{host}:{port}"

        if timeout is None:
            timeout = jetracer_config.get("timeout", 10.0)

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        self._last_state: Optional[JetRacerState] = None
    
    def get_all_sensors(self) -> Optional[Dict[str, Any]]:
        """全センサーデータ取得"""
        try:
            resp = self._client.get(f"{self.base_url}/sensors/all")
            if resp.status_code == 200:
                return resp.json()
        except httpx.ConnectError as e:
            print(f"[JetRacerClient] Connection error: {e}")
        except httpx.TimeoutException as e:
            print(f"[JetRacerClient] Timeout: {e}")
        except Exception as e:
            print(f"[JetRacerClient] Error: {e}")
        return None
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """システム状態取得"""
        try:
            resp = self._client.get(f"{self.base_url}/status")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[JetRacerClient] Error: {e}")
        return None
    
    def get_imu(self) -> Optional[Dict[str, Any]]:
        """IMUデータのみ取得"""
        try:
            resp = self._client.get(f"{self.base_url}/sensors/imu")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[JetRacerClient] Error: {e}")
        return None
    
    def get_distance(self) -> Optional[Dict[str, Any]]:
        """距離データのみ取得"""
        try:
            resp = self._client.get(f"{self.base_url}/sensors/distance")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[JetRacerClient] Error: {e}")
        return None
    
    def set_led(self, color: str) -> bool:
        """LED色を設定
        
        Args:
            color: red, blue, yellow, green, white, orange, magenta, lime, pink, off, normal
        """
        try:
            resp = self._client.post(f"{self.base_url}/sensors/led/{color}")
            return resp.status_code == 200
        except Exception as e:
            print(f"[JetRacerClient] LED error: {e}")
            return False
    
    def parse_state(self, data: Dict[str, Any]) -> JetRacerState:
        """APIレスポンスをJetRacerStateに変換"""
        state = JetRacerState(timestamp=time.time())
        
        try:
            # IMU
            if data.get("imu") and data["imu"].get("valid"):
                imu = data["imu"]
                state.temperature = imu.get("temperature", 0)
                
                accel = imu.get("accel", {})
                state.accel_x = accel.get("x", 0)
                state.accel_y = accel.get("y", 0)
                state.accel_z = accel.get("z", 0)
                
                gyro = imu.get("gyro", {})
                state.gyro_x = gyro.get("x", 0)
                state.gyro_y = gyro.get("y", 0)
                state.gyro_z = gyro.get("z", 0)
                
                euler = imu.get("euler", {})
                state.heading = euler.get("heading", 0)
                state.roll = euler.get("roll", 0)
                state.pitch = euler.get("pitch", 0)
                
                calib = imu.get("calibration", {})
                state.calib_status = calib.get("status", "Unknown")
            
            # PWM
            if data.get("pwm_input") and data["pwm_input"].get("valid"):
                pwm = data["pwm_input"]
                channels = pwm.get("channels", {})
                
                throttle_ch = channels.get("ch2_throttle", {})
                state.throttle = throttle_ch.get("normalized", 0)
                state.throttle_raw = throttle_ch.get("raw_us", 1500)
                
                steering_ch = channels.get("ch1_steering", {})
                state.steering = steering_ch.get("normalized", 0)
                state.steering_raw = steering_ch.get("raw_us", 1500)
                
                state.mode = pwm.get("mode", "unknown")
            
            # 距離
            if data.get("distance") and data["distance"].get("valid"):
                dist = data["distance"]
                stats = dist.get("statistics", {})
                state.min_distance = stats.get("min_mm", 0)
                state.max_distance = stats.get("max_mm", 0)
                state.avg_distance = stats.get("avg_mm", 0)
                state.distance_grid = dist.get("grid_8x8")
            
            state.valid = True
            
        except Exception as e:
            state.error = str(e)
            state.valid = False
        
        self._last_state = state
        return state
    
    def fetch_and_parse(self) -> JetRacerState:
        """データ取得とパースを一括実行"""
        data = self.get_all_sensors()
        if data is None:
            state = JetRacerState(timestamp=time.time())
            state.error = "Failed to fetch sensor data"
            return state
        return self.parse_state(data)
    
    def to_frame_description(self, state: JetRacerState) -> str:
        """JetRacerStateをフレーム説明文に変換（duo-talk用）
        
        フレーム説明は、やな・あゆが会話するための状況説明文。
        センサーデータを自然な日本語に変換する。
        """
        if not state.valid:
            return f"センサーデータ取得エラー: {state.error or '接続失敗'}"
        
        parts = []
        
        # スロットル状態
        throttle_pct = int(state.throttle * 100)
        if throttle_pct > 10:
            parts.append(f"スロットル{throttle_pct}%で走行中")
        elif throttle_pct < -10:
            parts.append(f"後退中（{abs(throttle_pct)}%）")
        else:
            parts.append("停止中")
        
        # ステアリング状態
        steering_pct = int(state.steering * 100)
        if steering_pct > 20:
            parts.append(f"右に{steering_pct}%ステアリング")
        elif steering_pct < -20:
            parts.append(f"左に{abs(steering_pct)}%ステアリング")
        
        # 温度
        if state.temperature > 0:
            temp_desc = f"温度{state.temperature:.0f}度"
            if state.temperature >= 60:
                temp_desc += "（危険！）"
            elif state.temperature >= 50:
                temp_desc += "（高め）"
            parts.append(temp_desc)
        
        # 振動（水平加速度から推定）
        accel_horizontal = (state.accel_x**2 + state.accel_y**2)**0.5
        if accel_horizontal > 5.0:
            parts.append(f"強い振動検出（{accel_horizontal:.1f}m/s²）")
        elif accel_horizontal > 3.0:
            parts.append(f"振動あり（{accel_horizontal:.1f}m/s²）")
        
        # 傾き
        if abs(state.roll) > 15 or abs(state.pitch) > 15:
            parts.append(f"傾き検出（ロール{state.roll:.0f}°、ピッチ{state.pitch:.0f}°）")
        
        # 前方距離
        if state.min_distance > 0:
            if state.min_distance < 200:
                parts.append(f"前方{state.min_distance}mmに障害物！危険")
            elif state.min_distance < 500:
                parts.append(f"前方{state.min_distance}mmに障害物接近")
            elif state.min_distance < 1000:
                parts.append(f"前方約{state.min_distance//10}cmに物体")
        
        # モード
        if state.mode == "auto":
            parts.append("自動運転モード")
        elif state.mode == "manual":
            parts.append("手動操縦モード")
        elif state.mode == "no_signal":
            parts.append("プロポ信号なし")
        
        # キャリブレーション
        if state.calib_status == "Calibrating":
            parts.append("IMUキャリブレーション中")
        
        return "。".join(parts) + "。" if parts else "センサーデータ取得中。"
    
    def get_risk_level(self, state: JetRacerState) -> Dict[str, str]:
        """リスクレベルを評価
        
        Returns:
            {"temperature": "low/medium/high/critical", ...}
        """
        risks = {}
        
        # 温度リスク
        if state.temperature >= 65:
            risks["temperature"] = "critical"
        elif state.temperature >= 55:
            risks["temperature"] = "high"
        elif state.temperature >= 45:
            risks["temperature"] = "medium"
        else:
            risks["temperature"] = "low"
        
        # 衝突リスク
        if state.min_distance > 0:
            if state.min_distance < 200:
                risks["collision"] = "critical"
            elif state.min_distance < 500:
                risks["collision"] = "high"
            elif state.min_distance < 1000:
                risks["collision"] = "medium"
            else:
                risks["collision"] = "low"
        else:
            risks["collision"] = "unknown"
        
        # 振動リスク
        accel_g = (state.accel_x**2 + state.accel_y**2)**0.5 / 9.8
        if accel_g > 1.0:
            risks["vibration"] = "critical"
        elif accel_g > 0.5:
            risks["vibration"] = "high"
        elif accel_g > 0.3:
            risks["vibration"] = "medium"
        else:
            risks["vibration"] = "low"
        
        # 総合リスク（最も高いもの）
        risk_order = ["low", "medium", "high", "critical"]
        max_risk = "low"
        for r in risks.values():
            if r in risk_order and risk_order.index(r) > risk_order.index(max_risk):
                max_risk = r
        risks["overall"] = max_risk
        
        return risks
    
    def get_camera_image(self, camera_id: int = 0, as_base64: bool = True) -> Optional[str]:
        """カメラ画像を取得

        Args:
            camera_id: カメラID（0または1）
            as_base64: base64エンコードで返すか（Trueならbase64文字列、Falseならバイト列）

        Returns:
            as_base64=True: base64エンコードされた画像文字列
            as_base64=False: 画像のバイト列
            取得失敗時はNone

        Note:
            JetRacer-Agentの以下のエンドポイントを順番に試行:
            1. /distance-grid/{camera_id}/snapshot (推奨)
            2. /camera/{camera_id}/image
        """
        import base64

        # 方法1: distance-grid API（セグメンテーションなしのスナップショット）
        try:
            resp = self._client.get(
                f"{self.base_url}/distance-grid/{camera_id}/snapshot",
                params={"undistort": True}
            )
            if resp.status_code == 200:
                data = resp.json()
                # レスポンスがJSONでbase64画像を含む場合
                if "image_base64" in data:
                    img_b64 = data["image_base64"]
                    if as_base64:
                        return img_b64
                    else:
                        return base64.b64decode(img_b64)
                # レスポンスがJSONでsnapshot_base64を含む場合
                if "snapshot_base64" in data:
                    img_b64 = data["snapshot_base64"]
                    if as_base64:
                        return img_b64
                    else:
                        return base64.b64decode(img_b64)
        except Exception as e:
            print(f"[JetRacerClient] Snapshot API error: {e}")

        # 方法2: カメラ直接API
        try:
            resp = self._client.get(f"{self.base_url}/camera/{camera_id}/image")
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "image" in content_type:
                    # バイナリ画像が返ってきた場合
                    if as_base64:
                        return base64.b64encode(resp.content).decode("utf-8")
                    else:
                        return resp.content
                elif "json" in content_type:
                    # JSONで返ってきた場合
                    data = resp.json()
                    if "image_base64" in data:
                        img_b64 = data["image_base64"]
                        if as_base64:
                            return img_b64
                        else:
                            return base64.b64decode(img_b64)
        except Exception as e:
            print(f"[JetRacerClient] Camera API error: {e}")

        # 方法3: セグメンテーションAPIのoverlay（フォールバック）
        try:
            resp = self._client.get(
                f"{self.base_url}/distance-grid/{camera_id}/analyze-segmentation-lightweight",
                params={"undistort": True, "show_grid": False}
            )
            if resp.status_code == 200:
                data = resp.json()
                if "overlay_base64" in data:
                    img_b64 = data["overlay_base64"]
                    if as_base64:
                        return img_b64
                    else:
                        return base64.b64decode(img_b64)
        except Exception as e:
            print(f"[JetRacerClient] Segmentation API error: {e}")

        print(f"[JetRacerClient] Failed to get camera image (camera_id={camera_id})")
        return None

    @property
    def last_state(self) -> Optional[JetRacerState]:
        """最後に取得した状態"""
        return self._last_state
    
    def close(self):
        """クライアントをクローズ"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# シンプルなテスト用
if __name__ == "__main__":
    import sys
    
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    print(f"Connecting to {url}...")
    
    with JetRacerClient(url) as client:
        state = client.fetch_and_parse()
        
        if state.valid:
            print("\n=== JetRacer State ===")
            print(f"Temperature: {state.temperature}°C")
            print(f"Throttle: {state.throttle*100:.0f}%")
            print(f"Steering: {state.steering*100:.0f}%")
            print(f"Mode: {state.mode}")
            print(f"Min Distance: {state.min_distance}mm")
            print(f"\n=== Frame Description ===")
            print(client.to_frame_description(state))
            print(f"\n=== Risk Levels ===")
            print(client.get_risk_level(state))
        else:
            print(f"Error: {state.error}")
