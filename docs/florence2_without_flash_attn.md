# Florence-2をflash-attn無しで動作させる技術資料

## 概要

Florence-2（Microsoft製のビジョンモデル）は通常`flash-attn`パッケージを必要とするが、PyTorch 2.9環境ではABI互換性の問題でインストールが困難。本資料では、モックモジュールを使用してflash-attn無しでFlorence-2を動作させる方法を説明する。

## 環境情報

| 項目 | 値 |
|------|-----|
| GPU | NVIDIA RTX A5000 (24GB VRAM) |
| Driver | 560.35.05 |
| CUDA (System) | 12.6 |
| Python | 3.11.13 |
| PyTorch | 2.9.0+cu128 |
| CUDA (PyTorch) | 12.8 |
| cuDNN | 9.10.2 |
| transformers | 4.44.2 |

## 問題

### flash-attnインストールの障害

Florence-2のモデルファイル（`modeling_florence2.py`）は起動時に`flash_attn`パッケージのインポートを試みる。

```python
# Florence-2のmodeling_florence2.py内
if is_flash_attn_2_available():
    from flash_attn import flash_attn_func, flash_attn_varlen_func
    from flash_attn.bert_padding import index_first_axis, pad_input, unpad_input
```

### 試行した解決策と結果

| 試行 | 結果 | エラー内容 |
|------|------|-----------|
| `pip install flash-attn` | ❌ | ソースビルドが必要（20-40分） |
| PyTorch 2.4用プリビルド | ❌ | `undefined symbol: _ZN3c105ErrorC2E...` |
| PyTorch 2.6用プリビルド | ❌ | `undefined symbol: _ZNK3c106SymInt...` |
| PyTorch 2.8用プリビルド | ❌ | 同上（ABI不一致） |

**原因**: PyTorch 2.9はABI（Application Binary Interface）が変更されており、既存のプリビルドホイールと互換性がない。

## 解決策: flash_attnモックモジュール

### 原理

transformersライブラリの`is_flash_attn_2_available()`関数は`importlib.util.find_spec()`を使用してパッケージの存在を確認する。適切な`__spec__`属性を持つモックモジュールを`sys.modules`に登録することで、インポートチェックをパスできる。

### 実装コード

```python
import sys
import types
import importlib.util

def _create_flash_attn_mock() -> None:
    """Create mock modules for flash_attn to avoid import errors"""
    if 'flash_attn' in sys.modules:
        return  # Already loaded (real or mock)

    def create_mock_module(name: str) -> types.ModuleType:
        mock = types.ModuleType(name)
        setattr(mock, '__spec__', importlib.util.spec_from_loader(name, loader=None))
        setattr(mock, '__file__', f"<mock:{name}>")
        setattr(mock, '__path__', [])
        return mock

    # Main flash_attn module
    flash_attn = create_mock_module('flash_attn')
    setattr(flash_attn, '__version__', "2.6.3")
    setattr(flash_attn, 'flash_attn_func', None)
    setattr(flash_attn, 'flash_attn_varlen_func', None)
    sys.modules['flash_attn'] = flash_attn

    # Submodules
    bert_padding = create_mock_module('flash_attn.bert_padding')
    setattr(bert_padding, 'pad_input', None)
    setattr(bert_padding, 'unpad_input', None)
    setattr(bert_padding, 'index_first_axis', None)
    sys.modules['flash_attn.bert_padding'] = bert_padding

    flash_attn_interface = create_mock_module('flash_attn.flash_attn_interface')
    setattr(flash_attn_interface, 'flash_attn_func', None)
    setattr(flash_attn_interface, 'flash_attn_varlen_func', None)
    sys.modules['flash_attn.flash_attn_interface'] = flash_attn_interface

# Initialize before any transformers imports
_create_flash_attn_mock()
```

### 重要ポイント

1. **インポート順序**: モックは`transformers`をインポートする**前**に実行する必要がある
2. **`__spec__`属性**: `importlib.util.find_spec()`が正常に動作するために必須
3. **`attn_implementation="eager"`**: モデルロード時にeager attentionを指定

## Florence-2の使用方法

### モデルロード

```python
from transformers import AutoProcessor, AutoModelForCausalLM
import torch

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
).to("cuda")
```

### 推論

```python
from PIL import Image

image = Image.open("image.jpg")
task_prompt = "<OD>"  # Object Detection

inputs = processor(text=task_prompt, images=image, return_tensors="pt")

# dtype変換（重要: float16に合わせる）
inputs = {
    k: v.to(model.device, dtype=torch.float16) if v.dtype == torch.float32 else v.to(model.device)
    for k, v in inputs.items()
}

with torch.no_grad():
    generated_ids = model.generate(
        input_ids=inputs["input_ids"],
        pixel_values=inputs["pixel_values"],
        max_new_tokens=1024,
        num_beams=3,
    )

# 結果デコード
generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
parsed = processor.post_process_generation(
    generated_text,
    task=task_prompt,
    image_size=(image.width, image.height)
)
```

## テスト結果

### 実行環境

- スクリプト: `scripts/test_florence2_eager.py`
- テスト画像: HuggingFace車画像

### 結果

| 項目 | 値 |
|------|-----|
| モデルロード時間 | 4.5秒 |
| VRAM使用量 | 0.44 GB |
| 推論時間 | 2229ms |
| 検出オブジェクト | car, door handle, wheel x2 |

### 出力例

```json
{
  "<OD>": {
    "bboxes": [
      [34.24, 160.08, 597.44, 371.76],
      [272.32, 241.68, 303.68, 247.44],
      [454.08, 276.72, 553.92, 370.80],
      [96.32, 280.56, 198.08, 371.28]
    ],
    "labels": ["car", "door handle", "wheel", "wheel"]
  }
}
```

## プロジェクトへの適用

### 変更ファイル

- `src/vision_processor.py`: ファイル先頭にモック関数を追加

### 利用可能なセグメンテーションモデル

| モデル | 説明 |
|--------|------|
| `yolov8` | 高速、一般物体検出 |
| `florence2-base` | Microsoft製、詳細検出 |
| `florence2-large` | より高精度（VRAM多め） |

## 注意事項

1. **パフォーマンス**: eager attentionはflash-attnより遅い（約2-3倍）
2. **メモリ**: eager attentionはVRAM使用量が多くなる可能性あり
3. **将来の互換性**: PyTorch/transformersのバージョンアップで挙動が変わる可能性あり

## 参考リンク

- [flash-attention-prebuild-wheels](https://github.com/mjun0812/flash-attention-prebuild-wheels) - プリビルドホイール
- [Flash Attention Prebuilt Wheels](https://flashattn.dev/) - ホイール検索ツール
- [Dao-AILab/flash-attention](https://github.com/Dao-AILab/flash-attention) - 公式リポジトリ

## 更新履歴

| 日付 | 内容 |
|------|------|
| 2026-01-04 | 初版作成、モック実装完了 |
