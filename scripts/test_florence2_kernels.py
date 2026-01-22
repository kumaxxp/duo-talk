"""
Florence-2 Kernels動作確認スクリプト

kernels-community/flash-attn2 → sdpa → eager の優先順でテスト
VRAM使用量、推論速度を測定
"""
import sys
from types import ModuleType


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


# モジュール読み込み時にダミーを設定（transformersインポート前に必要）
_setup_flash_attn_dummy()

import torch
from PIL import Image
import time
from typing import Dict, List, Any


def test_florence_kernels() -> Dict[str, Any]:
    """Florence-2 Kernels動作確認"""

    # transformers のインポート
    try:
        from transformers import AutoProcessor, AutoModelForCausalLM
    except ImportError as e:
        print(f"Error: transformers not installed: {e}")
        return {"error": str(e)}

    # 試行順序: flash_attention_2 → SDPA → eager
    backends = [
        "flash_attention_2",
        "sdpa",
        "eager"
    ]

    results: Dict[str, Any] = {}
    successful_backend = None

    for backend in backends:
        print(f"\n{'='*60}")
        print(f"Testing: {backend}")
        print('='*60)

        try:
            # GPU メモリクリア
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()

            # ロード時間計測
            start = time.time()

            model = AutoModelForCausalLM.from_pretrained(
                "microsoft/Florence-2-large",
                trust_remote_code=True,
                torch_dtype=torch.float16,
                attn_implementation=backend
            )

            if torch.cuda.is_available():
                model = model.cuda()

            processor = AutoProcessor.from_pretrained(
                "microsoft/Florence-2-large",
                trust_remote_code=True
            )
            load_time = time.time() - start

            # VRAM使用量
            if torch.cuda.is_available():
                vram_gb = torch.cuda.memory_allocated() / 1024**3
                vram_peak_gb = torch.cuda.max_memory_allocated() / 1024**3
            else:
                vram_gb = 0
                vram_peak_gb = 0

            # ダミー画像で推論テスト
            dummy_img = Image.new('RGB', (640, 480), color='white')

            # OD（物体検出）テスト
            inputs = processor(text="<OD>", images=dummy_img, return_tensors="pt")
            if torch.cuda.is_available():
                inputs = {
                    k: v.cuda().half() if torch.is_tensor(v) and v.dtype == torch.float32
                    else (v.cuda() if torch.is_tensor(v) else v)
                    for k, v in inputs.items()
                }

            start = time.time()
            with torch.no_grad():
                generated_ids = model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=512,
                    num_beams=3
                )
            od_inference_time = time.time() - start

            od_result = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]

            # Caption テスト
            inputs = processor(text="<CAPTION>", images=dummy_img, return_tensors="pt")
            if torch.cuda.is_available():
                inputs = {
                    k: v.cuda().half() if torch.is_tensor(v) and v.dtype == torch.float32
                    else (v.cuda() if torch.is_tensor(v) else v)
                    for k, v in inputs.items()
                }

            start = time.time()
            with torch.no_grad():
                generated_ids = model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=256,
                    num_beams=3
                )
            caption_inference_time = time.time() - start

            caption_result = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]

            results[backend] = {
                "success": True,
                "load_time": load_time,
                "vram_gb": vram_gb,
                "vram_peak_gb": vram_peak_gb,
                "od_inference_time": od_inference_time,
                "caption_inference_time": caption_inference_time,
                "od_sample": od_result[:200],
                "caption_sample": caption_result[:200]
            }

            print(f"SUCCESS")
            print(f"  Load time: {load_time:.2f}s")
            print(f"  VRAM: {vram_gb:.2f} GB (peak: {vram_peak_gb:.2f} GB)")
            print(f"  OD Inference: {od_inference_time:.2f}s")
            print(f"  Caption Inference: {caption_inference_time:.2f}s")
            print(f"  OD sample: {od_result[:100]}...")
            print(f"  Caption sample: {caption_result[:100]}...")

            successful_backend = backend

            # モデル解放
            del model
            del processor
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            # 成功したら終了
            break

        except Exception as e:
            results[backend] = {
                "success": False,
                "error": str(e)
            }
            print(f"FAILED: {e}")

            # 部分的にロードされたものをクリーンアップ
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            continue

    # 結果サマリー
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)

    for backend, result in results.items():
        if result.get("success"):
            print(f"  {backend}:")
            print(f"    OD: {result['od_inference_time']:.2f}s")
            print(f"    Caption: {result['caption_inference_time']:.2f}s")
            print(f"    VRAM: {result['vram_gb']:.2f}GB")
        else:
            error_preview = result.get('error', 'Unknown')[:80]
            print(f"  {backend}: FAILED - {error_preview}")

    print(f"\n{'='*60}")
    if successful_backend:
        print(f"RECOMMENDED BACKEND: {successful_backend}")
        r = results[successful_backend]

        # 成功判定
        checks = []
        checks.append(("VRAM <= 4GB", r['vram_gb'] <= 4.0))
        checks.append(("OD <= 5s", r['od_inference_time'] <= 5.0))
        checks.append(("Caption <= 5s", r['caption_inference_time'] <= 5.0))

        if successful_backend == "flash_attention_2":
            checks.append(("Flash Attn OD <= 3s", r['od_inference_time'] <= 3.0))

        print("\nCHECKS:")
        all_passed = True
        for check_name, passed in checks:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {check_name}")
            if not passed:
                all_passed = False

        if all_passed:
            print("\n ALL CHECKS PASSED")
        else:
            print("\n SOME CHECKS FAILED")
    else:
        print("ALL BACKENDS FAILED")

    print('='*60)

    return {
        "results": results,
        "successful_backend": successful_backend
    }


def check_kernels_installed() -> bool:
    """kernelsパッケージがインストールされているか確認"""
    try:
        import kernels
        print(f"kernels package version: {getattr(kernels, '__version__', 'unknown')}")
        return True
    except ImportError:
        print("kernels package not installed")
        print("Install with: pip install kernels")
        return False


def check_environment():
    """環境情報を表示"""
    print("="*60)
    print("ENVIRONMENT CHECK")
    print("="*60)

    print(f"Python: {sys.version}")
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")

    if torch.cuda.is_available():
        print(f"CUDA version: {torch.version.cuda}")
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

    # transformers バージョン
    try:
        import transformers
        print(f"Transformers: {transformers.__version__}")
    except ImportError:
        print("Transformers: NOT INSTALLED")

    # kernels チェック
    check_kernels_installed()

    print("="*60)


if __name__ == "__main__":
    check_environment()
    print()
    test_florence_kernels()
