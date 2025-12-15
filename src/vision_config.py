"""
Vision processing configuration management.
Supports multiple VLM types and combination approaches.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, List


class VisionMode(str, Enum):
    """Vision processing mode"""
    SINGLE_VLM = "single_vlm"                    # VLMのみで画像解析と説明生成
    VLM_PLUS_SEGMENTATION = "vlm_segmentation"   # VLM + セグメンテーションモデル併用
    SEGMENTATION_PLUS_LLM = "segmentation_llm"   # セグメンテーション → テキストLLMで説明生成


class VLMType(str, Enum):
    """Available Vision Language Models (画像入力対応モデルのみ)"""
    LLAVA_7B = "llava:7b"
    LLAVA_13B = "llava:13b"
    LLAVA_34B = "llava:34b"
    LLAVA_LATEST = "llava:latest"
    LLAMA_VISION_11B = "llama3.2-vision:11b"
    LLAMA_VISION_90B = "llama3.2-vision:90b"
    BAKLLAVA = "bakllava:latest"
    MOONDREAM = "moondream:latest"
    CUSTOM = "custom"


class TextLLMType(str, Enum):
    """Available Text LLMs (セグメンテーション結果の説明生成用)"""
    GEMMA3_4B = "gemma3:4b"
    GEMMA3_12B = "gemma3:12b"
    GEMMA3_27B = "gemma3:27b"
    QWEN2_5_7B = "qwen2.5:7b"
    QWEN2_5_14B = "qwen2.5:14b"
    MISTRAL_7B = "mistral:7b"
    LLAMA3_8B = "llama3:8b"
    CUSTOM = "custom"


class SegmentationModel(str, Enum):
    """Available segmentation models"""
    FLORENCE2_BASE = "florence2-base"
    FLORENCE2_LARGE = "florence2-large"
    GROUNDED_SAM2 = "grounded-sam2"
    GROUNDING_DINO = "grounding-dino"
    NONE = "none"


@dataclass
class VisionConfig:
    """Vision processing configuration"""

    # Mode selection
    mode: VisionMode = VisionMode.SINGLE_VLM

    # VLM settings (for modes using VLM)
    vlm_type: VLMType = VLMType.LLAVA_LATEST
    vlm_custom_model: str = ""  # Custom VLM model name

    # Text LLM settings (for SEGMENTATION_PLUS_LLM mode)
    text_llm_type: TextLLMType = TextLLMType.GEMMA3_12B
    text_llm_custom_model: str = ""  # Custom text LLM model name

    # Segmentation settings
    segmentation_model: SegmentationModel = SegmentationModel.NONE
    segmentation_confidence_threshold: float = 0.5

    # Processing options
    enable_ocr: bool = False
    enable_depth_estimation: bool = False
    max_objects: int = 20

    # Performance settings
    vlm_temperature: float = 0.3
    vlm_max_tokens: int = 1024
    llm_temperature: float = 0.5
    llm_max_tokens: int = 512
    use_gpu: bool = True
    batch_size: int = 1

    # Output format
    output_language: str = "ja"  # ja or en
    include_coordinates: bool = True
    include_confidence: bool = True

    # Prompt customization
    custom_detection_prompt: str = ""
    custom_description_prompt: str = ""

    def get_vlm_model_name(self) -> str:
        """Get actual VLM model name for Ollama"""
        if self.vlm_type == VLMType.CUSTOM:
            return self.vlm_custom_model
        return self.vlm_type.value

    def get_text_llm_model_name(self) -> str:
        """Get actual text LLM model name for Ollama"""
        if self.text_llm_type == TextLLMType.CUSTOM:
            return self.text_llm_custom_model
        return self.text_llm_type.value

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert enums to strings
        data["mode"] = self.mode.value
        data["vlm_type"] = self.vlm_type.value
        data["text_llm_type"] = self.text_llm_type.value
        data["segmentation_model"] = self.segmentation_model.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "VisionConfig":
        """Create from dictionary"""
        # Make a copy to avoid modifying the original
        data = data.copy()
        # Convert strings back to enums
        if "mode" in data:
            data["mode"] = VisionMode(data["mode"])
        if "vlm_type" in data:
            data["vlm_type"] = VLMType(data["vlm_type"])
        if "text_llm_type" in data:
            data["text_llm_type"] = TextLLMType(data["text_llm_type"])
        if "segmentation_model" in data:
            data["segmentation_model"] = SegmentationModel(data["segmentation_model"])
        # Filter out unknown fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class VisionPreset:
    """Predefined vision configuration presets"""
    name: str
    description: str
    config: VisionConfig

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "config": self.config.to_dict()
        }


# Predefined presets
PRESETS: List[VisionPreset] = [
    VisionPreset(
        name="lightweight",
        description="軽量モード - LLaVA のみ（低VRAM環境向け、約5GB）",
        config=VisionConfig(
            mode=VisionMode.SINGLE_VLM,
            vlm_type=VLMType.LLAVA_LATEST,
            segmentation_model=SegmentationModel.NONE,
        )
    ),
    VisionPreset(
        name="balanced",
        description="バランスモード - LLaMA 3.2 Vision 11B（約7GB）",
        config=VisionConfig(
            mode=VisionMode.SINGLE_VLM,
            vlm_type=VLMType.LLAMA_VISION_11B,
            segmentation_model=SegmentationModel.NONE,
        )
    ),
    VisionPreset(
        name="detailed_detection",
        description="詳細検出モード - Florence-2 + Gemma3（位置情報付き）",
        config=VisionConfig(
            mode=VisionMode.SEGMENTATION_PLUS_LLM,
            vlm_type=VLMType.LLAVA_LATEST,  # Used as fallback
            text_llm_type=TextLLMType.GEMMA3_12B,
            segmentation_model=SegmentationModel.FLORENCE2_LARGE,
            include_coordinates=True,
            max_objects=30,
        )
    ),
    VisionPreset(
        name="full_analysis",
        description="フル解析モード - VLM + セグメンテーション併用（高精度）",
        config=VisionConfig(
            mode=VisionMode.VLM_PLUS_SEGMENTATION,
            vlm_type=VLMType.LLAMA_VISION_11B,
            text_llm_type=TextLLMType.GEMMA3_12B,
            segmentation_model=SegmentationModel.FLORENCE2_LARGE,
            enable_ocr=True,
            include_coordinates=True,
        )
    ),
    VisionPreset(
        name="fast_detection",
        description="高速検出モード - Florence-2 Base + 軽量LLM",
        config=VisionConfig(
            mode=VisionMode.SEGMENTATION_PLUS_LLM,
            vlm_type=VLMType.LLAVA_LATEST,
            text_llm_type=TextLLMType.GEMMA3_4B,
            segmentation_model=SegmentationModel.FLORENCE2_BASE,
            max_objects=15,
        )
    ),
]


class VisionConfigManager:
    """Manages vision configuration persistence"""

    DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "vision_settings.json"

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._current_config: Optional[VisionConfig] = None

    def load(self) -> VisionConfig:
        """Load configuration from file"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._current_config = VisionConfig.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Warning: Failed to load vision config: {e}")
                self._current_config = VisionConfig()
        else:
            self._current_config = VisionConfig()

        return self._current_config

    def save(self, config: VisionConfig) -> bool:
        """Save configuration to file"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            self._current_config = config
            return True
        except IOError as e:
            print(f"Error saving vision config: {e}")
            return False

    def get_current(self) -> VisionConfig:
        """Get current configuration (always reload from file for freshness)"""
        return self.load()

    def reload(self) -> VisionConfig:
        """Force reload configuration from file"""
        self._current_config = None
        return self.load()

    def apply_preset(self, preset_name: str) -> Optional[VisionConfig]:
        """Apply a preset configuration"""
        for preset in PRESETS:
            if preset.name == preset_name:
                self.save(preset.config)
                return preset.config
        return None

    def get_presets(self) -> List[dict]:
        """Get all available presets"""
        return [p.to_dict() for p in PRESETS]

    def get_available_models(self) -> dict:
        """Get available model options"""
        return {
            "vlm_types": [
                {"value": t.value, "label": t.name.replace("_", " ")}
                for t in VLMType
            ],
            "text_llm_types": [
                {"value": t.value, "label": t.name.replace("_", " ")}
                for t in TextLLMType
            ],
            "segmentation_models": [
                {"value": s.value, "label": s.name.replace("_", " ")}
                for s in SegmentationModel
            ],
            "modes": [
                {"value": m.value, "label": m.name.replace("_", " ")}
                for m in VisionMode
            ]
        }


# Singleton instance
_config_manager: Optional[VisionConfigManager] = None


def get_vision_config_manager() -> VisionConfigManager:
    """Get singleton config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = VisionConfigManager()
    return _config_manager


def get_current_vision_config() -> VisionConfig:
    """Convenience function to get current config"""
    return get_vision_config_manager().get_current()
