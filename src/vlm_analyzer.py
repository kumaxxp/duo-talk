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
