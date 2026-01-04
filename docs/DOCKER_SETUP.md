# vLLM Docker Setup Guide

duo-talk v2.1 で vLLM をDockerで運用するためのガイド。

## 前提条件

- Docker Engine + NVIDIA Container Toolkit
- NVIDIA GPU（推奨: RTX A5000 24GB以上）
- CUDA 12.x

### NVIDIA Container Toolkit インストール

```bash
# Ubuntu/Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

## クイックスタート

### 1. 環境設定

```bash
cd docker
cp .env.example .env
# 必要に応じて .env を編集
```

### 2. vLLM 起動

```bash
# デフォルト（Gemma 3 12B INT8）で起動
./scripts/start-vllm.sh

# 特定モデルを指定
./scripts/start-vllm.sh gemma3-12b-int8    # 推奨構成
./scripts/start-vllm.sh gemma3-12b-gptq    # 軽量版
./scripts/start-vllm.sh qwen25-14b-awq     # Qwen（VLMなし）
```

### 3. 動作確認

```bash
# ヘルスチェック
./scripts/health-check.sh

# ログ確認
./scripts/logs.sh
./scripts/logs.sh -f  # リアルタイム表示
```

### 4. 停止

```bash
./scripts/stop-vllm.sh
```

## 利用可能なモデル

| モデルID | 正式名 | VRAM | VLM | 備考 |
|---------|--------|------|-----|------|
| `gemma3-12b-int8` | RedHatAI/gemma-3-12b-it-quantized.w8a8 | ~14GB | Yes | **推奨** |
| `gemma3-12b-gptq` | ISTA-DASLab/gemma-3-12b-it-GPTQ-4b-128g | ~7GB | Yes | 軽量版 |
| `qwen25-14b-awq` | Qwen/Qwen2.5-14B-Instruct-AWQ | ~10GB | No | テキスト専用 |

## モデル切り替え

```bash
# 別モデルに切り替え（停止→起動）
./scripts/switch-model.sh gemma3-12b-gptq
```

## トラブルシューティング

### モデルロードに時間がかかる

初回起動時はモデルのダウンロードが必要です。
Gemma 3 12B INT8の場合、約12GBのダウンロードに10-30分程度かかります。

```bash
# ログでダウンロード進捗を確認
./scripts/logs.sh -f
```

### OOMエラー（メモリ不足）

GPU_MEMORY_UTIL を下げるか、軽量モデルに切り替えてください。

```bash
# .env を編集
GPU_MEMORY_UTIL=0.80
MAX_MODEL_LEN=4096

# または軽量モデルを使用
./scripts/switch-model.sh gemma3-12b-gptq
```

### API接続できない

```bash
# コンテナ状態確認
docker ps -a | grep duo-talk-vllm

# ポート確認
curl http://localhost:8000/v1/models

# ログでエラー確認
./scripts/logs.sh
```

### GPUが認識されない

```bash
# Docker内でGPU確認
docker run --rm --gpus all nvidia/cuda:12.1-base nvidia-smi
```

## LLMProvider との連携

アプリケーションから vLLM を使用するには `LLMProvider` を使用します。

```python
from src.llm_provider import get_llm_provider, BackendType

provider = get_llm_provider()

# vLLMに切り替え
result = provider.switch_backend(BackendType.VLLM, "gemma3-12b-int8")
if result["success"]:
    print(f"Switched to {result['model']}")

# ヘルスチェック
status = provider.check_backend_health(BackendType.VLLM)
print(f"vLLM available: {status.available}")
```

## API エンドポイント

vLLM 起動後、以下のエンドポイントが利用可能：

| エンドポイント | 説明 |
|---------------|------|
| `GET /v1/models` | 利用可能モデル一覧 |
| `POST /v1/chat/completions` | チャット補完（メイン） |
| `POST /v1/completions` | テキスト補完 |

### リクエスト例

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RedHatAI/gemma-3-12b-it-quantized.w8a8",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

## ディレクトリ構成

```
docker/
├── docker-compose.yml        # vLLM メイン構成
├── docker-compose.ollama.yml # Ollama 参考構成
├── .env.example              # 環境変数テンプレート
├── .env                      # 環境変数（要作成）
└── scripts/
    ├── start-vllm.sh         # 起動スクリプト
    ├── stop-vllm.sh          # 停止スクリプト
    ├── health-check.sh       # ヘルスチェック
    ├── switch-model.sh       # モデル切り替え
    └── logs.sh               # ログ表示
```
