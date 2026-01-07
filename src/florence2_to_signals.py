"""
duo-talk v2.2 - Florence-2 to DuoSignals Bridge
Florence-2 Dockerサービスの出力をDuoSignalsに変換・注入

機能:
- Florence-2でcaption/object detection実行
- 結果をscene_factsに構造化
- DuoSignalsに自動注入
"""

from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.signals import DuoSignals, SignalEvent, EventType
from src.florence2_client import Florence2Client, Florence2Result, get_florence2_client


@dataclass
class Florence2AnalysisResult:
    """Florence-2解析結果"""
    caption: str = ""
    detailed_caption: str = ""
    objects: List[str] = field(default_factory=list)
    object_count: int = 0
    bboxes: List[List[float]] = field(default_factory=list)
    
    # メタデータ
    processing_time_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_scene_facts(self) -> Dict[str, str]:
        """DuoSignals.scene_facts用の辞書に変換"""
        facts = {}
        
        # キャプション（短い方を優先）
        if self.caption:
            facts["caption"] = self.caption
        
        # 検出物体
        if self.objects:
            # 重複を除去して上位5個
            unique_objects = list(dict.fromkeys(self.objects))[:5]
            facts["objects"] = ", ".join(unique_objects)
            facts["object_count"] = str(len(self.objects))
        
        # シーンタイプ推定
        scene_type = self._estimate_scene_type()
        if scene_type:
            facts["scene_type"] = scene_type
        
        # 処理時間（デバッグ用）
        facts["vision_time_ms"] = f"{self.processing_time_ms:.0f}"
        
        return facts
    
    def _estimate_scene_type(self) -> str:
        """検出物体からシーンタイプを推定"""
        objects_lower = [o.lower() for o in self.objects]
        caption_lower = self.caption.lower() + " " + self.detailed_caption.lower()
        
        # レーシング/走行系
        racing_keywords = ["car", "vehicle", "track", "road", "cone", "wheel", "racing"]
        if any(kw in caption_lower or kw in " ".join(objects_lower) for kw in racing_keywords):
            return "racing"
        
        # 室内
        indoor_keywords = ["room", "indoor", "floor", "carpet", "table", "chair", "bed"]
        if any(kw in caption_lower or kw in " ".join(objects_lower) for kw in indoor_keywords):
            return "indoor"
        
        # 屋外
        outdoor_keywords = ["outdoor", "sky", "tree", "grass", "building", "street"]
        if any(kw in caption_lower or kw in " ".join(objects_lower) for kw in outdoor_keywords):
            return "outdoor"
        
        return "unknown"
    
    def to_frame_description(self) -> str:
        """フレーム説明文に変換（Character用）"""
        parts = []
        
        # キャプション
        if self.caption:
            parts.append(f"【視覚情報】{self.caption}")
        
        # 検出物体
        if self.objects:
            unique_objects = list(dict.fromkeys(self.objects))[:5]
            parts.append(f"【検出物体】{', '.join(unique_objects)}")
        
        return "\n".join(parts) if parts else "【視覚情報】取得中..."


class Florence2ToSignals:
    """
    Florence-2解析結果をDuoSignalsに変換・注入するブリッジ
    
    使用例:
        bridge = Florence2ToSignals()
        
        # 画像解析 → Signals注入
        result = bridge.process_image("path/to/image.jpg")
        
        # または画像バイト列から
        result = bridge.process_image_bytes(image_bytes)
        
        # scene_factsだけ取得（注入なし）
        facts = bridge.analyze_only("path/to/image.jpg")
    """
    
    def __init__(
        self,
        client: Optional[Florence2Client] = None,
        signals: Optional[DuoSignals] = None,
        auto_inject: bool = True,
        use_detailed_caption: bool = False,
    ):
        """
        Args:
            client: Florence2Client（Noneならシングルトン使用）
            signals: DuoSignals（Noneならシングルトン使用）
            auto_inject: 解析後に自動でSignalsに注入
            use_detailed_caption: 詳細キャプションを使用
        """
        self._client = client
        self._signals = signals
        self.auto_inject = auto_inject
        self.use_detailed_caption = use_detailed_caption
    
    @property
    def client(self) -> Florence2Client:
        """Florence2Clientを取得（遅延初期化）"""
        if self._client is None:
            self._client = get_florence2_client()
        return self._client
    
    @property
    def signals(self) -> DuoSignals:
        """DuoSignalsを取得（遅延初期化）"""
        if self._signals is None:
            self._signals = DuoSignals()
        return self._signals
    
    def is_service_ready(self) -> bool:
        """Florence-2サービスが利用可能か確認"""
        try:
            return self.client.is_ready()
        except Exception:
            return False
    
    def process_image(
        self,
        image: Union[str, bytes, Path],
        inject: Optional[bool] = None,
    ) -> Florence2AnalysisResult:
        """
        画像をFlorence-2で解析し、Signalsに注入
        
        Args:
            image: 画像（ファイルパス、bytes、Path）
            inject: Signalsに注入するか（Noneならauto_inject設定に従う）
        
        Returns:
            Florence2AnalysisResult: 解析結果
        """
        start_time = datetime.now()
        result = Florence2AnalysisResult()
        
        try:
            # 1. キャプション取得
            caption_result = self.client.caption(image, detailed=self.use_detailed_caption)
            if caption_result.success:
                result.caption = caption_result.text
            else:
                result.error = caption_result.error
            
            # 2. 物体検出
            od_result = self.client.detect_objects(image)
            if od_result.success:
                result.objects = od_result.objects or []
                result.bboxes = od_result.bboxes or []
                result.object_count = len(result.objects)
            
            result.success = caption_result.success or od_result.success
            result.processing_time_ms = (
                caption_result.processing_time_ms + od_result.processing_time_ms
            )
            
        except Exception as e:
            result.success = False
            result.error = str(e)
            result.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        result.timestamp = datetime.now()
        
        # 3. Signalsに注入
        should_inject = inject if inject is not None else self.auto_inject
        if should_inject and result.success:
            self.inject_to_signals(result)
        
        return result
    
    def process_image_bytes(
        self,
        image_bytes: bytes,
        inject: Optional[bool] = None,
    ) -> Florence2AnalysisResult:
        """
        画像バイト列をFlorence-2で解析
        
        Args:
            image_bytes: 画像データ（bytes）
            inject: Signalsに注入するか
        
        Returns:
            Florence2AnalysisResult
        """
        return self.process_image(image_bytes, inject=inject)
    
    def analyze_only(
        self,
        image: Union[str, bytes, Path],
    ) -> Dict[str, str]:
        """
        画像を解析してscene_factsのみ返す（注入なし）
        
        Args:
            image: 画像
        
        Returns:
            scene_facts辞書
        """
        result = self.process_image(image, inject=False)
        return result.to_scene_facts()
    
    def inject_to_signals(self, result: Florence2AnalysisResult) -> None:
        """解析結果をDuoSignalsに注入"""
        facts = result.to_scene_facts()
        self.signals.update(SignalEvent(
            event_type=EventType.VLM,
            data={"facts": facts}
        ))
    
    def get_current_scene_facts(self) -> Dict[str, str]:
        """現在のscene_factsを取得"""
        state = self.signals.snapshot()
        return state.scene_facts


# シングルトンインスタンス
_bridge: Optional[Florence2ToSignals] = None


def get_florence2_bridge() -> Florence2ToSignals:
    """Florence2ToSignalsを取得（シングルトン）"""
    global _bridge
    if _bridge is None:
        _bridge = Florence2ToSignals()
    return _bridge


def reset_florence2_bridge() -> None:
    """Florence2ToSignalsをリセット"""
    global _bridge
    _bridge = None


# ============================================================
# 便利関数
# ============================================================

def analyze_image_to_signals(
    image: Union[str, bytes, Path],
    signals: Optional[DuoSignals] = None,
) -> Florence2AnalysisResult:
    """
    画像をFlorence-2で解析してSignalsに注入（ワンライナー）
    
    Args:
        image: 画像
        signals: DuoSignals（Noneならシングルトン）
    
    Returns:
        解析結果
    """
    bridge = Florence2ToSignals(signals=signals)
    return bridge.process_image(image)


def get_scene_facts_from_image(
    image: Union[str, bytes, Path],
) -> Dict[str, str]:
    """
    画像からscene_factsを取得（注入なし）
    
    Args:
        image: 画像
    
    Returns:
        scene_facts辞書
    """
    bridge = Florence2ToSignals(auto_inject=False)
    result = bridge.process_image(image, inject=False)
    return result.to_scene_facts()


# ============================================================
# CLI Test
# ============================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m src.florence2_to_signals <image_path>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    print(f"Analyzing: {image_path}")
    print("=" * 50)
    
    bridge = Florence2ToSignals()
    
    # サービス確認
    if not bridge.is_service_ready():
        print("❌ Florence-2 service not ready!")
        print("   Run: ./scripts/docker_services.sh start")
        sys.exit(1)
    
    # 解析
    result = bridge.process_image(image_path)
    
    print(f"Success: {result.success}")
    print(f"Caption: {result.caption}")
    print(f"Objects: {result.objects}")
    print(f"Object Count: {result.object_count}")
    print(f"Processing Time: {result.processing_time_ms:.1f}ms")
    print()
    print("Scene Facts:")
    for k, v in result.to_scene_facts().items():
        print(f"  {k}: {v}")
    print()
    print("Frame Description:")
    print(result.to_frame_description())
    
    # Signals確認
    state = bridge.signals.snapshot()
    print()
    print("DuoSignals.scene_facts:")
    for k, v in state.scene_facts.items():
        print(f"  {k}: {v}")
