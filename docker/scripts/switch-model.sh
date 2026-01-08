#!/bin/bash
# vLLM Model Switch Script
# Usage: ./switch-model.sh <model_name>

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Model presets
declare -A MODELS=(
    ["gemma3-27b-int4"]="RedHatAI/gemma-3-27b-it-quantized.w4a16"
    ["gemma3-12b-int8"]="RedHatAI/gemma-3-12b-it-quantized.w8a8"
    ["gemma3-12b-gptq"]="ISTA-DASLab/gemma-3-12b-it-GPTQ-4b-128g"
    ["qwen25-14b-awq"]="Qwen/Qwen2.5-14B-Instruct-AWQ"
)

if [ -z "$1" ]; then
    echo "Usage: $0 <model_name>"
    echo ""
    echo "Available presets:"
    for key in "${!MODELS[@]}"; do
        echo "  $key -> ${MODELS[$key]}"
    done
    echo ""
    echo "Or specify a full Hugging Face model name."
    exit 1
fi

MODEL_KEY="$1"

echo "Switching to model: $MODEL_KEY"
echo ""

# Stop current container
"$SCRIPT_DIR/stop-vllm.sh"

echo ""

# Start with new model
"$SCRIPT_DIR/start-vllm.sh" "$MODEL_KEY"
