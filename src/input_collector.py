"""
duo-talk v2.1 - Input Collector
InputBundleから入力を収集し、FrameContextに変換する

設計方針：
- Graceful Degradation: JetRacer接続失敗時はエラーではなくNoneを返す
- 遅延初期化: VisionProcessorは必要になるまでインスタンス化しない
- 統一インターフェース: 異なる入力ソースを統一的に処理
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from src.input_source import InputBundle, InputSource, SourceType

# 型ヒント用（循環インポート回避）
if TYPE_CHECKING:
    from src.jetracer_client import JetRacerClient, JetRacerState
    from src.vision_processor import VisionProcessor


@dataclass
class VisionAnalysis:
    """
    画像解析結果を表現するデータクラス

    Attributes:
        description: 画像の説明文
        objects: 検出されたオブジェクトのリスト
        scene_type: シーンタイプ（観光地、室内など）
        raw_result: VisionProcessorからの生の解析結果
    """
    description: str = ""
    objects: List[str] = field(default_factory=list)
    scene_type: str = ""
    raw_result: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        """有効な解析結果かどうか"""
        return bool(self.description)


@dataclass
class FrameContext:
    """
    対話生成に必要なフレーム情報を統合するデータクラス

    Attributes:
        text_description: テキストによる状況説明
        vision_analyses: 画像解析結果のリスト
        sensor_data: JetRacerセンサーデータ
        timestamp: コンテキスト作成時刻

    Examples:
        context = FrameContext(
            text_description="お正月の準備",
            vision_analyses=[VisionAnalysis(description="神社の境内")],
        )
        desc = context.to_frame_description()
    """
    text_description: Optional[str] = None
    vision_analyses: List[VisionAnalysis] = field(default_factory=list)
    sensor_data: Optional['JetRacerState'] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_frame_description(self) -> str:
        """
        全情報を統合したフレーム説明文を生成

        Returns:
            str: フレーム説明文
        """
        parts = []

        # テキスト説明
        if self.text_description:
            parts.append(self.text_description)

        # 映像情報
        if self.vision_analyses:
            vision_parts = []
            for va in self.vision_analyses:
                if va.description:
                    vision_parts.append(va.description)
            if vision_parts:
                parts.append(f"【映像情報】\n{chr(10).join(vision_parts)}")

        # センサー情報
        if self.sensor_data:
            sensor_info = self._format_sensor_data()
            if sensor_info:
                parts.append(f"【センサー】\n{sensor_info}")

        if not parts:
            return "状況不明"

        return "\n\n".join(parts)

    def _format_sensor_data(self) -> str:
        """センサーデータをフォーマット"""
        if not self.sensor_data:
            return ""

        lines = []
        sd = self.sensor_data

        # 速度・ステアリング
        if hasattr(sd, 'speed') and sd.speed is not None:
            lines.append(f"速度: {sd.speed:.2f} m/s")
        if hasattr(sd, 'steering') and sd.steering is not None:
            lines.append(f"ステアリング: {sd.steering:.2f}")

        # 温度
        if hasattr(sd, 'temperature') and sd.temperature:
            lines.append(f"温度: {sd.temperature:.1f}°C")

        # 距離センサー
        if hasattr(sd, 'ultrasonic_cm') and sd.ultrasonic_cm:
            lines.append(f"前方距離: {sd.ultrasonic_cm:.1f} cm")

        # モーター状態
        if hasattr(sd, 'motor_temp') and sd.motor_temp:
            lines.append(f"モーター温度: {sd.motor_temp:.1f}°C")

        return ", ".join(lines) if lines else ""

    @property
    def has_vision(self) -> bool:
        """映像情報があるか"""
        return any(va.is_valid for va in self.vision_analyses)

    @property
    def has_sensor(self) -> bool:
        """センサー情報があるか"""
        return self.sensor_data is not None

    @property
    def has_text(self) -> bool:
        """テキスト情報があるか"""
        return bool(self.text_description)


class InputCollector:
    """
    InputBundleから入力を収集し、FrameContextに変換するクラス

    Attributes:
        jetracer: JetRacerClient インスタンス（オプション）
        vision_processor: VisionProcessor インスタンス（遅延初期化）

    Examples:
        collector = InputCollector()
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="話題")
        ])
        context = collector.collect(bundle)
        description = context.to_frame_description()
    """

    def __init__(
        self,
        jetracer_client: Optional['JetRacerClient'] = None,
        vision_processor: Optional['VisionProcessor'] = None
    ):
        """
        Args:
            jetracer_client: JetRacerClient インスタンス（Noneなら未接続扱い）
            vision_processor: VisionProcessor インスタンス（Noneなら遅延初期化）
        """
        self.jetracer = jetracer_client
        self._vision_processor = vision_processor
        self._vision_processor_initialized = vision_processor is not None

    @property
    def vision_processor(self) -> Optional['VisionProcessor']:
        """VisionProcessorの遅延初期化"""
        if not self._vision_processor_initialized:
            try:
                from src.vision_processor import VisionProcessor
                self._vision_processor = VisionProcessor()
                self._vision_processor_initialized = True
            except Exception as e:
                print(f"[InputCollector] VisionProcessor initialization failed: {e}")
                self._vision_processor = None
                self._vision_processor_initialized = True
        return self._vision_processor

    def collect(self, bundle: InputBundle) -> FrameContext:
        """
        InputBundleの各ソースを処理してFrameContextを生成

        Args:
            bundle: 入力ソースのバンドル

        Returns:
            FrameContext: 統合されたフレーム情報
        """
        context = FrameContext()

        # テキスト取得
        text = bundle.get_text()
        if text:
            context.text_description = text

        # 画像解析
        vision_analyses = []
        for source in bundle.get_images():
            analysis = self._analyze_image(source)
            if analysis:
                vision_analyses.append(analysis)
        context.vision_analyses = vision_analyses

        # JetRacerセンサー取得
        if bundle.has_jetracer_sensor():
            sensor_data = self._fetch_jetracer_sensor()
            context.sensor_data = sensor_data

        context.timestamp = datetime.now()
        return context

    def _analyze_image(self, source: InputSource) -> Optional[VisionAnalysis]:
        """
        画像ソースを解析

        Args:
            source: 画像系の InputSource

        Returns:
            Optional[VisionAnalysis]: 解析結果、失敗時はNone
        """
        try:
            if source.source_type == SourceType.IMAGE_FILE:
                return self._analyze_image_file(source)
            elif source.source_type == SourceType.IMAGE_URL:
                return self._analyze_image_url(source)
            elif source.source_type in [SourceType.JETRACER_CAM0, SourceType.JETRACER_CAM1]:
                return self._analyze_jetracer_camera(source)
            else:
                return None
        except Exception as e:
            print(f"[InputCollector] Image analysis failed: {e}")
            return None

    def _analyze_image_file(self, source: InputSource) -> Optional[VisionAnalysis]:
        """ローカル画像ファイルを解析"""
        if not source.content:
            return None

        vp = self.vision_processor
        if not vp:
            print("[InputCollector] VisionProcessor not available")
            return None

        try:
            result = vp.analyze_image(source.content)

            if result.get("status") == "error":
                print(f"[InputCollector] VisionProcessor error: {result.get('error')}")
                return None

            # 解析結果をVisionAnalysisに変換
            visual_info = result.get("visual_info", {})
            raw_text = result.get("raw_text", "")

            return VisionAnalysis(
                description=raw_text or visual_info.get("description", ""),
                objects=visual_info.get("objects", []),
                scene_type=visual_info.get("scene_type", ""),
                raw_result=result
            )
        except Exception as e:
            print(f"[InputCollector] Image file analysis error: {e}")
            return None

    def _analyze_image_url(self, source: InputSource) -> Optional[VisionAnalysis]:
        """画像URLを解析（現時点ではスタブ）"""
        # TODO: URL画像のダウンロードと解析を実装
        return VisionAnalysis(
            description=f"URL画像: {source.content}",
            raw_result={"source": "url", "url": source.content}
        )

    def _analyze_jetracer_camera(self, source: InputSource) -> Optional[VisionAnalysis]:
        """JetRacerカメラ映像を解析（現時点ではスタブ）"""
        camera_id = "0" if source.source_type == SourceType.JETRACER_CAM0 else "1"
        # TODO: JetRacerカメラからの映像取得と解析を実装
        return VisionAnalysis(
            description=f"JetRacerカメラ{camera_id}映像",
            raw_result={"source": "jetracer_camera", "camera_id": camera_id}
        )

    def _fetch_jetracer_sensor(self) -> Optional['JetRacerState']:
        """
        JetRacerセンサーを取得（失敗時はNone、エラーにしない）

        Returns:
            Optional[JetRacerState]: センサーデータ、取得失敗時はNone
        """
        if not self.jetracer:
            return None

        try:
            return self.jetracer.fetch_and_parse()
        except Exception as e:
            print(f"[InputCollector] JetRacer sensor fetch failed: {e}")
            return None
