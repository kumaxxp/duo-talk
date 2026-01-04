#!/usr/bin/env python3
"""
Florence-2 Eager Attention Mode Test
flash-attn無しでFlorence-2を動作させるテスト（モンキーパッチ版）
"""
import sys
import os
import time
import types
import importlib.util

# flash_attnのモックを作成（インポートエラー回避）
def create_mock_module(name):
    """適切な__spec__を持つモックモジュールを作成"""
    mock = types.ModuleType(name)
    mock.__spec__ = importlib.util.spec_from_loader(name, loader=None)
    mock.__file__ = f"<mock:{name}>"
    mock.__path__ = []
    return mock

# flash_attnモジュール群をモック
flash_attn = create_mock_module('flash_attn')
flash_attn.__version__ = "2.6.3"  # バージョンを偽装
flash_attn.flash_attn_func = lambda *args, **kwargs: None
flash_attn.flash_attn_varlen_func = lambda *args, **kwargs: None
sys.modules['flash_attn'] = flash_attn

# サブモジュール
bert_padding = create_mock_module('flash_attn.bert_padding')
bert_padding.pad_input = lambda *args, **kwargs: None
bert_padding.unpad_input = lambda *args, **kwargs: None
bert_padding.index_first_axis = lambda *args, **kwargs: None
sys.modules['flash_attn.bert_padding'] = bert_padding

flash_attn_interface = create_mock_module('flash_attn.flash_attn_interface')
flash_attn_interface.flash_attn_func = lambda *args, **kwargs: None
flash_attn_interface.flash_attn_varlen_func = lambda *args, **kwargs: None
sys.modules['flash_attn.flash_attn_interface'] = flash_attn_interface

import torch
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_florence2_eager():
    """Florence-2をeager attentionモードでテスト"""
    print("=" * 60)
    print("Florence-2 Eager Attention Test (with mock)")
    print("=" * 60)

    # 環境情報
    print(f"\nEnvironment:")
    print(f"   PyTorch: {torch.__version__}")
    print(f"   CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"   GPU: {torch.cuda.get_device_name(0)}")
        print(f"   VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

    # Florence-2ロード
    print(f"\nLoading Florence-2 (eager attention)...")
    start_time = time.time()

    try:
        from transformers import AutoProcessor, AutoModelForCausalLM

        model_id = "microsoft/Florence-2-base"

        processor = AutoProcessor.from_pretrained(
            model_id,
            trust_remote_code=True
        )

        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            trust_remote_code=True,
            torch_dtype=torch.float16,
            attn_implementation="eager"  # flash-attn不要
        ).to("cuda" if torch.cuda.is_available() else "cpu")

        load_time = time.time() - start_time
        print(f"   Model loaded in {load_time:.1f}s")

        # VRAM使用量
        if torch.cuda.is_available():
            vram_used = torch.cuda.memory_allocated() / 1024**3
            print(f"   VRAM used: {vram_used:.2f} GB")

    except Exception as e:
        print(f"   Load error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # テスト画像で推論
    print(f"\nRunning inference test...")
    try:
        from PIL import Image
        import requests

        # テスト画像（URLから取得）
        url = "https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/transformers/tasks/car.jpg"
        image = Image.open(requests.get(url, stream=True).raw)

        # Object Detectionタスク
        task_prompt = "<OD>"

        inputs = processor(text=task_prompt, images=image, return_tensors="pt")
        # dtypeをモデルに合わせる（float16）
        inputs = {
            k: v.to(model.device, dtype=torch.float16) if v.dtype == torch.float32 else v.to(model.device)
            for k, v in inputs.items()
        }

        start_time = time.time()
        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=1024,
                num_beams=3,
            )
        inference_time = time.time() - start_time

        # 結果デコード
        generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(image.width, image.height)
        )

        print(f"   Inference completed in {inference_time*1000:.0f}ms")
        print(f"   Result: {parsed}")

        return True

    except Exception as e:
        print(f"   Inference error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    success = test_florence2_eager()

    print("\n" + "=" * 60)
    if success:
        print("Florence-2 works without flash-attn!")
        print("   Use the mock pattern shown in this script")
    else:
        print("Florence-2 test failed")
        print("   Consider using YOLOv8 as alternative")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
