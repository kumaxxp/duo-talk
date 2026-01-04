#!/bin/bash
# vLLM Docker Stop Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"

echo "Stopping vLLM Docker container..."

cd "$DOCKER_DIR"
docker compose down

echo "vLLM container stopped."
