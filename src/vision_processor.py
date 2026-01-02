"""
Vision processing module with multi-mode support.
Supports single VLM, VLM + segmentation, and segmentation + LLM pipelines.
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from openai import OpenAI

from src.config import config
from src.llm_client import get_llm_client
from src.vision_config import (
    VisionConfig,
    VisionMode,
    VLMType,
    TextLLMType,
    SegmentationModel,
    get_current_vision_config,
)


@dataclass
class DetectedObject:
    """Detected object with position information"""
    label: str
    confidence: float
    bbox: Optional[List[float]] = None  # [x1, y1, x2, y2] normalized
    position_description: str = ""  # e.g., "画面中央", "左上"
    size_description: str = ""  # e.g., "大", "中", "小"


@dataclass
class VisionResult:
    """Result of vision analysis"""
    status: str  # "success" or "error"
    image_path: str
    mode_used: str
    visual_info: Dict[str, str]
    detected_objects: List[DetectedObject]
    raw_text: str
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class VisionProcessor:
    """
    Multi-mode vision processor for tourism narration.
    Supports VLM-only, segmentation-only, and combined approaches.
    """

    def __init__(self, config: Optional[VisionConfig] = None):
        """
        Args:
            config: Vision configuration. If None, loads from saved config.
                   注意: Vision対応モデル (llava, llama3.2-vision等) が必要
        """
        self.config = config or get_current_vision_config()
        self._segmentation_model = None
        self._segmentation_processor = None
        # Text LLM for description generation (uses vLLM/Qwen instead of Ollama)
        self._text_llm = None

    def update_config(self, config: VisionConfig):
        """Update configuration"""
        self.config = config
        # Reset cached models if config changed
        self._segmentation_model = None
        self._segmentation_processor = None

    def analyze_image(self, image_path: str) -> dict:
        """
        Analyze image using configured mode.

        Args:
            image_path: Path to image file

        Returns:
            Dictionary with analysis results
        """
        import time
        start_time = time.time()

        try:
            image_file = Path(image_path)
            if not image_file.exists():
                return {
                    "status": "error",
                    "image_path": image_path,
                    "error": f"Image file not found: {image_path}"
                }

            # Route to appropriate processing mode
            if self.config.mode == VisionMode.SINGLE_VLM:
                result = self._analyze_with_vlm(image_file)
            elif self.config.mode == VisionMode.SEGMENTATION_PLUS_LLM:
                result = self._analyze_with_segmentation_llm(image_file)
            elif self.config.mode == VisionMode.VLM_PLUS_SEGMENTATION:
                result = self._analyze_combined(image_file)
            else:
                result = self._analyze_with_vlm(image_file)

            elapsed_ms = (time.time() - start_time) * 1000
            result["processing_time_ms"] = elapsed_ms
            result["mode_used"] = self.config.mode.value

            return result

        except Exception as e:
            return {
                "status": "error",
                "image_path": str(image_path),
                "error": str(e),
                "mode_used": self.config.mode.value
            }

    def _analyze_with_vlm(self, image_file: Path) -> dict:
        """
        Single VLM analysis mode using vLLM + Qwen2.5-VL.

        Uses OpenAI-compatible API to connect to vLLM server.
        The model (Qwen2.5-VL-7B-Instruct) supports multimodal input (text + image).
        """
        # Load image as base64
        with open(image_file, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Determine MIME type from file extension
        ext = str(image_file).lower().split('.')[-1]
        mime_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }.get(ext, "image/jpeg")

        # Get prompt (custom or default)
        prompt = self.config.custom_description_prompt or self._get_default_vlm_prompt()

        # Create OpenAI client for vLLM
        client = OpenAI(
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,
            timeout=config.timeout,
        )

        # Build messages with optional system message for language control
        messages = []

        # Add system message for Japanese-only output
        if self.config.output_language == "ja":
            messages.append({
                "role": "system",
                "content": "あなたは日本語のみで回答するアシスタントです。英語は絶対に使用しないでください。すべての出力を日本語で行ってください。"
            })

        # Add user message with image
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_data}"
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                },
            ],
        })

        # Call VLM with multimodal message format
        response = client.chat.completions.create(
            model=config.openai_model,
            messages=messages,
            max_tokens=self.config.vlm_max_tokens,
            temperature=self.config.vlm_temperature,
        )

        raw_text = response.choices[0].message.content or ""
        visual_info = self._parse_vision_response(raw_text)

        return {
            "status": "success",
            "image_path": str(image_file),
            "visual_info": visual_info,
            "detected_objects": [],
            "raw_text": raw_text
        }

    def _analyze_with_segmentation_llm(self, image_file: Path) -> dict:
        """Segmentation → structured data → LLM for description"""
        # Step 1: Run segmentation
        detected_objects = self._run_segmentation(image_file)

        # Step 2: Convert to structured data
        structured_data = self._objects_to_structured_data(detected_objects)

        # Step 3: Use LLM (vLLM/Qwen) to generate natural description
        visual_info, raw_text = self._generate_description_from_objects(
            structured_data, detected_objects
        )

        return {
            "status": "success",
            "image_path": str(image_file),
            "visual_info": visual_info,
            "detected_objects": [self._object_to_dict(obj) for obj in detected_objects],
            "raw_text": raw_text
        }

    def _analyze_combined(self, image_file: Path) -> dict:
        """Combined VLM + segmentation analysis"""
        # Run both in parallel conceptually (sequential here for simplicity)

        # Step 1: VLM analysis for overall description
        vlm_result = self._analyze_with_vlm(image_file)

        # Step 2: Segmentation for object detection
        detected_objects = self._run_segmentation(image_file)

        # Step 3: Merge results
        visual_info = vlm_result.get("visual_info", {})

        # Add object detection summary
        if detected_objects:
            object_summary = self._summarize_objects(detected_objects)
            visual_info["detected_objects_summary"] = object_summary

        return {
            "status": "success",
            "image_path": str(image_file),
            "visual_info": visual_info,
            "detected_objects": [self._object_to_dict(obj) for obj in detected_objects],
            "raw_text": vlm_result.get("raw_text", "")
        }

    def _run_segmentation(self, image_file: Path) -> List[DetectedObject]:
        """Run segmentation model on image"""
        if self.config.segmentation_model == SegmentationModel.NONE:
            return []

        try:
            if self.config.segmentation_model in [
                SegmentationModel.FLORENCE2_BASE,
                SegmentationModel.FLORENCE2_LARGE
            ]:
                return self._run_florence2(image_file)
            elif self.config.segmentation_model == SegmentationModel.YOLO_V8:
                return self._run_yolo(image_file)
            elif self.config.segmentation_model == SegmentationModel.GROUNDED_SAM2:
                return self._run_grounded_sam2(image_file)
            elif self.config.segmentation_model == SegmentationModel.GROUNDING_DINO:
                return self._run_grounding_dino(image_file)
        except Exception as e:
            print(f"Segmentation error: {e}")
            return []

        return []

    def _run_florence2(self, image_file: Path) -> List[DetectedObject]:
        """Run Florence-2 for object detection"""
        try:
            from transformers import AutoProcessor, AutoModelForCausalLM
            from PIL import Image
            import torch
        except ImportError:
            print("Florence-2 requires: pip install transformers torch pillow")
            return []

        # Load model if not cached
        if self._segmentation_model is None:
            model_name = (
                "microsoft/Florence-2-large"
                if self.config.segmentation_model == SegmentationModel.FLORENCE2_LARGE
                else "microsoft/Florence-2-base"
            )

            device = "cuda" if self.config.use_gpu and torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32

            # Use attn_implementation="eager" to avoid SDPA compatibility issues
            # with newer transformers versions (4.45+)
            self._segmentation_model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=dtype,
                trust_remote_code=True,
                attn_implementation="eager"
            ).to(device)

            self._segmentation_processor = AutoProcessor.from_pretrained(
                model_name,
                trust_remote_code=True
            )

        # Load image
        image = Image.open(image_file).convert("RGB")
        img_width, img_height = image.size

        # Run object detection
        task_prompt = "<OD>"
        inputs = self._segmentation_processor(
            text=task_prompt,
            images=image,
            return_tensors="pt"
        )

        # Move to device and convert dtype to match model
        device = self._segmentation_model.device
        model_dtype = next(self._segmentation_model.parameters()).dtype
        processed_inputs = {}
        for k, v in inputs.items():
            if v is None:
                continue
            if hasattr(v, 'dtype') and hasattr(v, 'to'):
                if v.dtype.is_floating_point:
                    processed_inputs[k] = v.to(device=device, dtype=model_dtype)
                else:
                    processed_inputs[k] = v.to(device)
            else:
                processed_inputs[k] = v
        inputs = processed_inputs

        generated_ids = self._segmentation_model.generate(
            **inputs,
            max_new_tokens=1024,
            num_beams=3,
        )

        generated_text = self._segmentation_processor.batch_decode(
            generated_ids, skip_special_tokens=False
        )[0]

        # Parse Florence-2 output
        result = self._segmentation_processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(img_width, img_height)
        )

        detected_objects = []
        if "<OD>" in result:
            od_result = result["<OD>"]
            labels = od_result.get("labels", [])
            bboxes = od_result.get("bboxes", [])

            for i, (label, bbox) in enumerate(zip(labels, bboxes)):
                if i >= self.config.max_objects:
                    break

                # Normalize bbox
                norm_bbox = [
                    bbox[0] / img_width,
                    bbox[1] / img_height,
                    bbox[2] / img_width,
                    bbox[3] / img_height
                ]

                obj = DetectedObject(
                    label=label,
                    confidence=1.0,  # Florence-2 doesn't provide confidence
                    bbox=norm_bbox,
                    position_description=self._bbox_to_position(norm_bbox),
                    size_description=self._bbox_to_size(norm_bbox)
                )
                detected_objects.append(obj)

        return detected_objects

    def _run_yolo(self, image_file: Path) -> List[DetectedObject]:
        """Run YOLOv8 for object detection"""
        try:
            from ultralytics import YOLO
            from PIL import Image
        except ImportError:
            print("YOLOv8 requires: pip install ultralytics")
            return []

        # Load model (cached after first load)
        if self._segmentation_model is None or not hasattr(self._segmentation_model, 'predict'):
            # Use YOLOv8 medium model for good balance of speed/accuracy
            self._segmentation_model = YOLO('yolov8m.pt')

        # Load image
        image = Image.open(image_file).convert("RGB")
        img_width, img_height = image.size

        # Run detection
        results = self._segmentation_model.predict(
            source=image,
            conf=self.config.segmentation_confidence_threshold,
            verbose=False
        )

        detected_objects = []
        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes

            for i, box in enumerate(boxes):
                if i >= self.config.max_objects:
                    break

                # Get box coordinates (xyxy format)
                xyxy = box.xyxy[0].cpu().numpy()
                confidence = float(box.conf[0].cpu().numpy())
                class_id = int(box.cls[0].cpu().numpy())
                label = result.names[class_id]

                # Normalize bbox
                norm_bbox = [
                    xyxy[0] / img_width,
                    xyxy[1] / img_height,
                    xyxy[2] / img_width,
                    xyxy[3] / img_height
                ]

                obj = DetectedObject(
                    label=label,
                    confidence=confidence,
                    bbox=norm_bbox,
                    position_description=self._bbox_to_position(norm_bbox),
                    size_description=self._bbox_to_size(norm_bbox)
                )
                detected_objects.append(obj)

        return detected_objects

    def _run_grounded_sam2(self, image_file: Path) -> List[DetectedObject]:
        """Run Grounded SAM 2 for detection and segmentation"""
        # Placeholder - requires separate installation
        print("Grounded SAM 2 not yet implemented. Install from: https://github.com/IDEA-Research/Grounded-SAM-2")
        return []

    def _run_grounding_dino(self, image_file: Path) -> List[DetectedObject]:
        """Run Grounding DINO for open-set detection"""
        # Placeholder - requires separate installation
        print("Grounding DINO not yet implemented. Install from: https://github.com/IDEA-Research/GroundingDINO")
        return []

    def _bbox_to_position(self, bbox: List[float]) -> str:
        """Convert normalized bbox to position description"""
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2

        h_pos = "左" if cx < 0.33 else ("右" if cx > 0.66 else "中央")
        v_pos = "上" if cy < 0.33 else ("下" if cy > 0.66 else "")

        if v_pos:
            return f"{h_pos}{v_pos}"
        return f"画面{h_pos}"

    def _bbox_to_size(self, bbox: List[float]) -> str:
        """Convert normalized bbox to size description"""
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        if area > 0.25:
            return "大"
        elif area > 0.05:
            return "中"
        return "小"

    def _object_to_dict(self, obj: DetectedObject) -> dict:
        """Convert DetectedObject to dictionary"""
        return {
            "label": obj.label,
            "confidence": obj.confidence,
            "bbox": obj.bbox,
            "position": obj.position_description,
            "size": obj.size_description
        }

    def _objects_to_structured_data(self, objects: List[DetectedObject]) -> str:
        """Convert detected objects to structured text"""
        if not objects:
            return "検出されたオブジェクトはありません"

        lines = ["【検出オブジェクト】"]
        for obj in objects:
            line = f"- {obj.label}"
            if obj.position_description:
                line += f" ({obj.position_description}"
                if obj.size_description:
                    line += f", {obj.size_description}"
                line += ")"
            lines.append(line)

        return "\n".join(lines)

    def _summarize_objects(self, objects: List[DetectedObject]) -> str:
        """Create summary of detected objects"""
        if not objects:
            return ""

        # Group by position
        position_groups = {}
        for obj in objects:
            pos = obj.position_description or "不明"
            if pos not in position_groups:
                position_groups[pos] = []
            position_groups[pos].append(obj.label)

        parts = []
        for pos, labels in position_groups.items():
            unique_labels = list(set(labels))
            parts.append(f"{pos}に{', '.join(unique_labels[:3])}")

        return "。".join(parts)

    def _create_visual_info_from_objects(
        self, objects: List[DetectedObject]
    ) -> Dict[str, str]:
        """Create visual_info dict from detected objects (without LLM)"""
        if not objects:
            return {"main_subjects": "検出なし"}

        # Find largest object as main subject
        main_obj = max(objects, key=lambda o: self._size_to_num(o.size_description))

        return {
            "main_subjects": f"{main_obj.label}（{main_obj.position_description}）",
            "environment": self._summarize_objects(objects),
            "people_activity": "",
            "colors_lighting": "",
            "perspective": "",
            "notable_details": ""
        }

    def _size_to_num(self, size: str) -> int:
        """Convert size description to number for comparison"""
        return {"大": 3, "中": 2, "小": 1}.get(size, 0)

    def _generate_description_from_objects(
        self,
        structured_data: str,
        objects: List[DetectedObject]
    ) -> tuple[Dict[str, str], str]:
        """Generate natural description from detected objects using text LLM.

        This method is used in SEGMENTATION_PLUS_LLM mode where:
        1. Florence-2 or similar model detects objects with positions
        2. Text LLM (vLLM/Qwen) generates natural descriptions from the structured data

        Note: This method no longer uses Ollama. It uses LlmClient which connects
        to vLLM server, eliminating VRAM conflicts with Ollama.
        """
        lang = "日本語" if self.config.output_language == "ja" else "English"

        system_prompt = "あなたは観光地ナレーションの専門家です。与えられた情報から簡潔な説明を生成してください。"

        user_prompt = f"""以下の画像解析結果を元に、観光地ナレーション向けの視覚情報を{lang}で生成してください。

{structured_data}

以下の形式で出力してください：

【メイン被写体】
（最も重要な被写体について、位置情報を含めて説明）

【環境・背景】
（周囲の状況について）

【人物・活動】
（人がいる場合はその様子）

【特筆すべき詳細】
（ナレーションで言及すると面白い点）

各項目について、簡潔かつ具体的に記述してください。"""

        try:
            # Use LlmClient (vLLM/Qwen) instead of Ollama to avoid VRAM conflicts
            if self._text_llm is None:
                self._text_llm = get_llm_client()

            raw_text = self._text_llm.call(
                system=system_prompt,
                user=user_prompt,
                temperature=self.config.llm_temperature,
                max_tokens=self.config.llm_max_tokens,
            )
            visual_info = self._parse_vision_response(raw_text)
            return visual_info, raw_text
        except Exception as e:
            # Fallback: Return minimal info without LLM
            print(f"Warning: LLM text generation failed: {e}")
            return self._create_visual_info_from_objects(objects), ""

    def _get_default_vlm_prompt(self) -> str:
        """Get default VLM analysis prompt"""
        if self.config.output_language == "ja":
            return """【重要】回答は必ず日本語のみで行ってください。英語は使用しないでください。

この画像を詳細に分析してください。以下の観点から、観光地ナレーション向けの視覚情報を日本語で提供してください：

【メイン被写体】
- 画像の中心的な被写体は何か？
- その特徴、大きさ、位置は？

【環境・背景】
- 周囲の環境はどのような状態か？
- 背景にある重要な要素は？

【人物・活動】
- 人物がいるか？いる場合の状態は？
- 何かアクティビティが起きているか？

【色調・照明】
- 全体的な色合いは？
- 光の質（朝日、逆光、曇りなど）は？

【構図・遠近感】
- 画像の構成はどうか？
- 遠近感（前景、中景、背景）の配分は？

【特筆すべき詳細】
- 観光地ナレーション時に言及すると面白い、珍しい要素は？

各項目について、簡潔かつ具体的に日本語で記述してください。英語での回答は禁止です。"""
        else:
            return """Analyze this image in detail. Provide visual information for tourism narration from the following perspectives:

【Main Subject】
- What is the central subject?
- Features, size, position?

【Environment/Background】
- Surrounding environment condition?
- Important background elements?

【People/Activity】
- Are there people? Their state?
- Any activities happening?

【Color/Lighting】
- Overall color tone?
- Quality of light (morning sun, backlit, cloudy, etc.)?

【Composition/Perspective】
- Image composition?
- Foreground, midground, background distribution?

【Notable Details】
- Interesting or unusual elements worth mentioning?

Be concise and specific for each item."""

    def _parse_vision_response(self, text: str) -> dict:
        """Parse VLM response into structured sections"""
        sections = {
            "main_subjects": self._extract_section(text, "【メイン被写体】"),
            "environment": self._extract_section(text, "【環境・背景】"),
            "people_activity": self._extract_section(text, "【人物・活動】"),
            "colors_lighting": self._extract_section(text, "【色調・照明】"),
            "perspective": self._extract_section(text, "【構図・遠近感】"),
            "notable_details": self._extract_section(text, "【特筆すべき詳細】")
        }
        return sections

    @staticmethod
    def _extract_section(text: str, header: str) -> str:
        """Extract a section from text by header"""
        if header not in text:
            return ""

        start = text.find(header) + len(header)
        next_header_pos = len(text)
        for next_header in ["【", "\n\n"]:
            pos = text.find(next_header, start)
            if pos != -1 and pos < next_header_pos:
                next_header_pos = pos

        section = text[start:next_header_pos].strip()
        return section

    def format_for_character(self, visual_info: dict) -> str:
        """Format visual info for character prompt"""
        output = "【映像情報】\n"

        if visual_info.get("main_subjects"):
            output += f"メイン：{visual_info['main_subjects']}\n"

        if visual_info.get("environment"):
            output += f"環境：{visual_info['environment']}\n"

        if visual_info.get("people_activity"):
            output += f"人物・活動：{visual_info['people_activity']}\n"

        if visual_info.get("colors_lighting"):
            output += f"色調：{visual_info['colors_lighting']}\n"

        if visual_info.get("perspective"):
            output += f"構図：{visual_info['perspective']}\n"

        if visual_info.get("notable_details"):
            output += f"注目点：{visual_info['notable_details']}\n"

        if visual_info.get("detected_objects_summary"):
            output += f"検出物：{visual_info['detected_objects_summary']}\n"

        return output


# Convenience function for backward compatibility
def get_vision_processor(config: Optional[VisionConfig] = None) -> VisionProcessor:
    """Get a VisionProcessor instance"""
    return VisionProcessor(config)
