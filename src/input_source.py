"""
duo-talk v2.1 - Input Source Abstraction
異なる入力ソースを統一的に扱う抽象化層

設計方針：
- Text/Image/JetRacerセンサーなど、異なる入力ソースを統一的に扱う
- Console/RUNS/LIVE の3つの実行パスで同じ入力形式を使用可能
- dataclass で型安全性を確保
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class SourceType(Enum):
    """入力ソースタイプ"""
    TEXT = "text"                      # テキスト入力
    IMAGE_FILE = "image_file"          # ローカル画像ファイル
    IMAGE_URL = "image_url"            # 画像URL
    JETRACER_CAM0 = "jetracer_cam0"    # JetRacerカメラ0
    JETRACER_CAM1 = "jetracer_cam1"    # JetRacerカメラ1
    JETRACER_SENSOR = "jetracer_sensor"  # JetRacerセンサーデータ


@dataclass
class InputSource:
    """
    単一の入力ソースを表現するデータクラス

    Attributes:
        source_type: 入力ソースのタイプ
        content: テキスト内容、ファイルパス、またはURL
        raw_data: 画像などのバイナリデータ
        metadata: 追加のメタデータ（センサー値、タイムスタンプなど）
        timestamp: 入力が作成された時刻

    Examples:
        # テキスト入力
        text_source = InputSource(
            source_type=SourceType.TEXT,
            content="お正月の準備について話して"
        )

        # 画像ファイル入力
        image_source = InputSource(
            source_type=SourceType.IMAGE_FILE,
            content="tests/images/sample.jpg"
        )

        # JetRacerセンサー入力
        sensor_source = InputSource(
            source_type=SourceType.JETRACER_SENSOR,
            metadata={"speed": 1.5, "steering": 0.2}
        )
    """
    source_type: SourceType
    content: Optional[str] = None
    raw_data: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """文字列からSourceTypeへの変換"""
        if isinstance(self.source_type, str):
            self.source_type = SourceType(self.source_type)

    @property
    def is_available(self) -> bool:
        """
        入力データが利用可能かどうかを判定

        Returns:
            bool: content または raw_data が存在すれば True
        """
        return self.content is not None or self.raw_data is not None

    @property
    def is_image(self) -> bool:
        """
        画像系のソースかどうかを判定

        Returns:
            bool: 画像系ソースの場合 True
        """
        return self.source_type in [
            SourceType.IMAGE_FILE,
            SourceType.IMAGE_URL,
            SourceType.JETRACER_CAM0,
            SourceType.JETRACER_CAM1,
        ]

    @property
    def is_jetracer(self) -> bool:
        """
        JetRacer関連のソースかどうかを判定

        Returns:
            bool: JetRacer系ソースの場合 True
        """
        return self.source_type in [
            SourceType.JETRACER_CAM0,
            SourceType.JETRACER_CAM1,
            SourceType.JETRACER_SENSOR,
        ]


@dataclass
class InputBundle:
    """
    複数の入力ソースをまとめて扱うバンドル

    Attributes:
        sources: 入力ソースのリスト
        is_interrupt: 対話中の割り込み入力かどうか

    Examples:
        # 複数ソースのバンドル
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="話題"),
            InputSource(source_type=SourceType.IMAGE_FILE, content="image.jpg"),
        ])

        # テキスト取得
        text = bundle.get_text()

        # 画像ソース一覧
        images = bundle.get_images()
    """
    sources: List[InputSource] = field(default_factory=list)
    is_interrupt: bool = False

    def get_text(self) -> Optional[str]:
        """
        TEXT タイプのソースから content を取得

        Returns:
            Optional[str]: テキスト内容、なければ None
        """
        for source in self.sources:
            if source.source_type == SourceType.TEXT and source.content:
                return source.content
        return None

    def get_images(self) -> List[InputSource]:
        """
        画像系ソースのリストを取得

        Returns:
            List[InputSource]: 画像系ソースのリスト
        """
        return [s for s in self.sources if s.is_image]

    def get_jetracer_sources(self) -> List[InputSource]:
        """
        JetRacer関連ソースのリストを取得

        Returns:
            List[InputSource]: JetRacer系ソースのリスト
        """
        return [s for s in self.sources if s.is_jetracer]

    def has_jetracer_sensor(self) -> bool:
        """
        JETRACER_SENSOR タイプのソースが存在するか

        Returns:
            bool: JETRACER_SENSOR があれば True
        """
        return any(
            s.source_type == SourceType.JETRACER_SENSOR
            for s in self.sources
        )

    def has_image(self) -> bool:
        """
        画像系ソースが存在するか

        Returns:
            bool: 画像系ソースがあれば True
        """
        return any(s.is_image for s in self.sources)

    def has_text(self) -> bool:
        """
        テキストソースが存在するか

        Returns:
            bool: TEXT ソースがあれば True
        """
        return any(
            s.source_type == SourceType.TEXT and s.content
            for s in self.sources
        )

    def add(self, source: InputSource) -> None:
        """
        ソースを追加

        Args:
            source: 追加する InputSource
        """
        self.sources.append(source)

    def get_by_type(self, source_type: SourceType) -> List[InputSource]:
        """
        指定タイプのソースを取得

        Args:
            source_type: 取得するソースタイプ

        Returns:
            List[InputSource]: 指定タイプのソースリスト
        """
        return [s for s in self.sources if s.source_type == source_type]

    @property
    def is_empty(self) -> bool:
        """
        バンドルが空かどうか

        Returns:
            bool: ソースが1つもなければ True
        """
        return len(self.sources) == 0

    def __len__(self) -> int:
        """ソースの数を返す"""
        return len(self.sources)

    def __iter__(self):
        """ソースをイテレート"""
        return iter(self.sources)
