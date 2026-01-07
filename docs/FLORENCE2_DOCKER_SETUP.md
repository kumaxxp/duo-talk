# Florence-2 Docker Service セットアップガイド

## クイックスタート（推奨）

```bash
# 一括起動（vLLM + Florence-2）
./scripts/docker_services.sh start

# 状態確認
./scripts/docker_services.sh status

# 一括停止
./scripts/docker_services.sh stop
```

またはPythonから：

```bash
python -m src.docker_manager start
python -m src.docker_manager status
```

---

## 概要

Florence-2をDockerコンテナで実行し、duo-talkから利用するためのガイドです。

### 特徴

- **flash-attn不要**: PyTorch SDPAを使用（同等速度）
- **transformers 4.49.0固定**: 安定動作を保証
- **vLLMと共存**: GPU メモリを適切に分割
- **REST API**: FastAPIベースの統一インターフェース

### アーキテクチャ

```
duo-talk (conda環境)
    │
    ├─ Florence2Client ──→ Florence-2 Docker (port 5001)
    │                      └─ SDPA attention
    │                      └─ 25% GPU memory (~6GB)
    │
    └─ LLMProvider ──────→ vLLM Docker (port 8000)
                           └─ Gemma 3 12B
                           └─ 55% GPU memory (~13GB)
```

## クイックスタート

### 1. Dockerイメージのビルド

```bash
cd ~/work/duo-talk

# Florence-2イメージをビルド
docker build -t duo-talk-florence2 docker/florence2/
```

### 2. 単体起動（テスト用）

```bash
# Florence-2のみ起動
docker run --gpus all -p 5001:5001 \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    --name florence2-test \
    duo-talk-florence2

# 別ターミナルでテスト
curl http://localhost:5001/health
```

### 3. vLLMと同時起動（本番用）

```bash
# docker-compose で両方起動
docker compose -f docker/docker-compose.florence2.yml up -d

# 状態確認
docker compose -f docker/docker-compose.florence2.yml ps

# ログ確認
docker compose -f docker/docker-compose.florence2.yml logs -f florence2
```

## API エンドポイント

### ヘルスチェック

```bash
curl http://localhost:5001/health
```

```json
{
  "status": "healthy",
  "model_loaded": true,
  "device": "cuda:0",
  "gpu_memory_gb": 4.52
}
```

### タスク一覧

```bash
curl http://localhost:5001/tasks
```

### 推論（Base64画像）

```bash
# 画像をBase64エンコード
IMAGE_B64=$(base64 -w0 test_image.jpg)

# キャプション生成
curl -X POST http://localhost:5001/infer \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$IMAGE_B64\", \"task\": \"caption\"}"
```

### 推論（ファイルアップロード）

```bash
curl -X POST http://localhost:5001/infer/upload \
  -F "file=@test_image.jpg" \
  -F "task=object_detection"
```

## 利用可能なタスク

| タスク | 説明 |
|--------|------|
| `caption` | シンプルなキャプション |
| `detailed_caption` | 詳細なキャプション |
| `more_detailed_caption` | より詳細なキャプション |
| `object_detection` | 物体検出（バウンディングボックス付き） |
| `dense_region_caption` | 領域ごとのキャプション |
| `ocr` | テキスト抽出 |
| `ocr_with_region` | 位置付きテキスト抽出 |
| `referring_expression_segmentation` | テキスト指定セグメンテーション |
| `phrase_grounding` | フレーズグラウンディング |

## Python クライアント

### 基本使用法

```python
from src.florence2_client import Florence2Client

# クライアント作成
client = Florence2Client("http://localhost:5001")

# ヘルスチェック
if client.is_ready():
    print("Service ready!")

# キャプション生成
result = client.caption("path/to/image.jpg")
print(result.text)

# 詳細キャプション
result = client.caption("path/to/image.jpg", detailed=True)
print(result.text)

# 物体検出
result = client.detect_objects("path/to/image.jpg")
print(f"Objects: {result.objects}")
print(f"Bboxes: {result.bboxes}")

# OCR
result = client.ocr("path/to/image.jpg")
print(f"Text: {result.text}")

# セグメンテーション
result = client.segment("path/to/image.jpg", "the red car")
print(result.result)

# クライアント終了
client.close()
```

### with構文

```python
with Florence2Client("http://localhost:5001") as client:
    result = client.caption("image.jpg")
    print(result.text)
```

## テスト

### Dockerサービステスト

```bash
# サービス起動後
python scripts/test_florence2_service.py --docker

# 画像付きテスト
python scripts/test_florence2_service.py --docker --image test_image.jpg
```

### 直接テスト（Docker不要、要transformers==4.49.0）

```bash
python scripts/test_florence2_service.py --direct
```

## GPU メモリ設定

### A5000 24GB での推奨設定

| サービス | メモリ割当 | 設定 |
|----------|-----------|------|
| Florence-2 | ~6GB (25%) | `CUDA_MEMORY_FRACTION=0.25` |
| vLLM | ~13GB (55%) | `--gpu-memory-utilization 0.55` |
| 余裕 | ~5GB | CUDA context + バッファ |

### 環境変数で調整

```bash
# .envファイル
GPU_MEMORY_UTIL=0.55  # vLLM用
CUDA_MEMORY_FRACTION=0.25  # Florence-2用
```

## トラブルシューティング

### モデルロードが遅い

初回起動時はモデルダウンロードが必要です（約1.5GB）。

```bash
# HuggingFaceキャッシュを確認
ls ~/.cache/huggingface/hub/models--microsoft--Florence-2-large/
```

### GPU メモリ不足

```bash
# 他のGPUプロセスを確認
nvidia-smi

# メモリ割当を調整
GPU_MEMORY_UTIL=0.50 docker compose -f docker/docker-compose.florence2.yml up -d
```

### transformersバージョンエラー

```
'Florence2ForConditionalGeneration' object has no attribute '_supports_sdpa'
```

→ transformers 4.49.0 を使用してください（Dockerイメージでは固定済み）

### flash-attn関連エラー

```
ImportError: flash_attn is required
```

→ import パッチが正しく適用されていません。Dockerイメージを再ビルドしてください。

## ファイル構成

```
docker/
├── florence2/
│   ├── Dockerfile          # Florence-2 Dockerイメージ
│   ├── main.py             # FastAPIサーバー
│   └── requirements.txt    # Python依存関係
├── docker-compose.florence2.yml  # Florence-2 + vLLM
└── docker-compose.yml      # vLLMのみ（既存）

src/
├── florence2_client.py     # Florence-2 Pythonクライアント
└── docker_manager.py       # Docker管理クラス

scripts/
├── docker_services.sh      # Docker一括管理シェルスクリプト
├── start_duo_talk.py       # duo-talk起動スクリプト
└── test_florence2_service.py  # テストスクリプト
```

## 管理スクリプト使用法

### シェルスクリプト（推奨）

```bash
# 実行権限を付与（初回のみ）
chmod +x scripts/docker_services.sh

# コマンド一覧
./scripts/docker_services.sh start    # 全サービス起動
./scripts/docker_services.sh stop     # 全サービス停止
./scripts/docker_services.sh restart  # 再起動
./scripts/docker_services.sh status   # 状態確認
./scripts/docker_services.sh health   # ヘルスチェック
./scripts/docker_services.sh logs     # ログ表示
./scripts/docker_services.sh clean    # コンテナ削除
```

### Pythonモジュール

```bash
python -m src.docker_manager start    # 全サービス起動
python -m src.docker_manager stop     # 全サービス停止
python -m src.docker_manager status   # 状態確認
python -m src.docker_manager ensure   # 動いていなければ起動
```

### Pythonコードから

```python
from src.docker_manager import DockerServiceManager

manager = DockerServiceManager()

# 状態確認
status = manager.status()
print(status)

# サービス起動（動いていなければ起動）
manager.ensure_running()

# 状態表示
manager.print_status()
```

## 参考リンク

- [Florence-2 HuggingFace](https://huggingface.co/microsoft/Florence-2-large)
- [PyTorch SDPA](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)
- [transformers 4.49.0](https://github.com/huggingface/transformers/releases/tag/v4.49.0)
