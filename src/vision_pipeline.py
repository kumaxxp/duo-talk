"""
Vision Pipeline

VLM + Florence-2 を組み合わせた画像解析パイプライン。
duo-talk の scene_facts 生成に使用。
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import base64
import io
import re
import json

from PIL import Image

logger = logging.getLogger(__name__)


class VisionMode(Enum):
    """処理モード"""
    VLM_ONLY = "vlm_only"                    # VLMのみ（高速）
    FLORENCE_ONLY = "florence_only"          # Florence-2のみ（物体検出のみ）
    VLM_WITH_FLORENCE = "vlm_with_florence"  # VLM + Florence-2（詳細）
    FLORENCE_THEN_LLM = "florence_then_llm"  # Florence→LLM（VLM非対応モデル用）


@dataclass
class VisionPipelineConfig:
    """パイプライン設定"""
    mode: VisionMode = VisionMode.VLM_ONLY
    florence_enabled: bool = True
    florence_auto_unload: bool = True  # 使用後にFlorence-2をアンロード
    vlm_temperature: float = 0.3
    vlm_max_tokens: int = 512
    output_language: str = "ja"


class VisionPipeline:
    """
    Vision Pipeline

    画像から scene_facts を生成するパイプライン。
    モードに応じてVLM、Florence-2、またはその組み合わせを使用。
    """

    def __init__(self, config: Optional[VisionPipelineConfig] = None):
        self.config = config or VisionPipelineConfig()
        self._florence_detector = None

    @property
    def florence_detector(self):
        """Florence-2検出器（遅延ロード）"""
        if self._florence_detector is None and self.config.florence_enabled:
            from src.florence2_detector import get_florence2_detector
            self._florence_detector = get_florence2_detector()
        return self._florence_detector

    def process(
        self,
        image: Union[str, Path, Image.Image, bytes],
        mode: Optional[VisionMode] = None,
        additional_context: str = ""
    ) -> Dict[str, Any]:
        """
        画像を処理してscene_factsを生成

        Args:
            image: 画像（パス、PIL Image、またはバイト列）
            mode: 処理モード（Noneの場合は設定値を使用）
            additional_context: 追加コンテキスト（プロンプトに追加）

        Returns:
            scene_facts形式の辞書
        """
        mode = mode or self.config.mode
        start_time = datetime.now()

        scene_facts: Dict[str, Any] = {
            "mode": mode.value,
            "timestamp": start_time.isoformat(),
            "objects": [],
            "obstacles": [],
            "road_info": {},
            "description": "",
            "error": None,
        }

        try:
            # 画像の正規化
            pil_image = self._normalize_image(image)

            if mode == VisionMode.VLM_ONLY:
                scene_facts = self._process_vlm_only(pil_image, additional_context)

            elif mode == VisionMode.FLORENCE_ONLY:
                scene_facts = self._process_florence_only(pil_image)

            elif mode == VisionMode.VLM_WITH_FLORENCE:
                scene_facts = self._process_vlm_with_florence(pil_image, additional_context)

            elif mode == VisionMode.FLORENCE_THEN_LLM:
                scene_facts = self._process_florence_then_llm(pil_image, additional_context)

        except Exception as e:
            logger.error(f"Vision pipeline error: {e}")
            scene_facts["error"] = str(e)

        scene_facts["processing_time_ms"] = (
            datetime.now() - start_time
        ).total_seconds() * 1000
        scene_facts["mode"] = mode.value

        return scene_facts

    def _normalize_image(
        self,
        image: Union[str, Path, Image.Image, bytes]
    ) -> Image.Image:
        """画像をPIL Imageに正規化"""
        if isinstance(image, Image.Image):
            return image.convert("RGB")
        elif isinstance(image, bytes):
            return Image.open(io.BytesIO(image)).convert("RGB")
        elif isinstance(image, (str, Path)):
            return Image.open(image).convert("RGB")
        else:
            raise ValueError(f"Unsupported image type: {type(image)}")

    def _image_to_base64(self, image: Image.Image) -> str:
        """PIL ImageをBase64に変換"""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _process_vlm_only(
        self,
        image: Image.Image,
        additional_context: str
    ) -> Dict[str, Any]:
        """VLMのみで処理"""
        from src.llm_provider import get_llm_provider

        provider = get_llm_provider()
        client = provider.get_client()
        model_name = provider.get_model_name()

        # プロンプト作成
        prompt = self._build_vlm_prompt(additional_context)

        # Base64エンコード
        image_b64 = self._image_to_base64(image)

        # VLM呼び出し
        response = client.chat.completions.create(
            model=model_name,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{image_b64}"
                    }}
                ]
            }],
            max_tokens=self.config.vlm_max_tokens,
            temperature=self.config.vlm_temperature,
        )

        vlm_response = response.choices[0].message.content or ""

        # VLM応答をscene_factsに変換
        return self._parse_vlm_response(vlm_response)

    def _process_florence_only(self, image: Image.Image) -> Dict[str, Any]:
        """Florence-2のみで処理"""
        if not self.florence_detector:
            return {"error": "Florence-2 not enabled"}

        result = self.florence_detector.detect_for_driving(image)

        if self.config.florence_auto_unload:
            self.florence_detector.unload()

        return result

    def _process_vlm_with_florence(
        self,
        image: Image.Image,
        additional_context: str
    ) -> Dict[str, Any]:
        """VLM + Florence-2で処理"""
        # まずFlorence-2で物体検出
        florence_result: Dict[str, Any] = {}
        if self.florence_detector:
            florence_result = self.florence_detector.detect_for_driving(image)

        # Florence結果をコンテキストに追加
        florence_context = self._format_florence_for_vlm(florence_result)
        full_context = f"{additional_context}\n\n{florence_context}".strip()

        # VLMで処理
        vlm_result = self._process_vlm_only(image, full_context)

        # 結果をマージ
        vlm_result["florence_objects"] = florence_result.get("objects", [])
        vlm_result["florence_obstacles"] = florence_result.get("obstacles", [])

        if self.config.florence_auto_unload and self.florence_detector:
            self.florence_detector.unload()

        return vlm_result

    def _process_florence_then_llm(
        self,
        image: Image.Image,
        additional_context: str
    ) -> Dict[str, Any]:
        """Florence-2 → LLM（VLM非対応モデル用）"""
        # Florence-2で物体検出
        if not self.florence_detector:
            return {"error": "Florence-2 not enabled"}

        florence_result = self.florence_detector.detect_for_driving(image)

        # Florence結果をテキスト化
        florence_text = self._format_florence_for_llm(florence_result)

        # LLMで説明生成（画像なし）
        from src.llm_provider import get_llm_provider

        provider = get_llm_provider()
        client = provider.get_client()
        model_name = provider.get_model_name()

        prompt = f"""以下の物体検出結果から、自動運転ロボットの走行状況を説明してください。

{florence_text}

{additional_context}

簡潔に、走行に重要な情報を優先して説明してください。"""

        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.config.vlm_max_tokens,
            temperature=self.config.vlm_temperature,
        )

        llm_response = response.choices[0].message.content or ""

        # 結果を統合
        result = florence_result.copy()
        result["description"] = llm_response

        if self.config.florence_auto_unload:
            self.florence_detector.unload()

        return result

    def _build_vlm_prompt(self, additional_context: str) -> str:
        """VLM用プロンプトを構築"""
        base_prompt = """この画像は自動運転ロボット（JetRacer）のカメラ映像です。
以下の情報を簡潔に報告してください：

1. 路面状態（road_condition）: 直進/カーブ/交差点など
2. 障害物（obstacles）: コーン、物体、人などの位置と距離感
3. 走行可能領域（drivable_area）: 左/中央/右のどこが空いているか
4. 注意点（warnings）: 走行上の注意事項

JSON形式で回答してください：
```json
{
  "road_condition": "...",
  "obstacles": [{"type": "...", "position": "left/center/right", "distance": "near/medium/far"}],
  "drivable_area": "...",
  "warnings": ["..."]
}
```"""

        if additional_context:
            base_prompt += f"\n\n追加情報:\n{additional_context}"

        return base_prompt

    def _format_florence_for_vlm(self, florence_result: Dict[str, Any]) -> str:
        """Florence結果をVLMコンテキスト用にフォーマット"""
        if not florence_result or florence_result.get("error"):
            return ""

        lines = ["[物体検出結果]"]

        for obj in florence_result.get("obstacles", []):
            lines.append(f"- {obj['type']}: {obj['position']}側, 距離{obj.get('distance_estimate', '不明')}")

        for obj in florence_result.get("objects", [])[:5]:  # 最大5件
            lines.append(f"- {obj['label']}: {obj['position']}側")

        return "\n".join(lines)

    def _format_florence_for_llm(self, florence_result: Dict[str, Any]) -> str:
        """Florence結果をLLM用にフォーマット"""
        if not florence_result or florence_result.get("error"):
            return "物体検出結果: なし"

        lines = ["【検出された物体】"]

        for obj in florence_result.get("obstacles", []):
            lines.append(f"・障害物: {obj['type']} - 位置: {obj['position']}, 距離: {obj.get('distance_estimate', '不明')}")

        for obj in florence_result.get("objects", []):
            lines.append(f"・{obj['label']} - 位置: {obj['position']}")

        if florence_result.get("caption"):
            lines.append(f"\n【シーン概要】\n{florence_result['caption']}")

        return "\n".join(lines)

    def _parse_vlm_response(self, response: str) -> Dict[str, Any]:
        """VLM応答をscene_factsに変換"""
        scene_facts: Dict[str, Any] = {
            "objects": [],
            "obstacles": [],
            "road_info": {},
            "description": response,
        }

        # JSON部分を抽出
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                scene_facts["road_info"] = {
                    "condition": parsed.get("road_condition", ""),
                    "drivable_area": parsed.get("drivable_area", ""),
                }
                scene_facts["obstacles"] = parsed.get("obstacles", [])
                scene_facts["warnings"] = parsed.get("warnings", [])
            except json.JSONDecodeError:
                pass

        return scene_facts


# モジュールレベルのインスタンス
_pipeline: Optional[VisionPipeline] = None


def get_vision_pipeline(config: Optional[VisionPipelineConfig] = None) -> VisionPipeline:
    """VisionPipelineのインスタンスを取得"""
    global _pipeline
    if _pipeline is None:
        _pipeline = VisionPipeline(config)
    return _pipeline


def process_image(
    image: Union[str, Path, Image.Image, bytes],
    mode: Optional[VisionMode] = None
) -> Dict[str, Any]:
    """
    簡易画像処理関数

    Args:
        image: 画像
        mode: 処理モード

    Returns:
        scene_facts
    """
    pipeline = get_vision_pipeline()
    return pipeline.process(image, mode)
