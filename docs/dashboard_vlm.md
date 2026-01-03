【タスク】duo-talk v2.1 ダッシュボード改造 + VLM統合

【作業ディレクトリ】
C:\work\duo-talk

【概要】
1. 既存のReactダッシュボード + FastAPIサーバーをv2.1対応に改造
2. VLM統合パイプライン（Phase 0）の実装

===========================================
Part 1: サーバーサイド v2.1 API追加
===========================================

【ファイル】server/api_v2.py を新規作成
```python
#!/usr/bin/env python3
"""
DUO-TALK v2.1 API Extensions
DuoSignals, NoveltyGuard, SilenceController のリアルタイム状態を配信
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Generator

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, jsonify, request, Response
from src.signals import DuoSignals, SignalEvent, EventType, DuoSignalsState
from src.novelty_guard import NoveltyGuard, LoopBreakStrategy
from src.silence_controller import SilenceController, SilenceType
from src.character import Character
from src.jetracer_client import JetRacerClient
from src.jetracer_provider import JetRacerProvider, DataMode

# Blueprint for v2.1 APIs
v2_api = Blueprint('v2_api', __name__, url_prefix='/api/v2')

# Global instances
_signals: Optional[DuoSignals] = None
_novelty_guard: Optional[NoveltyGuard] = None
_silence_controller: Optional[SilenceController] = None
_characters: Dict[str, Character] = {}
_jetracer_provider: Optional[JetRacerProvider] = None


def get_signals() -> DuoSignals:
    global _signals
    if _signals is None:
        DuoSignals.reset_instance()
        _signals = DuoSignals()
    return _signals


def get_novelty_guard() -> NoveltyGuard:
    global _novelty_guard
    if _novelty_guard is None:
        _novelty_guard = NoveltyGuard()
    return _novelty_guard


def get_silence_controller() -> SilenceController:
    global _silence_controller
    if _silence_controller is None:
        _silence_controller = SilenceController()
    return _silence_controller


def get_character(char_id: str) -> Character:
    global _characters
    if char_id not in _characters:
        _characters[char_id] = Character(char_id)
    return _characters[char_id]


# ==================== DuoSignals API ====================

@v2_api.route('/signals', methods=['GET'])
def get_signals_state():
    """現在のDuoSignals状態を取得"""
    signals = get_signals()
    state = signals.snapshot()
    
    return jsonify({
        "status": "ok",
        "state": {
            "jetracer_mode": state.jetracer_mode,
            "current_speed": state.current_speed,
            "steering_angle": state.steering_angle,
            "distance_sensors": state.distance_sensors,
            "scene_facts": state.scene_facts,
            "last_speaker": state.last_speaker,
            "turn_count": state.turn_count,
            "current_topic": state.current_topic,
            "topic_depth": state.topic_depth,
            "recent_topics": state.recent_topics[-5:],
            "recent_events": state.recent_events[-3:],
            "last_updated": state.last_updated.isoformat(),
            "is_stale": signals.is_stale()
        }
    })


@v2_api.route('/signals/update', methods=['POST'])
def update_signals():
    """DuoSignalsを更新（テスト/シミュレーション用）"""
    data = request.get_json()
    signals = get_signals()
    
    event_type_str = data.get('event_type', 'sensor')
    event_data = data.get('data', {})
    
    try:
        event_type = EventType(event_type_str)
        signals.update(SignalEvent(event_type=event_type, data=event_data))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@v2_api.route('/signals/stream', methods=['GET'])
def stream_signals():
    """DuoSignals状態をSSEでストリーム"""
    def generate():
        signals = get_signals()
        last_update = None
        
        while True:
            state = signals.snapshot()
            current_update = state.last_updated
            
            # 更新があった場合のみ送信
            if last_update is None or current_update > last_update:
                event_data = {
                    "jetracer_mode": state.jetracer_mode,
                    "current_speed": state.current_speed,
                    "steering_angle": state.steering_angle,
                    "distance_sensors": state.distance_sensors,
                    "scene_facts": state.scene_facts,
                    "turn_count": state.turn_count,
                    "topic_depth": state.topic_depth,
                    "is_stale": signals.is_stale(),
                    "timestamp": current_update.isoformat()
                }
                yield f"event: signals\ndata: {json.dumps(event_data)}\n\n"
                last_update = current_update
            
            time.sleep(0.5)
    
    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache'})


# ==================== NoveltyGuard API ====================

@v2_api.route('/novelty/status', methods=['GET'])
def get_novelty_status():
    """NoveltyGuardの状態を取得"""
    guard = get_novelty_guard()
    stats = guard.get_stats()
    
    return jsonify({
        "status": "ok",
        "novelty_guard": stats
    })


@v2_api.route('/novelty/check', methods=['POST'])
def check_novelty():
    """テキストのループ検知をチェック"""
    data = request.get_json()
    text = data.get('text', '')
    
    guard = get_novelty_guard()
    result = guard.check_and_update(text)
    
    return jsonify({
        "status": "ok",
        "result": {
            "loop_detected": result.loop_detected,
            "stuck_nouns": result.stuck_nouns,
            "strategy": result.strategy.value if result.strategy else None,
            "topic_depth": result.topic_depth,
            "injection": result.injection
        }
    })


# ==================== SilenceController API ====================

@v2_api.route('/silence/check', methods=['GET'])
def check_silence():
    """現在の状態で沈黙すべきかチェック"""
    signals = get_signals()
    controller = get_silence_controller()
    state = signals.snapshot()
    
    silence = controller.should_silence(state)
    
    if silence:
        return jsonify({
            "status": "ok",
            "should_silence": True,
            "silence": {
                "type": silence.silence_type.value,
                "duration": silence.duration_seconds,
                "allow_short": silence.allow_short_utterance,
                "sfx": silence.suggested_sfx,
                "bgm_intensity": silence.suggested_bgm_intensity
            }
        })
    else:
        return jsonify({
            "status": "ok",
            "should_silence": False
        })


# ==================== Character v2 API ====================

@v2_api.route('/speak', methods=['POST'])
def speak_v2():
    """speak_v2を使った発話生成"""
    data = request.get_json()
    
    char_id = data.get('character', 'A')
    last_utterance = data.get('last_utterance', '')
    frame_description = data.get('frame_description', '')
    history = data.get('history', [])
    
    character = get_character(char_id)
    
    result = character.speak_v2(
        last_utterance=last_utterance,
        context={"history": history},
        frame_description=frame_description
    )
    
    return jsonify({
        "status": "ok",
        "result": result
    })


# ==================== JetRacer Integration ====================

@v2_api.route('/jetracer/connect', methods=['POST'])
def connect_jetracer():
    """JetRacerに接続"""
    global _jetracer_provider
    
    data = request.get_json()
    url = data.get('url', 'http://192.168.1.65:8000')
    mode = data.get('mode', 'sensor_only')
    
    try:
        client = JetRacerClient(url, timeout=5.0)
        status = client.get_status()
        
        if status:
            data_mode = DataMode(mode)
            _jetracer_provider = JetRacerProvider(client, data_mode)
            return jsonify({
                "status": "ok",
                "message": f"Connected to {url}",
                "mode": mode
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Connection failed"
            }), 503
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@v2_api.route('/jetracer/fetch', methods=['GET'])
def fetch_jetracer():
    """JetRacerからデータ取得してDuoSignalsに反映"""
    global _jetracer_provider
    
    if _jetracer_provider is None:
        return jsonify({
            "status": "error",
            "message": "Not connected to JetRacer"
        }), 400
    
    try:
        full_state = _jetracer_provider.fetch()
        
        if not full_state.valid or full_state.sensor is None:
            return jsonify({
                "status": "error",
                "message": "Failed to fetch sensor data"
            }), 503
        
        sensor = full_state.sensor
        signals = get_signals()
        
        # センサーイベント
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={
                "speed": abs(sensor.throttle) * 3.0,
                "steering": sensor.steering * 45,
                "sensors": {
                    "distance": sensor.min_distance,
                    "temperature": sensor.temperature
                }
            }
        ))
        
        # VLM観測（VISIONモード時）
        if full_state.vision and full_state.vision.road_percentage > 0:
            signals.update(SignalEvent(
                event_type=EventType.VLM,
                data={
                    "facts": {
                        "road_percentage": f"{full_state.vision.road_percentage:.0f}%",
                        "inference_time": f"{full_state.vision.inference_time_ms:.0f}ms"
                    }
                }
            ))
        
        frame_desc = _jetracer_provider.to_frame_description(full_state)
        
        return jsonify({
            "status": "ok",
            "frame_description": frame_desc,
            "sensor": {
                "speed": sensor.throttle,
                "steering": sensor.steering,
                "distance": sensor.min_distance,
                "temperature": sensor.temperature,
                "mode": sensor.mode
            },
            "vision": {
                "road_percentage": full_state.vision.road_percentage if full_state.vision else 0,
                "inference_time": full_state.vision.inference_time_ms if full_state.vision else 0
            } if full_state.vision else None
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@v2_api.route('/jetracer/stream', methods=['GET'])
def stream_jetracer():
    """JetRacerデータをSSEでストリーム"""
    global _jetracer_provider
    
    if _jetracer_provider is None:
        return jsonify({
            "status": "error",
            "message": "Not connected to JetRacer"
        }), 400
    
    interval = float(request.args.get('interval', 1.0))
    
    def generate():
        signals = get_signals()
        
        while True:
            try:
                full_state = _jetracer_provider.fetch()
                
                if full_state.valid and full_state.sensor:
                    sensor = full_state.sensor
                    
                    # DuoSignals更新
                    signals.update(SignalEvent(
                        event_type=EventType.SENSOR,
                        data={
                            "speed": abs(sensor.throttle) * 3.0,
                            "steering": sensor.steering * 45,
                            "sensors": {
                                "distance": sensor.min_distance,
                                "temperature": sensor.temperature
                            }
                        }
                    ))
                    
                    event_data = {
                        "sensor": {
                            "speed": sensor.throttle,
                            "steering": sensor.steering,
                            "distance": sensor.min_distance,
                            "temperature": sensor.temperature,
                            "mode": sensor.mode
                        },
                        "frame_description": _jetracer_provider.to_frame_description(full_state),
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    if full_state.vision:
                        event_data["vision"] = {
                            "road_percentage": full_state.vision.road_percentage,
                            "inference_time": full_state.vision.inference_time_ms
                        }
                    
                    yield f"event: jetracer\ndata: {json.dumps(event_data)}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            
            time.sleep(interval)
    
    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache'})


# ==================== Live Commentary ====================

@v2_api.route('/live/start', methods=['POST'])
def start_live_commentary():
    """ライブコメンタリーセッション開始"""
    data = request.get_json()
    
    # JetRacer接続確認
    jetracer_url = data.get('jetracer_url', 'http://192.168.1.65:8000')
    turns_per_frame = data.get('turns_per_frame', 4)
    interval = data.get('interval', 3.0)
    
    # セッションID生成
    session_id = f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    return jsonify({
        "status": "ok",
        "session_id": session_id,
        "config": {
            "jetracer_url": jetracer_url,
            "turns_per_frame": turns_per_frame,
            "interval": interval
        }
    })


@v2_api.route('/live/dialogue', methods=['POST'])
def generate_live_dialogue():
    """1フレーム分の対話を生成"""
    data = request.get_json()
    
    frame_description = data.get('frame_description', '')
    history = data.get('history', [])
    turns = data.get('turns', 2)
    
    signals = get_signals()
    novelty_guard = get_novelty_guard()
    silence_controller = get_silence_controller()
    
    state = signals.snapshot()
    
    # 沈黙チェック
    silence = silence_controller.should_silence(state)
    if silence:
        return jsonify({
            "status": "ok",
            "type": "silence",
            "silence": {
                "type": silence.silence_type.value,
                "duration": silence.duration_seconds
            }
        })
    
    # 対話生成
    dialogue = []
    for turn in range(turns):
        char_id = "A" if turn % 2 == 0 else "B"
        character = get_character(char_id)
        
        last_utterance = dialogue[-1]["content"] if dialogue else (
            history[-1]["content"] if history else "（画面を見ている）"
        )
        
        result = character.speak_v2(
            last_utterance=last_utterance,
            context={"history": history + dialogue},
            frame_description=frame_description
        )
        
        if result["type"] == "speech":
            speaker_name = "やな" if char_id == "A" else "あゆ"
            dialogue.append({
                "speaker": speaker_name,
                "content": result["content"],
                "debug": result.get("debug", {})
            })
    
    return jsonify({
        "status": "ok",
        "type": "dialogue",
        "dialogue": dialogue
    })
```

【ファイル】server/api_server.py を編集
既存ファイルの最後（if __name__ == '__main__': の前）に以下を追加:
```python
# ==================== v2.1 API Extensions ====================
from server.api_v2 import v2_api
app.register_blueprint(v2_api)
```

===========================================
Part 2: VLM統合パイプライン (Phase 0)
===========================================

【ファイル】src/vlm_analyzer.py を新規作成
```python
#!/usr/bin/env python3
"""
duo-talk v2.1 - VLM Analyzer
カメラ画像をVLMで解析し、構造化された観測データ（scene_facts）に変換

機能:
- 画像のVLM解析（車載カメラ視点）
- 構造化されたシーン情報の抽出
- DuoSignalsへの自動注入
"""

import base64
import json
import httpx
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from src.config import config
from src.signals import DuoSignals, SignalEvent, EventType


@dataclass
class VLMAnalysisResult:
    """VLM解析結果"""
    # 基本情報
    road_condition: str = "unknown"  # clear, wet, rough, obstacle
    visibility: str = "good"  # good, moderate, poor
    lighting: str = "normal"  # bright, normal, dark, backlight
    
    # 走行関連
    lane_position: str = "center"  # left, center, right
    upcoming_feature: str = "straight"  # straight, curve_left, curve_right, corner, intersection
    obstacle_detected: bool = False
    obstacle_description: str = ""
    
    # 環境
    environment: str = "indoor"  # indoor, outdoor
    surface_type: str = "unknown"  # carpet, tile, asphalt, concrete
    
    # 数値データ
    road_percentage: float = 0.0  # 走行可能領域の割合
    confidence: float = 0.0
    
    # 生データ
    raw_description: str = ""
    inference_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_scene_facts(self) -> Dict[str, str]:
        """DuoSignals.scene_facts用の辞書に変換"""
        facts = {
            "road_condition": self.road_condition,
            "visibility": self.visibility,
            "lighting": self.lighting,
            "lane_position": self.lane_position,
            "upcoming": self.upcoming_feature,
            "environment": self.environment,
            "surface": self.surface_type,
            "road_percentage": f"{self.road_percentage:.0f}%",
        }
        
        if self.obstacle_detected:
            facts["obstacle"] = self.obstacle_description or "detected"
        
        return facts
    
    def to_frame_description(self) -> str:
        """フレーム説明文に変換"""
        parts = []
        
        # 走行領域
        if self.road_percentage > 0:
            if self.road_percentage < 30:
                parts.append(f"走行可能領域わずか{self.road_percentage:.0f}%")
            elif self.road_percentage < 60:
                parts.append(f"走行可能領域{self.road_percentage:.0f}%")
            else:
                parts.append(f"走行可能領域十分（{self.road_percentage:.0f}%）")
        
        # コーナー/直線
        feature_map = {
            "straight": "直線区間",
            "curve_left": "左カーブ",
            "curve_right": "右カーブ",
            "corner": "コーナー",
            "intersection": "交差点",
        }
        if self.upcoming_feature in feature_map:
            parts.append(feature_map[self.upcoming_feature])
        
        # 障害物
        if self.obstacle_detected:
            desc = self.obstacle_description or "障害物"
            parts.append(f"前方に{desc}あり")
        
        # 路面状態
        if self.road_condition != "clear":
            condition_map = {
                "wet": "路面濡れ",
                "rough": "路面荒れ",
                "obstacle": "障害物あり",
            }
            if self.road_condition in condition_map:
                parts.append(condition_map[self.road_condition])
        
        # 照明
        if self.lighting != "normal":
            lighting_map = {
                "dark": "暗い",
                "bright": "眩しい",
                "backlight": "逆光",
            }
            if self.lighting in lighting_map:
                parts.append(lighting_map[self.lighting])
        
        return "。".join(parts) + "。" if parts else "通常走行中。"


class VLMAnalyzer:
    """
    VLM画像解析器
    
    使用例:
        analyzer = VLMAnalyzer()
        result = analyzer.analyze_image("path/to/image.jpg")
        
        # DuoSignalsに注入
        signals = DuoSignals()
        analyzer.inject_to_signals(result, signals)
    """
    
    # VLM解析用プロンプト
    ANALYSIS_PROMPT = """あなたは自動運転車の車載カメラ映像を解析するAIです。
画像を見て、以下の情報をJSON形式で出力してください。

{
    "road_condition": "clear|wet|rough|obstacle",
    "visibility": "good|moderate|poor",
    "lighting": "bright|normal|dark|backlight",
    "lane_position": "left|center|right",
    "upcoming_feature": "straight|curve_left|curve_right|corner|intersection",
    "obstacle_detected": true|false,
    "obstacle_description": "障害物の説明（なければ空文字）",
    "environment": "indoor|outdoor",
    "surface_type": "carpet|tile|asphalt|concrete|unknown",
    "road_percentage": 0-100（走行可能な領域の割合）,
    "description": "シーンの簡潔な説明（日本語で1文）"
}

注意:
- road_percentageは画像内で走行可能な領域の割合を推定
- upcoming_featureは進行方向の道路形状を判断
- 不明な場合はunknownや0を使用
- JSONのみを出力し、他の説明は不要"""

    def __init__(
        self,
        api_base: str = None,
        model: str = None,
        timeout: float = 30.0
    ):
        """
        Args:
            api_base: VLM APIのベースURL（Noneならconfig使用）
            model: 使用するモデル名（Noneならconfig使用）
            timeout: APIタイムアウト秒数
        """
        self.api_base = api_base or config.openai_base_url
        self.model = model or config.openai_model
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
    
    def analyze_image(self, image_path: str) -> VLMAnalysisResult:
        """
        画像をVLMで解析
        
        Args:
            image_path: 画像ファイルパス
            
        Returns:
            VLMAnalysisResult: 解析結果
        """
        start_time = datetime.now()
        result = VLMAnalysisResult()
        
        try:
            # 画像をbase64エンコード
            image_path = Path(image_path)
            if not image_path.exists():
                result.raw_description = f"Image not found: {image_path}"
                return result
            
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            # 拡張子からMIMEタイプを推定
            ext = image_path.suffix.lower()
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
            }
            mime_type = mime_types.get(ext, 'image/jpeg')
            
            # VLM API呼び出し
            response = self._call_vlm(image_data, mime_type)
            
            # 結果をパース
            result = self._parse_response(response)
            
        except Exception as e:
            result.raw_description = f"Analysis error: {str(e)}"
        
        # 処理時間を記録
        result.inference_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        result.timestamp = datetime.now()
        
        return result
    
    def analyze_base64(self, image_base64: str, mime_type: str = "image/jpeg") -> VLMAnalysisResult:
        """
        base64エンコードされた画像を解析
        
        Args:
            image_base64: base64エンコードされた画像データ
            mime_type: MIMEタイプ
            
        Returns:
            VLMAnalysisResult: 解析結果
        """
        start_time = datetime.now()
        result = VLMAnalysisResult()
        
        try:
            response = self._call_vlm(image_base64, mime_type)
            result = self._parse_response(response)
        except Exception as e:
            result.raw_description = f"Analysis error: {str(e)}"
        
        result.inference_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        result.timestamp = datetime.now()
        
        return result
    
    def _call_vlm(self, image_base64: str, mime_type: str) -> str:
        """VLM APIを呼び出し"""
        # OpenAI互換API形式
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self.ANALYSIS_PROMPT
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 500,
            "temperature": 0.1
        }
        
        response = self._client.post(
            f"{self.api_base}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    def _parse_response(self, response_text: str) -> VLMAnalysisResult:
        """VLMレスポンスをパース"""
        result = VLMAnalysisResult()
        result.raw_description = response_text
        
        try:
            # JSONを抽出（```json...```で囲まれている場合も対応）
            json_text = response_text
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0]
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0]
            
            data = json.loads(json_text.strip())
            
            result.road_condition = data.get("road_condition", "unknown")
            result.visibility = data.get("visibility", "good")
            result.lighting = data.get("lighting", "normal")
            result.lane_position = data.get("lane_position", "center")
            result.upcoming_feature = data.get("upcoming_feature", "straight")
            result.obstacle_detected = data.get("obstacle_detected", False)
            result.obstacle_description = data.get("obstacle_description", "")
            result.environment = data.get("environment", "indoor")
            result.surface_type = data.get("surface_type", "unknown")
            result.road_percentage = float(data.get("road_percentage", 0))
            result.confidence = 0.8  # パース成功
            
            if data.get("description"):
                result.raw_description = data["description"]
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            result.confidence = 0.3  # パース失敗
        
        return result
    
    def inject_to_signals(self, result: VLMAnalysisResult, signals: DuoSignals) -> None:
        """解析結果をDuoSignalsに注入"""
        signals.update(SignalEvent(
            event_type=EventType.VLM,
            data={"facts": result.to_scene_facts()}
        ))
    
    def close(self):
        """クライアントをクローズ"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# シングルトンインスタンス
_analyzer: Optional[VLMAnalyzer] = None


def get_vlm_analyzer() -> VLMAnalyzer:
    """VLMAnalyzerを取得（シングルトン）"""
    global _analyzer
    if _analyzer is None:
        _analyzer = VLMAnalyzer()
    return _analyzer


def reset_vlm_analyzer() -> None:
    """VLMAnalyzerをリセット"""
    global _analyzer
    if _analyzer:
        _analyzer.close()
    _analyzer = None
```

【ファイル】src/vision_to_signals.py を新規作成
```python
#!/usr/bin/env python3
"""
duo-talk v2.1 - Vision to Signals Bridge
VLM出力を構造化してDuoSignalsに流すブリッジ

設計書 Phase 0 の実装:
- VLM出力（JSON or テキスト）をパース
- 構造化した観測データを DuoSignals.scene_facts に格納
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from src.signals import DuoSignals, SignalEvent, EventType
from src.vlm_analyzer import VLMAnalyzer, VLMAnalysisResult, get_vlm_analyzer


@dataclass
class VisionBridgeConfig:
    """Vision→Signalsブリッジの設定"""
    auto_inject: bool = True  # 解析後に自動でSignalsに注入
    include_raw: bool = False  # 生のVLM出力も含める
    min_confidence: float = 0.5  # 最低信頼度（これ以下は無視）


class VisionToSignalsBridge:
    """
    Vision解析結果をDuoSignalsに変換・注入するブリッジ
    
    使用例:
        bridge = VisionToSignalsBridge()
        
        # 画像から直接
        result = bridge.process_image("path/to/image.jpg")
        
        # JetRacerのセグメンテーション結果から
        bridge.process_segmentation_result({
            "road_percentage": 75.0,
            "inference_time_ms": 40.0
        })
    """
    
    def __init__(
        self,
        signals: DuoSignals = None,
        analyzer: VLMAnalyzer = None,
        config: VisionBridgeConfig = None
    ):
        self.signals = signals or DuoSignals()
        self.analyzer = analyzer or get_vlm_analyzer()
        self.config = config or VisionBridgeConfig()
    
    def process_image(self, image_path: str) -> VLMAnalysisResult:
        """
        画像を解析してSignalsに注入
        
        Args:
            image_path: 画像ファイルパス
            
        Returns:
            VLMAnalysisResult: 解析結果
        """
        result = self.analyzer.analyze_image(image_path)
        
        if self.config.auto_inject and result.confidence >= self.config.min_confidence:
            self._inject_result(result)
        
        return result
    
    def process_image_base64(self, image_base64: str, mime_type: str = "image/jpeg") -> VLMAnalysisResult:
        """
        base64画像を解析してSignalsに注入
        """
        result = self.analyzer.analyze_base64(image_base64, mime_type)
        
        if self.config.auto_inject and result.confidence >= self.config.min_confidence:
            self._inject_result(result)
        
        return result
    
    def process_segmentation_result(self, seg_result: Dict[str, Any]) -> None:
        """
        セグメンテーション結果（JetRacer APIから）をSignalsに注入
        
        Args:
            seg_result: {
                "road_percentage": float,
                "inference_time_ms": float,
                "navigation_hint": str (optional)
            }
        """
        facts = {}
        
        if "road_percentage" in seg_result:
            facts["road_percentage"] = f"{seg_result['road_percentage']:.0f}%"
        
        if "inference_time_ms" in seg_result:
            facts["inference_time"] = f"{seg_result['inference_time_ms']:.0f}ms"
        
        if "navigation_hint" in seg_result:
            hint = seg_result["navigation_hint"]
            if hint in ["left", "right", "straight", "stop"]:
                facts["navigation_hint"] = hint
        
        if facts:
            self.signals.update(SignalEvent(
                event_type=EventType.VLM,
                data={"facts": facts}
            ))
    
    def process_jetracer_vision(self, vision_data: Any) -> None:
        """
        JetRacerProvider.VisionDataをSignalsに注入
        
        Args:
            vision_data: JetRacerProvider.fetch()で取得したvisionデータ
        """
        if vision_data is None:
            return
        
        facts = {}
        
        if hasattr(vision_data, 'road_percentage') and vision_data.road_percentage > 0:
            facts["road_percentage"] = f"{vision_data.road_percentage:.0f}%"
        
        if hasattr(vision_data, 'inference_time_ms') and vision_data.inference_time_ms > 0:
            facts["inference_time"] = f"{vision_data.inference_time_ms:.0f}ms"
        
        if hasattr(vision_data, 'navigation_hint') and vision_data.navigation_hint:
            facts["navigation_hint"] = vision_data.navigation_hint
        
        if facts:
            self.signals.update(SignalEvent(
                event_type=EventType.VLM,
                data={"facts": facts}
            ))
    
    def _inject_result(self, result: VLMAnalysisResult) -> None:
        """解析結果をSignalsに注入"""
        self.analyzer.inject_to_signals(result, self.signals)


# シングルトンインスタンス
_bridge: Optional[VisionToSignalsBridge] = None


def get_vision_bridge() -> VisionToSignalsBridge:
    """VisionToSignalsBridgeを取得（シングルトン）"""
    global _bridge
    if _bridge is None:
        _bridge = VisionToSignalsBridge()
    return _bridge


def reset_vision_bridge() -> None:
    """VisionToSignalsBridgeをリセット"""
    global _bridge
    _bridge = None
```

===========================================
Part 3: フロントエンド v2.1 コンポーネント追加
===========================================

【ファイル】duo-gui/src/lib/types.ts に追加
```typescript
// v2.1 Types
export type SignalsState = {
  jetracer_mode: string
  current_speed: number
  steering_angle: number
  distance_sensors: Record<string, number>
  scene_facts: Record<string, string>
  turn_count: number
  topic_depth: number
  is_stale: boolean
  timestamp: string
}

export type NoveltyStatus = {
  history_length: number
  recent_strategies: string[]
  current_nouns: string[]
}

export type SilenceInfo = {
  type: string
  duration: number
  allow_short: boolean
  sfx: string | null
  bgm_intensity: number
}

export type LiveDialogue = {
  speaker: string
  content: string
  debug?: {
    loop_detected?: boolean
    strategy?: string
    unfilled_slots?: string[]
    few_shot_used?: boolean
  }
}
```

【ファイル】duo-gui/src/components/SignalsPanel.tsx を新規作成
```tsx
import React from 'react'
import type { SignalsState } from '../lib/types'

type Props = {
  signals: SignalsState | null
}

export default function SignalsPanel({ signals }: Props) {
  if (!signals) {
    return (
      <div className="p-4 bg-slate-100 rounded-lg">
        <h3 className="font-medium text-slate-500">Signals: 未接続</h3>
      </div>
    )
  }

  const speedColor = signals.current_speed > 2.5 ? 'text-red-600' : 'text-slate-900'
  const staleColor = signals.is_stale ? 'bg-yellow-100' : 'bg-white'

  return (
    <div className={`p-4 rounded-lg shadow ${staleColor}`}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium">DuoSignals</h3>
        {signals.is_stale && (
          <span className="px-2 py-0.5 text-xs bg-yellow-200 text-yellow-800 rounded">
            STALE
          </span>
        )}
      </div>
      
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-slate-500">Mode:</span>
          <span className="ml-1 font-mono">{signals.jetracer_mode}</span>
        </div>
        <div>
          <span className="text-slate-500">Speed:</span>
          <span className={`ml-1 font-mono ${speedColor}`}>
            {signals.current_speed.toFixed(2)} m/s
          </span>
        </div>
        <div>
          <span className="text-slate-500">Steering:</span>
          <span className="ml-1 font-mono">{signals.steering_angle.toFixed(1)}°</span>
        </div>
        <div>
          <span className="text-slate-500">Turn:</span>
          <span className="ml-1 font-mono">#{signals.turn_count}</span>
        </div>
      </div>

      {/* Scene Facts */}
      {Object.keys(signals.scene_facts).length > 0 && (
        <div className="mt-3 pt-2 border-t">
          <h4 className="text-xs text-slate-500 mb-1">Scene Facts</h4>
          <div className="flex flex-wrap gap-1">
            {Object.entries(signals.scene_facts).map(([key, value]) => (
              <span key={key} className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded">
                {key}: {value}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Topic Depth */}
      {signals.topic_depth > 0 && (
        <div className="mt-2">
          <span className="text-xs text-slate-500">Topic Depth: </span>
          <span className={`text-xs font-mono ${signals.topic_depth >= 3 ? 'text-orange-600' : ''}`}>
            {signals.topic_depth}
          </span>
          {signals.topic_depth >= 3 && (
            <span className="ml-1 text-xs text-orange-600">⚠️ Loop risk</span>
          )}
        </div>
      )}

      {/* Distance Sensors */}
      {Object.keys(signals.distance_sensors).length > 0 && (
        <div className="mt-2">
          <h4 className="text-xs text-slate-500 mb-1">Sensors</h4>
          <div className="flex gap-2 text-xs font-mono">
            {Object.entries(signals.distance_sensors).map(([key, value]) => (
              <span key={key} className="px-1 bg-slate-100 rounded">
                {key}: {typeof value === 'number' ? value.toFixed(0) : value}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

【ファイル】duo-gui/src/components/LivePanel.tsx を新規作成
```tsx
import React, { useState, useEffect, useRef } from 'react'
import type { SignalsState, LiveDialogue, SilenceInfo } from '../lib/types'

const API = (import.meta as any).env?.VITE_API_BASE || ''

type Props = {
  jetracer_url?: string
}

export default function LivePanel({ jetracer_url = 'http://192.168.1.65:8000' }: Props) {
  const [connected, setConnected] = useState(false)
  const [signals, setSignals] = useState<SignalsState | null>(null)
  const [dialogue, setDialogue] = useState<LiveDialogue[]>([])
  const [silence, setSilence] = useState<SilenceInfo | null>(null)
  const [running, setRunning] = useState(false)
  const [frameDesc, setFrameDesc] = useState('')
  const dialogueEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll dialogue
  useEffect(() => {
    dialogueEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [dialogue])

  const connect = async () => {
    try {
      const resp = await fetch(`${API}/api/v2/jetracer/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: jetracer_url, mode: 'vision' })
      })
      const data = await resp.json()
      if (data.status === 'ok') {
        setConnected(true)
      }
    } catch (e) {
      console.error('Connect error:', e)
    }
  }

  const fetchAndGenerate = async () => {
    if (!connected) return

    try {
      // Fetch JetRacer data
      const fetchResp = await fetch(`${API}/api/v2/jetracer/fetch`)
      const fetchData = await fetchResp.json()
      
      if (fetchData.status !== 'ok') return
      
      setFrameDesc(fetchData.frame_description)

      // Get signals state
      const sigResp = await fetch(`${API}/api/v2/signals`)
      const sigData = await sigResp.json()
      if (sigData.status === 'ok') {
        setSignals(sigData.state)
      }

      // Check silence
      const silResp = await fetch(`${API}/api/v2/silence/check`)
      const silData = await silResp.json()
      
      if (silData.should_silence) {
        setSilence(silData.silence)
        return
      }
      setSilence(null)

      // Generate dialogue
      const dialogueResp = await fetch(`${API}/api/v2/live/dialogue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          frame_description: fetchData.frame_description,
          history: dialogue.slice(-10),
          turns: 2
        })
      })
      const dialogueData = await dialogueResp.json()
      
      if (dialogueData.type === 'dialogue') {
        setDialogue(prev => [...prev, ...dialogueData.dialogue])
      }
    } catch (e) {
      console.error('Fetch error:', e)
    }
  }

  // Auto-run loop
  useEffect(() => {
    if (!running) return
    
    const interval = setInterval(fetchAndGenerate, 3000)
    return () => clearInterval(interval)
  }, [running, connected, dialogue])

  return (
    <div className="space-y-4">
      {/* Connection */}
      <div className="flex items-center gap-4">
        <input
          type="text"
          defaultValue={jetracer_url}
          className="flex-1 px-3 py-2 border rounded"
          placeholder="JetRacer URL"
        />
        <button
          onClick={connect}
          disabled={connected}
          className={`px-4 py-2 rounded ${connected ? 'bg-green-500 text-white' : 'bg-blue-500 text-white hover:bg-blue-600'}`}
        >
          {connected ? '✓ Connected' : 'Connect'}
        </button>
      </div>

      {/* Controls */}
      {connected && (
        <div className="flex items-center gap-4">
          <button
            onClick={() => setRunning(!running)}
            className={`px-4 py-2 rounded ${running ? 'bg-red-500' : 'bg-green-500'} text-white`}
          >
            {running ? '⏹ Stop' : '▶ Start'}
          </button>
          <button
            onClick={fetchAndGenerate}
            disabled={running}
            className="px-4 py-2 bg-slate-200 rounded hover:bg-slate-300 disabled:opacity-50"
          >
            🔄 Single Fetch
          </button>
          <button
            onClick={() => setDialogue([])}
            className="px-4 py-2 bg-slate-200 rounded hover:bg-slate-300"
          >
            🗑 Clear
          </button>
        </div>
      )}

      {/* Frame Description */}
      {frameDesc && (
        <div className="p-3 bg-slate-100 rounded text-sm">
          <span className="text-slate-500">📝 Frame: </span>
          {frameDesc}
        </div>
      )}

      {/* Silence Indicator */}
      {silence && (
        <div className="p-3 bg-purple-100 rounded flex items-center gap-2">
          <span className="text-2xl">🤫</span>
          <div>
            <div className="font-medium text-purple-800">Silence: {silence.type}</div>
            <div className="text-sm text-purple-600">Duration: {silence.duration}s</div>
          </div>
        </div>
      )}

      {/* Dialogue */}
      <div className="max-h-96 overflow-y-auto space-y-2 p-4 bg-white rounded-lg shadow">
        {dialogue.map((d, i) => (
          <div key={i} className={`p-2 rounded ${d.speaker === 'やな' ? 'bg-pink-50' : 'bg-blue-50'}`}>
            <div className="flex items-center gap-2">
              <span className="font-medium">{d.speaker === 'やな' ? '👧' : '👧'} {d.speaker}</span>
              {d.debug?.loop_detected && (
                <span className="px-1 text-xs bg-orange-200 text-orange-800 rounded">
                  Loop: {d.debug.strategy}
                </span>
              )}
              {d.debug?.few_shot_used && (
                <span className="px-1 text-xs bg-green-200 text-green-800 rounded">
                  Few-shot
                </span>
              )}
            </div>
            <p className="mt-1">{d.content}</p>
          </div>
        ))}
        <div ref={dialogueEndRef} />
      </div>

      {/* Signals State */}
      {signals && (
        <div className="p-3 bg-slate-50 rounded text-xs">
          <div className="flex flex-wrap gap-2">
            <span>Mode: {signals.jetracer_mode}</span>
            <span>Speed: {signals.current_speed.toFixed(2)}</span>
            <span>Turn: #{signals.turn_count}</span>
            <span>TopicDepth: {signals.topic_depth}</span>
            {signals.is_stale && <span className="text-yellow-600">⚠️ Stale</span>}
          </div>
        </div>
      )}
    </div>
  )
}
```

===========================================
Part 4: 統合テスト
===========================================

【実行手順】

1. サーバーサイドテスト:
   cd C:\work\duo-talk
   conda activate duo-talk
   python -c "from server.api_v2 import v2_api; print('API v2 loaded OK')"

2. VLM Analyzerテスト:
   python -c "from src.vlm_analyzer import VLMAnalyzer; print('VLM Analyzer loaded OK')"

3. Vision Bridgeテスト:
   python -c "from src.vision_to_signals import get_vision_bridge; print('Vision Bridge loaded OK')"

4. サーバー起動:
   python server/api_server.py

5. フロントエンドビルド:
   cd duo-gui
   npm run build

6. ブラウザで http://localhost:5000 にアクセス

【完了報告】
1. 各モジュールのインポートテスト結果
2. サーバー起動確認
3. フロントエンドビルド結果
4. 動作確認（可能であればスクリーンショット）