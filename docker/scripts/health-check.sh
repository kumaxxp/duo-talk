#!/bin/bash
# vLLM Health Check Script

VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_URL="http://localhost:$VLLM_PORT"

echo "=========================================="
echo "vLLM Health Check"
echo "=========================================="

# Check if container is running
if docker ps --filter "name=duo-talk-vllm" --format "{{.Status}}" | grep -q "Up"; then
    echo "Container: Running"
else
    echo "Container: Not running"
    echo ""
    echo "Start with: ./start-vllm.sh"
    exit 1
fi

# Check API health
echo -n "API Status: "
if curl -sf "$VLLM_URL/v1/models" > /dev/null 2>&1; then
    echo "Ready"

    # Get model info
    echo ""
    echo "Loaded Models:"
    curl -s "$VLLM_URL/v1/models" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for model in data.get('data', []):
    print(f\"  - {model['id']}\")
" 2>/dev/null || echo "  (unable to parse)"
else
    echo "Not ready (model still loading)"
    echo ""
    echo "View logs with: ./logs.sh"
fi

# GPU memory usage
echo ""
echo "GPU Memory Usage:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | while read used total; do
    percent=$((used * 100 / total))
    echo "  ${used}MB / ${total}MB (${percent}%)"
done

echo "=========================================="
