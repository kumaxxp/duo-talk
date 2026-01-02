"""
JetRacer Data Provider - モード別データ取得

モード:
- SENSOR_ONLY: 軽量（センサーのみ）- 現在のjetracer_client相当
- VISION: センサー + カメラ + セグメンテーション
- FULL_AUTONOMY: 全データ + 自律走行状態

yana-brainのjetson_client.pyを参考に実装。
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional
import time

from .jetracer_client import JetRacerClient, JetRacerState, load_config


class DataMode(Enum):
    SENSOR_ONLY = "sensor_only"
    VISION = "vision"
    FULL_AUTONOMY = "full_autonomy"


@dataclass
class VisionData:
    """画像・セグメンテーションデータ"""
    camera_image_base64: Optional[str] = None
    segmentation_overlay_base64: Optional[str] = None
    road_percentage: float = 0.0
    inference_time_ms: float = 0.0
    model_type: str = "lightweight"  # lightweight or oneformer
    navigation_hint: str = ""  # left, right, straight, stop


@dataclass
class AutonomyData:
    """自律走行データ"""
    mode: str = "manual"  # init, manual, auto, emergency_stop
    running: bool = False
    steering_command: float = 0.0
    throttle_command: float = 0.0
    road_ratio: float = 0.0
    lidar_min_mm: int = 9999
    loop_count: int = 0
    loop_time_ms: float = 0.0


@dataclass
class JetRacerFullState:
    """JetRacer全状態（JetRacerStateを拡張）"""
    # センサー（JetRacerStateから継承）
    sensor: Optional[JetRacerState] = None

    # ビジョン（VISIONモード以上）
    vision: Optional[VisionData] = None

    # 自律走行（FULL_AUTONOMYモード）
    autonomy: Optional[AutonomyData] = None

    # メタ
    timestamp: float = 0.0
    data_mode: DataMode = DataMode.SENSOR_ONLY
    valid: bool = False
    error: Optional[str] = None


class JetRacerProvider:
    """モード別データプロバイダー"""

    def __init__(self, client: JetRacerClient = None, mode: DataMode = None):
        """
        Args:
            client: JetRacerClient インスタンス（Noneの場合は自動作成）
            mode: データモード（Noneの場合はconfig.yamlから取得）
        """
        if client is None:
            client = JetRacerClient()
        self.client = client

        if mode is None:
            config = load_config()
            mode_str = config.get("jetracer", {}).get("data_mode", "sensor_only")
            try:
                mode = DataMode(mode_str)
            except ValueError:
                print(f"[JetRacerProvider] Unknown mode '{mode_str}', using SENSOR_ONLY")
                mode = DataMode.SENSOR_ONLY
        self.mode = mode

        print(f"[JetRacerProvider] Mode: {self.mode.value}")

    def fetch(self) -> JetRacerFullState:
        """モードに応じたデータ取得"""
        state = JetRacerFullState(
            timestamp=time.time(),
            data_mode=self.mode
        )

        try:
            # 常にセンサーデータ取得
            state.sensor = self.client.fetch_and_parse()
            state.valid = state.sensor.valid

            # VISIONモード以上
            if self.mode in [DataMode.VISION, DataMode.FULL_AUTONOMY]:
                state.vision = self._fetch_vision()

            # FULL_AUTONOMYモード
            if self.mode == DataMode.FULL_AUTONOMY:
                state.autonomy = self._fetch_autonomy()

        except Exception as e:
            state.error = str(e)
            state.valid = False

        return state

    def _fetch_vision(self) -> VisionData:
        """ビジョンデータ取得（Lightweightセグメンテーション）"""
        vision = VisionData()

        try:
            # Lightweight セグメンテーション API
            resp = self.client._client.get(
                f"{self.client.base_url}/distance-grid/0/analyze-segmentation-lightweight",
                params={"undistort": True, "show_grid": False}
            )
            if resp.status_code == 200:
                data = resp.json()
                vision.segmentation_overlay_base64 = data.get("overlay_base64")
                vision.road_percentage = data.get("road_percentage", 0)
                vision.inference_time_ms = data.get("inference_time_ms", 0)
                vision.model_type = data.get("model_type", "lightweight")
        except Exception as e:
            print(f"[JetRacerProvider] Vision fetch error: {e}")

        return vision

    def _fetch_autonomy(self) -> AutonomyData:
        """自律走行データ取得"""
        autonomy = AutonomyData()

        try:
            resp = self.client._client.get(f"{self.client.base_url}/auto/state")
            if resp.status_code == 200:
                data = resp.json()
                autonomy.mode = data.get("mode", "manual")
                autonomy.running = data.get("running", False)

                control = data.get("control", {})
                autonomy.steering_command = control.get("steering", 0)
                autonomy.throttle_command = control.get("throttle", 0)

                sensors = data.get("sensors", {})
                autonomy.road_ratio = sensors.get("road_ratio", 0)
                autonomy.lidar_min_mm = sensors.get("lidar_min_mm", 9999)

                stats = data.get("stats", {})
                autonomy.loop_count = stats.get("loop_count", 0)
                autonomy.loop_time_ms = stats.get("avg_loop_time_ms", 0)
        except Exception as e:
            print(f"[JetRacerProvider] Autonomy fetch error: {e}")

        return autonomy

    def to_frame_description(self, state: JetRacerFullState) -> str:
        """JetRacerFullStateをフレーム説明文に変換"""
        if not state.valid or state.sensor is None:
            return f"センサーデータ取得エラー: {state.error or '接続失敗'}"

        parts = []

        # センサー情報（基本）
        sensor = state.sensor
        throttle_pct = int(sensor.throttle * 100)
        if throttle_pct > 10:
            parts.append(f"スロットル{throttle_pct}%で走行中")
        elif throttle_pct < -10:
            parts.append(f"後退中（{abs(throttle_pct)}%）")
        else:
            parts.append("停止中")

        # 温度
        if sensor.temperature > 0:
            temp_desc = f"温度{sensor.temperature:.0f}度"
            if sensor.temperature >= 60:
                temp_desc += "（危険！）"
            elif sensor.temperature >= 50:
                temp_desc += "（高め）"
            parts.append(temp_desc)

        # 前方距離
        if sensor.min_distance > 0:
            if sensor.min_distance < 200:
                parts.append(f"前方{sensor.min_distance}mmに障害物！危険")
            elif sensor.min_distance < 500:
                parts.append(f"前方{sensor.min_distance}mmに障害物接近")
            elif sensor.min_distance < 1000:
                parts.append(f"前方約{sensor.min_distance//10}cmに物体")

        # VISIONモード追加情報
        if state.vision and state.data_mode in [DataMode.VISION, DataMode.FULL_AUTONOMY]:
            vision = state.vision
            if vision.road_percentage > 0:
                road_pct = vision.road_percentage
                if road_pct < 20:
                    parts.append(f"走行可能領域わずか{road_pct:.0f}%")
                elif road_pct < 50:
                    parts.append(f"走行可能領域{road_pct:.0f}%")
                else:
                    parts.append(f"走行可能領域十分（{road_pct:.0f}%）")

        # FULL_AUTONOMYモード追加情報
        if state.autonomy and state.data_mode == DataMode.FULL_AUTONOMY:
            auto = state.autonomy
            if auto.mode == "auto":
                parts.append("自動運転モード稼働中")
            elif auto.mode == "emergency_stop":
                parts.append("緊急停止中！")

            if auto.running:
                parts.append(f"ループ{auto.loop_time_ms:.0f}ms")

        # モード
        if sensor.mode == "auto":
            parts.append("AIモード")
        elif sensor.mode == "manual":
            parts.append("手動操縦")
        elif sensor.mode == "no_signal":
            parts.append("プロポ信号なし")

        return "。".join(parts) + "。" if parts else "データ取得中。"

    def close(self):
        """クライアントをクローズ"""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
