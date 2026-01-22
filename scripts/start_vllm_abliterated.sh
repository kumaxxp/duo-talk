#!/bin/bash
#
# vLLM Abliterated Model起動スクリプト
#
# 使用方法:
#   ./scripts/start_vllm_abliterated.sh [model_key]
#
# モデルキー:
#   abliterated    - mlabonne/gemma-3-12b-it-abliterated (デフォルト)
#   abliterated-v2 - mlabonne/gemma-3-12b-it-abliterated-v2
#   heretic        - DreamFast/gemma-3-12b-it-heretic (推奨)
#   abliterated-4b - mlabonne/gemma-3-4b-it-abliterated (軽量版)
#
# 例:
#   ./scripts/start_vllm_abliterated.sh heretic
#   ./scripts/start_vllm_abliterated.sh abliterated-4b

set -e

# デフォルト設定
MODEL_KEY="${1:-abliterated}"
PORT=8000
GPU_MEMORY_UTILIZATION=0.85
MAX_MODEL_LEN=8192

# モデルマッピング
declare -A MODEL_MAP=(
    ["abliterated"]="mlabonne/gemma-3-12b-it-abliterated"
    ["abliterated-v2"]="mlabonne/gemma-3-12b-it-abliterated-v2"
    ["heretic"]="DreamFast/gemma-3-12b-it-heretic"
    ["abliterated-4b"]="mlabonne/gemma-3-4b-it-abliterated"
)

# VRAM推定値
declare -A VRAM_MAP=(
    ["abliterated"]="24"
    ["abliterated-v2"]="24"
    ["heretic"]="24"
    ["abliterated-4b"]="8"
)

# モデル検証
if [[ -z "${MODEL_MAP[$MODEL_KEY]}" ]]; then
    echo "ERROR: Unknown model key: $MODEL_KEY"
    echo ""
    echo "Available models:"
    for key in "${!MODEL_MAP[@]}"; do
        echo "  $key -> ${MODEL_MAP[$key]}"
    done
    exit 1
fi

MODEL_NAME="${MODEL_MAP[$MODEL_KEY]}"
VRAM_ESTIMATE="${VRAM_MAP[$MODEL_KEY]}"

echo "========================================"
echo "  vLLM Abliterated Model Launcher"
echo "========================================"
echo "Model Key: $MODEL_KEY"
echo "Model: $MODEL_NAME"
echo "VRAM Estimate: ${VRAM_ESTIMATE}GB"
echo "Port: $PORT"
echo "GPU Memory Utilization: $GPU_MEMORY_UTILIZATION"
echo "Max Model Length: $MAX_MODEL_LEN"
echo "========================================"

# 既存のvLLMコンテナを停止
echo ""
echo "Stopping existing vLLM containers..."
docker stop vllm-abliterated 2>/dev/null || true
docker rm vllm-abliterated 2>/dev/null || true

# HuggingFaceキャッシュディレクトリ
HF_CACHE="${HOME}/.cache/huggingface"
mkdir -p "$HF_CACHE"

echo ""
echo "Starting vLLM with $MODEL_NAME..."
echo ""

# vLLMコンテナ起動
docker run -d \
    --name vllm-abliterated \
    --gpus all \
    --ipc=host \
    -p ${PORT}:8000 \
    -v "${HF_CACHE}:/root/.cache/huggingface" \
    -e "HUGGING_FACE_HUB_TOKEN=${HUGGING_FACE_HUB_TOKEN:-}" \
    vllm/vllm-openai:latest \
    --model "$MODEL_NAME" \
    --trust-remote-code \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --dtype bfloat16

echo ""
echo "Container started. Waiting for model to load..."
echo ""

# ヘルスチェック（最大5分待機）
MAX_WAIT=300
WAIT_INTERVAL=10
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -s "http://localhost:${PORT}/v1/models" > /dev/null 2>&1; then
        echo ""
        echo "========================================"
        echo "  vLLM is ready!"
        echo "========================================"
        echo "API: http://localhost:${PORT}/v1"
        echo "Models: http://localhost:${PORT}/v1/models"
        echo ""
        echo "Test command:"
        echo "  curl http://localhost:${PORT}/v1/chat/completions \\"
        echo "    -H 'Content-Type: application/json' \\"
        echo "    -d '{\"model\": \"$MODEL_NAME\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]}'"
        echo ""
        exit 0
    fi

    echo "Waiting for vLLM to be ready... (${ELAPSED}s / ${MAX_WAIT}s)"
    sleep $WAIT_INTERVAL
    ELAPSED=$((ELAPSED + WAIT_INTERVAL))
done

echo ""
echo "ERROR: vLLM failed to start within ${MAX_WAIT}s"
echo ""
echo "Check logs with:"
echo "  docker logs vllm-abliterated"
echo ""
exit 1
