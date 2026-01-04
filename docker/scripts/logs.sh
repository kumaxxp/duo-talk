#!/bin/bash
# vLLM Docker Logs Script
# Usage: ./logs.sh [-f]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"

cd "$DOCKER_DIR"

if [ "$1" = "-f" ] || [ "$1" = "--follow" ]; then
    docker compose logs -f vllm
else
    docker compose logs --tail=100 vllm
fi
