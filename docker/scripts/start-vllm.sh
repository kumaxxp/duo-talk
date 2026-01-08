#!/bin/bash
# vLLM Docker Start Script
# Usage: ./start-vllm.sh [model_name]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment if exists
if [ -f "$DOCKER_DIR/.env" ]; then
    export $(grep -v '^#' "$DOCKER_DIR/.env" | xargs)
fi

# Model presets
declare -A MODELS=(
    ["gemma3-27b-int4"]="RedHatAI/gemma-3-27b-it-quantized.w4a16"
    ["gemma3-12b-int8"]="RedHatAI/gemma-3-12b-it-quantized.w8a8"
    ["gemma3-12b-gptq"]="ISTA-DASLab/gemma-3-12b-it-GPTQ-4b-128g"
    ["qwen25-14b-awq"]="Qwen/Qwen2.5-14B-Instruct-AWQ"
)

# Parse arguments
MODEL_KEY="${1:-gemma3-12b-int8}"

if [ -n "${MODELS[$MODEL_KEY]}" ]; then
    VLLM_MODEL="${MODELS[$MODEL_KEY]}"
    echo "Using preset model: $MODEL_KEY -> $VLLM_MODEL"
else
    # Assume it's a full model name
    VLLM_MODEL="$MODEL_KEY"
    echo "Using custom model: $VLLM_MODEL"
fi

# Set extra args for AWQ models
VLLM_EXTRA_ARGS=""
if [[ "$VLLM_MODEL" == *"AWQ"* ]] || [[ "$VLLM_MODEL" == *"awq"* ]]; then
    VLLM_EXTRA_ARGS="--quantization awq"
fi

export VLLM_MODEL
export VLLM_EXTRA_ARGS

echo "=========================================="
echo "Starting vLLM Docker Container"
echo "=========================================="
echo "Model: $VLLM_MODEL"
echo "Port: ${VLLM_PORT:-8000}"
echo "GPU Memory Util: ${GPU_MEMORY_UTIL:-0.85}"
echo "Max Model Len: ${MAX_MODEL_LEN:-8192}"
echo "=========================================="

cd "$DOCKER_DIR"

# Stop existing container if running
docker compose down 2>/dev/null || true

# Start container
docker compose up -d

echo ""
echo "Container started. Waiting for model to load..."
echo "This may take 1-2 minutes for large models."
echo ""
echo "Check status with: $SCRIPT_DIR/health-check.sh"
echo "View logs with: $SCRIPT_DIR/logs.sh"
