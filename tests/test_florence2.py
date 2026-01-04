"""Florence-2 テスト"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFlorence2Config:
    """Florence2Config テスト"""

    def test_default_config(self):
        from src.florence2_detector import Florence2Config

        config = Florence2Config()
        assert config.model_name == "microsoft/Florence-2-large"
        assert config.device == "cuda"
        assert config.max_objects == 20
        assert config.confidence_threshold == 0.3

    def test_custom_config(self):
        from src.florence2_detector import Florence2Config

        config = Florence2Config(
            model_name="microsoft/Florence-2-base",
            device="cpu",
            max_objects=10,
        )
        assert config.model_name == "microsoft/Florence-2-base"
        assert config.device == "cpu"
        assert config.max_objects == 10


class TestFlorence2Detector:
    """Florence2Detector テスト"""

    def test_singleton(self):
        from src.florence2_detector import Florence2Detector

        # シングルトンをリセット
        Florence2Detector._instance = None

        d1 = Florence2Detector()
        d2 = Florence2Detector()
        assert d1 is d2

    def test_is_loaded_initial(self):
        from src.florence2_detector import Florence2Detector

        Florence2Detector._instance = None
        detector = Florence2Detector()
        assert not detector.is_loaded

    def test_get_position_label(self):
        from src.florence2_detector import Florence2Detector

        Florence2Detector._instance = None
        detector = Florence2Detector()

        assert detector._get_position_label(0.1) == "left"
        assert detector._get_position_label(0.5) == "center"
        assert detector._get_position_label(0.9) == "right"

    def test_estimate_distance(self):
        from src.florence2_detector import Florence2Detector

        Florence2Detector._instance = None
        detector = Florence2Detector()

        assert detector._estimate_distance({"width": 0.5, "height": 0.5}) == "near"
        assert detector._estimate_distance({"width": 0.2, "height": 0.2}) == "medium"
        assert detector._estimate_distance({"width": 0.1, "height": 0.1}) == "far"


class TestDetectionResult:
    """DetectionResult テスト"""

    def test_default_values(self):
        from src.florence2_detector import DetectionResult

        result = DetectionResult()
        assert result.objects == []
        assert result.caption == ""
        assert result.processing_time_ms == 0.0
        assert result.error is None


class TestVisionPipeline:
    """VisionPipeline テスト"""

    def test_default_config(self):
        from src.vision_pipeline import VisionPipelineConfig, VisionMode

        config = VisionPipelineConfig()
        assert config.mode == VisionMode.VLM_ONLY
        assert config.florence_enabled is True
        assert config.florence_auto_unload is True

    def test_vision_mode_enum(self):
        from src.vision_pipeline import VisionMode

        assert VisionMode.VLM_ONLY.value == "vlm_only"
        assert VisionMode.FLORENCE_ONLY.value == "florence_only"
        assert VisionMode.VLM_WITH_FLORENCE.value == "vlm_with_florence"
        assert VisionMode.FLORENCE_THEN_LLM.value == "florence_then_llm"

    def test_build_vlm_prompt(self):
        from src.vision_pipeline import VisionPipeline

        pipeline = VisionPipeline()
        prompt = pipeline._build_vlm_prompt("")

        assert "JetRacer" in prompt
        assert "路面状態" in prompt
        assert "障害物" in prompt

    def test_build_vlm_prompt_with_context(self):
        from src.vision_pipeline import VisionPipeline

        pipeline = VisionPipeline()
        prompt = pipeline._build_vlm_prompt("追加のコンテキスト")

        assert "追加のコンテキスト" in prompt

    def test_format_florence_for_vlm_empty(self):
        from src.vision_pipeline import VisionPipeline

        pipeline = VisionPipeline()
        result = pipeline._format_florence_for_vlm({})
        assert result == ""

    def test_format_florence_for_vlm(self):
        from src.vision_pipeline import VisionPipeline

        pipeline = VisionPipeline()
        florence_result = {
            "obstacles": [
                {"type": "cone", "position": "right", "distance_estimate": "near"}
            ],
            "objects": [
                {"label": "road", "position": "center"}
            ]
        }
        result = pipeline._format_florence_for_vlm(florence_result)

        assert "cone" in result
        assert "right" in result
        assert "road" in result

    def test_parse_vlm_response_with_json(self):
        from src.vision_pipeline import VisionPipeline

        pipeline = VisionPipeline()
        response = '''分析結果です。
```json
{
  "road_condition": "straight",
  "obstacles": [{"type": "cone", "position": "right", "distance": "near"}],
  "drivable_area": "left and center",
  "warnings": ["Cone on right side"]
}
```
以上です。'''

        result = pipeline._parse_vlm_response(response)

        assert result["road_info"]["condition"] == "straight"
        assert len(result["obstacles"]) == 1
        assert result["obstacles"][0]["type"] == "cone"

    def test_parse_vlm_response_no_json(self):
        from src.vision_pipeline import VisionPipeline

        pipeline = VisionPipeline()
        response = "直進道路です。右側にコーンがあります。"

        result = pipeline._parse_vlm_response(response)

        assert result["description"] == response
        assert result["obstacles"] == []


class TestHelperFunctions:
    """ヘルパー関数テスト"""

    def test_get_florence2_detector(self):
        from src.florence2_detector import get_florence2_detector, Florence2Detector

        Florence2Detector._instance = None

        d1 = get_florence2_detector()
        d2 = get_florence2_detector()
        assert d1 is d2

    def test_get_vision_pipeline(self):
        from src.vision_pipeline import get_vision_pipeline
        import src.vision_pipeline as vp

        vp._pipeline = None

        p1 = get_vision_pipeline()
        p2 = get_vision_pipeline()
        assert p1 is p2
