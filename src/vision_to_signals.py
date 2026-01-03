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
