"""
Florence-2 Kernels 動作検証スクリプト

検証内容:
1. flash_attnダミーモジュールでインポートエラーをバイパス
2. Kernels (`kernels-community/flash-attn2`) でロード試行
3. 失敗したらSDPA → eager へfallback
4. OD / Caption の推論時間を計測
5. VRAM使用量を計測
"""

import sys
import time
import torch
from PIL import Image
from pathlib import Path
from types import ModuleType

# テスト画像を用意（なければダミー作成）
TEST_IMAGE_PATH = "tests/images/sample.jpg"


def setup_flash_attn_dummy():
    """
    flash_attn ダミーモジュールを作成してインポートエラーを回避
    Florence-2のモデルコードは flash_attn をインポートしようとするが、
    attn_implementation が eager/sdpa の場合は実際には使用しない
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

        print("[INFO] flash_attn ダミーモジュールを設定しました")
        return True
    return False


def create_dummy_image():
    """テスト用ダミー画像を作成"""
    img = Image.new("RGB", (640, 480), color=(128, 128, 128))
    Path("tests/images").mkdir(parents=True, exist_ok=True)
    img.save(TEST_IMAGE_PATH)
    print(f"Created dummy image: {TEST_IMAGE_PATH}")


def get_vram_usage():
    """現在のVRAM使用量をGB単位で取得"""
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / 1024**3
    return 0.0


def test_florence2_with_backend(backend: str) -> dict:
    """
    指定バックエンドでFlorence-2をテスト

    Args:
        backend: "kernels-community/flash-attn2", "sdpa", or "eager"

    Returns:
        dict: テスト結果
    """
    from transformers import AutoModelForCausalLM, AutoProcessor

    result = {
        "backend": backend,
        "load_success": False,
        "load_time_sec": 0.0,
        "vram_gb": 0.0,
        "od_time_sec": 0.0,
        "caption_time_sec": 0.0,
        "error": None
    }

    # VRAM初期化
    torch.cuda.empty_cache()
    initial_vram = get_vram_usage()

    model = None
    processor = None

    try:
        # モデルロード
        print(f"\n{'='*50}")
        print(f"Testing backend: {backend}")
        print(f"{'='*50}")

        load_start = time.time()

        model = AutoModelForCausalLM.from_pretrained(
            "microsoft/Florence-2-large",
            trust_remote_code=True,
            torch_dtype=torch.float16,
            attn_implementation=backend
        ).cuda()

        processor = AutoProcessor.from_pretrained(
            "microsoft/Florence-2-large",
            trust_remote_code=True
        )

        load_time = time.time() - load_start
        result["load_success"] = True
        result["load_time_sec"] = round(load_time, 2)
        result["vram_gb"] = round(get_vram_usage() - initial_vram, 2)

        print(f"  Load success: {load_time:.2f}s, VRAM: {result['vram_gb']:.2f} GB")

        # テスト画像読み込み
        if not Path(TEST_IMAGE_PATH).exists():
            create_dummy_image()
        image = Image.open(TEST_IMAGE_PATH).convert("RGB")

        # OD (Object Detection) テスト
        od_start = time.time()
        inputs = processor(text="<OD>", images=image, return_tensors="pt")
        # fp16モデルにはfp16入力が必要
        inputs = {
            k: v.cuda().half() if torch.is_tensor(v) and v.dtype == torch.float32 else (v.cuda() if torch.is_tensor(v) else v)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=512,
                num_beams=3
            )
        od_result = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        result["od_time_sec"] = round(time.time() - od_start, 2)
        print(f"  OD inference: {result['od_time_sec']:.2f}s")
        print(f"   Result preview: {od_result[:100]}...")

        # Caption テスト
        caption_start = time.time()
        inputs = processor(text="<CAPTION>", images=image, return_tensors="pt")
        inputs = {
            k: v.cuda().half() if torch.is_tensor(v) and v.dtype == torch.float32 else (v.cuda() if torch.is_tensor(v) else v)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=256,
                num_beams=3
            )
        caption_result = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        result["caption_time_sec"] = round(time.time() - caption_start, 2)
        print(f"  Caption inference: {result['caption_time_sec']:.2f}s")
        print(f"   Result: {caption_result[:100]}...")

    except Exception as e:
        result["error"] = str(e)
        print(f"  Error with {backend}: {e}")

    finally:
        # クリーンアップ
        if model is not None:
            del model
        if processor is not None:
            del processor
        torch.cuda.empty_cache()

    return result


def main():
    """メイン実行"""
    print("="*60)
    print("Florence-2 Kernels 動作検証")
    print("="*60)

    # flash_attn ダミー設定
    setup_flash_attn_dummy()

    # バックエンドを優先順で試行
    # Note: Florence-2 は "kernels-community/flash-attn2" をサポートしていない
    #       対応バックエンド: eager, flash_attention_2, sdpa
    backends = [
        "flash_attention_2",               # FlashAttention2（要flash-attn）
        "sdpa",                            # PyTorch SDPA
        "eager",                           # eager（保険）
    ]

    results = []
    successful_backend = None

    for backend in backends:
        result = test_florence2_with_backend(backend)
        results.append(result)

        if result["load_success"] and successful_backend is None:
            successful_backend = backend

    # 結果サマリー
    print("\n" + "="*60)
    print("テスト結果サマリー")
    print("="*60)

    print(f"\n{'Backend':<35} {'Load':<8} {'VRAM':<10} {'OD':<10} {'Caption':<10}")
    print("-"*75)

    for r in results:
        status = "OK" if r["load_success"] else "NG"
        vram = f"{r['vram_gb']:.2f} GB" if r["load_success"] else "N/A"
        od = f"{r['od_time_sec']:.2f}s" if r["load_success"] else "N/A"
        caption = f"{r['caption_time_sec']:.2f}s" if r["load_success"] else "N/A"
        print(f"{r['backend']:<35} {status:<8} {vram:<10} {od:<10} {caption:<10}")

    print("\n" + "="*60)

    if successful_backend:
        print(f"推奨バックエンド: {successful_backend}")

        # 成功判定基準
        success_result = next(r for r in results if r["backend"] == successful_backend)

        criteria = {
            "VRAM 4GB以下": success_result["vram_gb"] <= 4.0,
            "OD推論 5秒以下": success_result["od_time_sec"] <= 5.0,
            "Caption推論 3秒以下": success_result["caption_time_sec"] <= 3.0,
        }

        print("\n成功判定:")
        all_pass = True
        for name, passed in criteria.items():
            status = "OK" if passed else "NG"
            print(f"  [{status}] {name}")
            if not passed:
                all_pass = False

        if all_pass:
            print("\n全基準クリア！このバックエンドを採用できます。")
        else:
            print("\n一部基準を満たしていません。eagerへのフォールバックを検討してください。")
    else:
        print("全バックエンドで失敗しました。環境を確認してください。")

    return results


if __name__ == "__main__":
    main()
