"""InputCollector VisionPipeline統合テスト"""

import pytest
from pathlib import Path
from PIL import Image, ImageDraw

from src.input_collector import InputCollector, VisionAnalysis, FrameContext
from src.input_source import InputBundle, InputSource, SourceType


class TestVisionAnalysisAdapter:
    """VisionAnalysis.from_vision_pipeline_result テスト"""

    def test_from_pipeline_result_basic(self):
        """基本的な変換"""
        result = {
            "road_info": {"condition": "straight", "drivable_area": "center"},
            "obstacles": [{"type": "cone", "position": "left"}],
            "warnings": ["curve ahead"],
            "processing_time_ms": 100.0,
        }

        va = VisionAnalysis.from_vision_pipeline_result(result)

        assert va.is_valid
        assert "straight" in va.description
        assert "cone" in va.objects
        assert va.processing_time_ms == 100.0

    def test_from_pipeline_result_with_obstacles(self):
        """障害物情報の変換"""
        result = {
            "obstacles": [
                {"type": "cone", "position": "left"},
                {"type": "wall", "position": "right"},
            ],
            "processing_time_ms": 50.0,
        }

        va = VisionAnalysis.from_vision_pipeline_result(result)

        assert va.is_valid
        assert "cone" in va.description
        assert "cone" in va.objects
        assert "wall" in va.objects

    def test_from_pipeline_result_with_description(self):
        """VLM説明文の使用"""
        result = {
            "description": "灰色の道路にオレンジ色のコーンが配置されています",
            "processing_time_ms": 200.0,
        }

        va = VisionAnalysis.from_vision_pipeline_result(result)

        assert va.is_valid
        assert "灰色" in va.description or "オレンジ" in va.description

    def test_from_pipeline_result_empty(self):
        """空の結果"""
        result = {}
        va = VisionAnalysis.from_vision_pipeline_result(result)

        assert va.description == "解析結果なし"
        assert va.objects == []


class TestInputCollectorVisionPipeline:
    """InputCollector VisionPipeline統合テスト"""

    @pytest.fixture
    def test_image(self, tmp_path):
        """テスト用画像を生成"""
        img = Image.new('RGB', (640, 480), color='gray')
        draw = ImageDraw.Draw(img)
        draw.polygon([(200, 480), (440, 480), (350, 200), (290, 200)], fill='darkgray')
        draw.rectangle([100, 300, 150, 350], fill='orange')

        path = tmp_path / "test_track.png"
        img.save(path)
        return str(path)

    def test_collect_with_image(self, test_image):
        """画像付きInputBundleの収集"""
        collector = InputCollector(use_vision_pipeline=True)

        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.IMAGE_FILE, content=test_image),
            InputSource(source_type=SourceType.TEXT, content="テスト走行"),
        ])

        context = collector.collect(bundle)

        assert context.has_text
        assert context.has_vision
        assert len(context.vision_analyses) == 1
        assert context.vision_analyses[0].is_valid

    def test_collect_text_only(self):
        """テキストのみのInputBundle"""
        collector = InputCollector(use_vision_pipeline=True)

        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="お正月の話"),
        ])

        context = collector.collect(bundle)

        assert context.has_text
        assert not context.has_vision
        assert context.text_description == "お正月の話"

    def test_frame_description_generation(self, test_image):
        """フレーム説明文の生成"""
        collector = InputCollector(use_vision_pipeline=True)

        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.IMAGE_FILE, content=test_image),
            InputSource(source_type=SourceType.TEXT, content="コース走行中"),
        ])

        context = collector.collect(bundle)
        description = context.to_frame_description()

        assert "コース走行中" in description
        assert "【映像情報】" in description

    def test_collector_without_vision_pipeline(self):
        """VisionPipeline無効時のテスト"""
        collector = InputCollector(use_vision_pipeline=False)

        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="テストテキスト"),
        ])

        context = collector.collect(bundle)

        assert context.has_text
        assert context.text_description == "テストテキスト"

    def test_jetracer_camera_without_client(self):
        """JetRacerクライアントなしでのカメラソース処理"""
        collector = InputCollector(use_vision_pipeline=True, jetracer_client=None)

        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.JETRACER_CAM0, content=None),
        ])

        context = collector.collect(bundle)

        # カメラソースがあっても、クライアントなしでは有効な映像なし
        assert len(context.vision_analyses) == 1
        assert "未接続" in context.vision_analyses[0].description


class TestVisionAnalysisProperties:
    """VisionAnalysis プロパティテスト"""

    def test_is_valid_with_description(self):
        """説明文ありの場合は有効"""
        va = VisionAnalysis(description="テスト")
        assert va.is_valid

    def test_is_valid_without_description(self):
        """説明文なしの場合は無効"""
        va = VisionAnalysis()
        assert not va.is_valid

    def test_processing_time_default(self):
        """処理時間のデフォルト値"""
        va = VisionAnalysis()
        assert va.processing_time_ms == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
