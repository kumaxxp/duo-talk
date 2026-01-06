"""
Florence-2 物体検出モジュール

Microsoft Florence-2を使った物体検出・セグメンテーション。
オンデマンドでモデルをロード/アンロードしてVRAMを節約。

使用例:
    detector = Florence2Detector()
    detector.load()  # モデルロード
    result = detector.detect(image_path)
    detector.unload()  # VRAM解放
"""
import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field
from datetime import datetime
import threading
from types import ModuleType

import torch
from PIL import Image


def _setup_flash_attn_dummy() -> bool:
    """
    flash_attn ダミーモジュールを作成してインポートエラーを回避

    Florence-2のモデルコードは flash_attn をインポートしようとするが、
    attn_implementation が eager/sdpa の場合は実際には使用しない

    Returns:
        ダミーが設定されたかどうか
    """
    from importlib.machinery import ModuleSpec

    if "flash_attn" not in sys.modules:
        # ダミーモジュール作成
        flash_attn = ModuleType("flash_attn")
        flash_attn.__version__ = "0.0.0"
        flash_attn.__spec__ = ModuleSpec("flash_attn", None)
        flash_attn.__file__ = "<dummy>"
        flash_attn.__path__ = []

        # flash_attn.flash_attn_func のダミー
        flash_attn_func = ModuleType("flash_attn.flash_attn_func")
        flash_attn_func.flash_attn_func = lambda *args, **kwargs: None
        flash_attn_func.__spec__ = ModuleSpec("flash_attn.flash_attn_func", None)

        # flash_attn.bert_padding のダミー
        bert_padding = ModuleType("flash_attn.bert_padding")
        bert_padding.index_first_axis = lambda *args, **kwargs: None
        bert_padding.pad_input = lambda *args, **kwargs: None
        bert_padding.unpad_input = lambda *args, **kwargs: None
        bert_padding.__spec__ = ModuleSpec("flash_attn.bert_padding", None)

        sys.modules["flash_attn"] = flash_attn
        sys.modules["flash_attn.flash_attn_func"] = flash_attn_func
        sys.modules["flash_attn.bert_padding"] = bert_padding

        return True
    return False


# モジュール読み込み時にダミーを設定
_setup_flash_attn_dummy()

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    """検出結果"""
    objects: List[Dict[str, Any]] = field(default_factory=list)
    caption: str = ""
    raw_output: Dict[str, Any] = field(default_factory=dict)
    processing_time_ms: float = 0.0
    model_loaded: bool = False
    error: Optional[str] = None


@dataclass
class Florence2Config:
    """Florence-2設定"""
    model_name: str = "microsoft/Florence-2-large"
    device: str = "cuda"
    torch_dtype: torch.dtype = torch.float16
    trust_remote_code: bool = True
    attn_implementation: str = "sdpa"  # "sdpa", "eager", or "flash_attention_2"
    max_objects: int = 20
    confidence_threshold: float = 0.3
    cache_dir: Optional[str] = None


class Florence2Detector:
    """
    Florence-2 物体検出器

    オンデマンドロード対応でVRAMを効率的に使用。
    スレッドセーフなロード/アンロード機能。
    """

    _instance: Optional['Florence2Detector'] = None
    _lock = threading.Lock()

    def __new__(cls, config: Optional[Florence2Config] = None):
        """シングルトンパターン"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[Florence2Config] = None):
        if self._initialized:
            return

        self.config = config or Florence2Config()
        self.model = None
        self.processor = None
        self._loaded = False
        self._load_lock = threading.Lock()
        self._active_backend: str = ""  # 実際に使用中のバックエンド
        self._initialized = True

        logger.info(f"Florence2Detector initialized (model: {self.config.model_name})")

    @property
    def is_loaded(self) -> bool:
        """モデルがロード済みかどうか"""
        return self._loaded and self.model is not None

    @property
    def active_backend(self) -> str:
        """現在使用中のattentionバックエンド"""
        return self._active_backend

    def load(self, force: bool = False) -> bool:
        """
        モデルをロード

        Args:
            force: 既にロード済みでも再ロードするか

        Returns:
            ロード成功したかどうか
        """
        with self._load_lock:
            if self._loaded and not force:
                logger.debug("Florence-2 already loaded")
                return True

            try:
                logger.info("Loading Florence-2 model...")
                start_time = datetime.now()

                from transformers import AutoProcessor, AutoModelForCausalLM

                # プロセッサのロード
                self.processor = AutoProcessor.from_pretrained(
                    self.config.model_name,
                    trust_remote_code=self.config.trust_remote_code,
                    cache_dir=self.config.cache_dir
                )

                # attn_implementation の優先順を取得
                attn_backends = self._get_attn_backends()

                model_kwargs: Dict[str, Any] = {
                    "trust_remote_code": self.config.trust_remote_code,
                    "torch_dtype": self.config.torch_dtype,
                    "cache_dir": self.config.cache_dir,
                }

                # 優先順でバックエンドを試行
                last_error = None
                for backend in attn_backends:
                    try:
                        logger.info(f"Trying attn_implementation: {backend}")
                        model_kwargs["attn_implementation"] = backend

                        self.model = AutoModelForCausalLM.from_pretrained(
                            self.config.model_name,
                            **model_kwargs
                        ).to(self.config.device)

                        self.model.eval()
                        self._loaded = True
                        self._active_backend = backend

                        elapsed = (datetime.now() - start_time).total_seconds()
                        logger.info(f"Florence-2 loaded with '{backend}' in {elapsed:.1f}s")

                        # VRAM使用量ログ
                        if torch.cuda.is_available():
                            vram_gb = torch.cuda.memory_allocated() / 1024**3
                            logger.info(f"VRAM usage: {vram_gb:.2f} GB")

                        return True

                    except Exception as e:
                        last_error = e
                        logger.warning(f"Failed with '{backend}': {e}")
                        # モデルが部分的にロードされていたらクリーンアップ
                        if self.model is not None:
                            del self.model
                            self.model = None
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                        continue

                # 全バックエンド失敗
                raise RuntimeError(f"All attention backends failed. Last error: {last_error}")

            except Exception as e:
                logger.error(f"Failed to load Florence-2: {e}")
                self.model = None
                self.processor = None
                self._loaded = False
                self._active_backend = ""
                return False

    def _get_attn_backends(self) -> List[str]:
        """
        使用するattentionバックエンドの優先順リストを返す

        Florence-2 がサポートするバックエンド: sdpa, eager, flash_attention_2
        ※ flash_attention_2 は実際のflash_attnパッケージが必要（ダミーでは不可）

        Returns:
            バックエンド名のリスト（優先順）
        """
        # 設定で指定されたバックエンドを最優先
        backends = [self.config.attn_implementation]

        # フォールバック順序を追加（重複除去）
        # flash_attention_2 はダミーモジュールでは動作しないので含めない
        fallback_order = ["sdpa", "eager"]
        for backend in fallback_order:
            if backend not in backends:
                backends.append(backend)

        logger.debug(f"Attention backends priority: {backends}")
        return backends

    def unload(self) -> bool:
        """
        モデルをアンロードしてVRAMを解放

        Returns:
            アンロード成功したかどうか
        """
        with self._load_lock:
            if not self._loaded:
                return True

            try:
                logger.info("Unloading Florence-2 model...")

                del self.model
                del self.processor
                self.model = None
                self.processor = None
                self._loaded = False
                self._active_backend = ""

                # VRAM解放
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()

                import gc
                gc.collect()

                logger.info("Florence-2 unloaded")
                return True

            except Exception as e:
                logger.error(f"Failed to unload Florence-2: {e}")
                return False

    def detect(
        self,
        image: Union[str, Path, Image.Image],
        task: str = "<OD>",
        text_input: str = ""
    ) -> DetectionResult:
        """
        物体検出を実行

        Args:
            image: 画像パスまたはPIL Image
            task: Florence-2タスク
                - "<OD>": Object Detection
                - "<DENSE_REGION_CAPTION>": 詳細キャプション
                - "<CAPTION>": 簡潔なキャプション
                - "<DETAILED_CAPTION>": 詳細キャプション
                - "<MORE_DETAILED_CAPTION>": より詳細なキャプション
                - "<REGION_PROPOSAL>": 領域提案
            text_input: タスクに応じた追加テキスト入力

        Returns:
            DetectionResult
        """
        result = DetectionResult()
        start_time = datetime.now()

        # 自動ロード
        if not self.is_loaded:
            if not self.load():
                result.error = "Failed to load model"
                return result

        try:
            # 画像の読み込み
            if isinstance(image, (str, Path)):
                image = Image.open(image).convert("RGB")
            elif not isinstance(image, Image.Image):
                raise ValueError(f"Unsupported image type: {type(image)}")

            # プロンプト作成
            prompt = task + text_input

            # 推論
            inputs = self.processor(
                text=prompt,
                images=image,
                return_tensors="pt"
            ).to(self.config.device, self.config.torch_dtype)

            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=1024,
                    num_beams=3,
                    do_sample=False,
                )

            # デコード
            generated_text = self.processor.batch_decode(
                generated_ids,
                skip_special_tokens=False
            )[0]

            # 後処理
            parsed = self.processor.post_process_generation(
                generated_text,
                task=task,
                image_size=(image.width, image.height)
            )

            result.raw_output = parsed
            result.model_loaded = True

            # タスクに応じた結果の整形
            if task == "<OD>":
                result.objects = self._parse_od_result(parsed, image.size)
            elif task in ["<CAPTION>", "<DETAILED_CAPTION>", "<MORE_DETAILED_CAPTION>"]:
                result.caption = parsed.get(task, "")
            elif task == "<DENSE_REGION_CAPTION>":
                result.objects = self._parse_dense_caption(parsed, image.size)

        except Exception as e:
            logger.error(f"Detection failed: {e}")
            result.error = str(e)

        result.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        return result

    def _parse_od_result(
        self,
        parsed: Dict[str, Any],
        image_size: tuple
    ) -> List[Dict[str, Any]]:
        """Object Detection結果をパース"""
        objects = []

        od_result = parsed.get("<OD>", {})
        bboxes = od_result.get("bboxes", [])
        labels = od_result.get("labels", [])

        width, height = image_size

        for i, (bbox, label) in enumerate(zip(bboxes, labels)):
            if i >= self.config.max_objects:
                break

            # 正規化座標に変換
            x1, y1, x2, y2 = bbox
            obj = {
                "id": i,
                "label": label,
                "bbox": {
                    "x1": x1 / width,
                    "y1": y1 / height,
                    "x2": x2 / width,
                    "y2": y2 / height,
                },
                "bbox_pixel": {
                    "x1": int(x1),
                    "y1": int(y1),
                    "x2": int(x2),
                    "y2": int(y2),
                },
                "center": {
                    "x": (x1 + x2) / 2 / width,
                    "y": (y1 + y2) / 2 / height,
                },
                "size": {
                    "width": (x2 - x1) / width,
                    "height": (y2 - y1) / height,
                },
                "position": self._get_position_label((x1 + x2) / 2 / width),
            }
            objects.append(obj)

        return objects

    def _parse_dense_caption(
        self,
        parsed: Dict[str, Any],
        image_size: tuple
    ) -> List[Dict[str, Any]]:
        """Dense Region Caption結果をパース"""
        objects = []

        result = parsed.get("<DENSE_REGION_CAPTION>", {})
        bboxes = result.get("bboxes", [])
        labels = result.get("labels", [])

        width, height = image_size

        for i, (bbox, label) in enumerate(zip(bboxes, labels)):
            if i >= self.config.max_objects:
                break

            x1, y1, x2, y2 = bbox
            obj = {
                "id": i,
                "label": label,
                "bbox_pixel": {
                    "x1": int(x1),
                    "y1": int(y1),
                    "x2": int(x2),
                    "y2": int(y2),
                },
                "position": self._get_position_label((x1 + x2) / 2 / width),
            }
            objects.append(obj)

        return objects

    def _get_position_label(self, x_center: float) -> str:
        """X座標から位置ラベルを取得"""
        if x_center < 0.33:
            return "left"
        elif x_center > 0.67:
            return "right"
        else:
            return "center"

    def _estimate_distance(self, size: Dict[str, float]) -> str:
        """サイズから距離を推定（簡易版）"""
        area = size["width"] * size["height"]
        if area > 0.1:
            return "near"  # 30cm以内
        elif area > 0.03:
            return "medium"  # 30-100cm
        else:
            return "far"  # 100cm以上

    def detect_for_driving(
        self,
        image: Union[str, Path, Image.Image]
    ) -> Dict[str, Any]:
        """
        自動運転向けの検出（duo-talk用）

        物体検出 + キャプションを組み合わせて
        scene_facts形式で返す

        Args:
            image: 画像

        Returns:
            scene_facts形式の辞書
        """
        scene_facts: Dict[str, Any] = {
            "objects": [],
            "obstacles": [],
            "lane_info": "",
            "road_condition": "",
            "caption": "",
            "timestamp": datetime.now().isoformat(),
        }

        # 物体検出
        od_result = self.detect(image, task="<OD>")
        if od_result.error:
            scene_facts["error"] = od_result.error
            return scene_facts

        # 検出物体の分類
        for obj in od_result.objects:
            label_lower = obj["label"].lower()

            # 障害物カテゴリ
            obstacle_keywords = ["cone", "barrier", "person", "car", "vehicle", "box"]
            if any(kw in label_lower for kw in obstacle_keywords):
                scene_facts["obstacles"].append({
                    "type": obj["label"],
                    "position": obj["position"],
                    "distance_estimate": self._estimate_distance(obj["size"]),
                })

            scene_facts["objects"].append({
                "label": obj["label"],
                "position": obj["position"],
            })

        # キャプション取得
        caption_result = self.detect(image, task="<CAPTION>")
        if not caption_result.error:
            scene_facts["caption"] = caption_result.caption

        # 処理時間
        scene_facts["processing_time_ms"] = (
            od_result.processing_time_ms +
            (caption_result.processing_time_ms if not caption_result.error else 0)
        )

        return scene_facts


# モジュールレベルのヘルパー関数
_detector: Optional[Florence2Detector] = None


def get_florence2_detector(config: Optional[Florence2Config] = None) -> Florence2Detector:
    """Florence2Detectorのシングルトンインスタンスを取得"""
    global _detector
    if _detector is None:
        _detector = Florence2Detector(config)
    return _detector


def detect_objects(
    image: Union[str, Path, Image.Image],
    auto_unload: bool = False
) -> DetectionResult:
    """
    簡易物体検出関数

    Args:
        image: 画像
        auto_unload: 検出後にモデルをアンロードするか

    Returns:
        DetectionResult
    """
    detector = get_florence2_detector()
    result = detector.detect(image)

    if auto_unload:
        detector.unload()

    return result


def detect_for_driving(
    image: Union[str, Path, Image.Image],
    auto_unload: bool = False
) -> Dict[str, Any]:
    """
    自動運転向け検出関数

    Args:
        image: 画像
        auto_unload: 検出後にモデルをアンロードするか

    Returns:
        scene_facts形式の辞書
    """
    detector = get_florence2_detector()
    result = detector.detect_for_driving(image)

    if auto_unload:
        detector.unload()

    return result
