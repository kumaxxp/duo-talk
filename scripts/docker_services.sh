#!/bin/bash
# duo-talk Docker Service Manager
# 
# Usage:
#   ./scripts/docker_services.sh start   - Start all services (vLLM first, then Florence-2)
#   ./scripts/docker_services.sh stop    - Stop all services
#   ./scripts/docker_services.sh restart - Restart all services
#   ./scripts/docker_services.sh status  - Show service status
#   ./scripts/docker_services.sh logs    - Show logs (follow mode)
#   ./scripts/docker_services.sh clean   - Stop and remove all containers

set -e

# ============================================================
# Configuration
# ============================================================

VLLM_CONTAINER="duo-talk-vllm"
FLORENCE_CONTAINER="duo-talk-florence2"
FLORENCE_IMAGE="duo-talk-florence2"

VLLM_PORT=8000
FLORENCE_PORT=5001

# vLLM settings
# vLLM settings
VLLM_MODEL="RedHatAI/gemma-3-12b-it-quantized.w8a8"
VLLM_GPU_MEMORY=0.85
VLLM_MAX_MODEL_LEN=8192



# HuggingFace cache
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================
# Helper Functions
# ============================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if container exists (running or stopped)
container_exists() {
    docker ps -a --format '{{.Names}}' | grep -q "^$1$"
}

# Check if container is running
container_running() {
    docker ps --format '{{.Names}}' | grep -q "^$1$"
}

# Wait for HTTP endpoint to be ready
wait_for_endpoint() {
    local url=$1
    local timeout=${2:-300}
    local interval=${3:-5}
    local elapsed=0
    
    log_info "Waiting for $url to be ready (timeout: ${timeout}s)..."
    
    while [ $elapsed -lt $timeout ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -n "."
    done
    echo ""
    return 1
}

# ============================================================
# Stop Functions
# ============================================================

# Load Configuration from .env
# ============================================================

# Load configuration from .env if available
ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
    # Load .env variables (ignoring comments)
    export $(grep -v '^#' "$ENV_FILE" | xargs)
    
    if [ -n "$OPENAI_MODEL" ]; then
        log_info "Using model from .env: $OPENAI_MODEL"
        VLLM_MODEL="$OPENAI_MODEL"
    fi
fi

stop_container() {
    local name=$1
    if container_running "$name"; then
        log_info "Stopping $name..."
        docker stop "$name" > /dev/null
        log_success "$name stopped"
    fi
}

remove_container() {
    local name=$1
    if container_exists "$name"; then
        log_info "Removing $name..."
        docker rm "$name" > /dev/null 2>&1 || true
        log_success "$name removed"
    fi
}

stop_all() {
    log_info "Stopping all duo-talk services..."
    stop_container "$FLORENCE_CONTAINER"
    stop_container "$VLLM_CONTAINER"
    log_success "All services stopped"
}

clean_all() {
    log_info "Cleaning up all duo-talk containers..."
    stop_container "$FLORENCE_CONTAINER"
    stop_container "$VLLM_CONTAINER"
    remove_container "$FLORENCE_CONTAINER"
    remove_container "$VLLM_CONTAINER"
    log_success "All containers cleaned up"
}

# ============================================================
# Start Functions
# ============================================================

start_vllm() {
    if container_running "$VLLM_CONTAINER"; then
        log_warn "$VLLM_CONTAINER is already running"
        return 0
    fi
    
    # Remove existing stopped container
    remove_container "$VLLM_CONTAINER"
    
    log_info "Starting vLLM ($VLLM_MODEL)..."
    docker run -d --gpus all \
        -v "$HF_CACHE:/root/.cache/huggingface" \
        -p "${VLLM_PORT}:8000" \
        --ipc=host \
        --name "$VLLM_CONTAINER" \
        vllm/vllm-openai:latest \
        --model "$VLLM_MODEL" \
        --gpu-memory-utilization "$VLLM_GPU_MEMORY" \
        --max-model-len "$VLLM_MAX_MODEL_LEN" \
        --trust-remote-code \
        > /dev/null
    
    # Wait for vLLM to be ready
    if wait_for_endpoint "http://localhost:${VLLM_PORT}/v1/models" 300 5; then
        log_success "vLLM is ready"
        return 0
    else
        log_error "vLLM failed to start within timeout"
        docker logs --tail 50 "$VLLM_CONTAINER"
        return 1
    fi
}

start_florence() {
    if container_running "$FLORENCE_CONTAINER"; then
        log_warn "$FLORENCE_CONTAINER is already running"
        return 0
    fi
    
    # Remove existing stopped container
    remove_container "$FLORENCE_CONTAINER"
    
    log_info "Starting Florence-2..."
    docker run -d --gpus all \
        -v "$HF_CACHE:/root/.cache/huggingface" \
        -p "${FLORENCE_PORT}:5001" \
        --ipc=host \
        --name "$FLORENCE_CONTAINER" \
        "$FLORENCE_IMAGE" \
        > /dev/null
    
    # Wait for Florence-2 to be ready
    if wait_for_endpoint "http://localhost:${FLORENCE_PORT}/health" 180 5; then
        log_success "Florence-2 is ready"
        return 0
    else
        log_error "Florence-2 failed to start within timeout"
        docker logs --tail 50 "$FLORENCE_CONTAINER"
        return 1
    fi
}

start_all() {
    log_info "Starting all duo-talk services..."
    echo ""
    
    # Check for existing containers and stop them
    if container_running "$VLLM_CONTAINER" || container_running "$FLORENCE_CONTAINER"; then
        log_warn "Found running containers, stopping them first..."
        stop_all
        sleep 2
    fi
    
    # Clean up any stopped containers
    remove_container "$VLLM_CONTAINER"
    remove_container "$FLORENCE_CONTAINER"
    
    # Start vLLM first (needs more GPU memory)
    echo ""
    echo "=========================================="
    echo "Step 1/2: Starting vLLM"
    echo "=========================================="
    if ! start_vllm; then
        log_error "Failed to start vLLM"
        return 1
    fi
    
    # Then start Florence-2
    echo ""
    echo "=========================================="
    echo "Step 2/2: Starting Florence-2"
    echo "=========================================="
    if ! start_florence; then
        log_error "Failed to start Florence-2"
        return 1
    fi
    
    echo ""
    echo "=========================================="
    log_success "All services started successfully!"
    echo "=========================================="
    echo ""
    show_status
}

# ============================================================
# Status Functions
# ============================================================

show_status() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║           duo-talk Docker Services Status                ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    
    # vLLM status
    if container_running "$VLLM_CONTAINER"; then
        local vllm_health=$(curl -s "http://localhost:${VLLM_PORT}/v1/models" 2>/dev/null | head -c 50)
        if [ -n "$vllm_health" ]; then
            echo -e "║  vLLM:      ${GREEN}● Running${NC}  (port $VLLM_PORT)                    ║"
        else
            echo -e "║  vLLM:      ${YELLOW}● Starting${NC} (port $VLLM_PORT)                    ║"
        fi
    else
        echo -e "║  vLLM:      ${RED}○ Stopped${NC}                                   ║"
    fi
    
    # Florence-2 status
    if container_running "$FLORENCE_CONTAINER"; then
        local florence_health=$(curl -s "http://localhost:${FLORENCE_PORT}/health" 2>/dev/null)
        if echo "$florence_health" | grep -q "healthy"; then
            echo -e "║  Florence-2: ${GREEN}● Running${NC}  (port $FLORENCE_PORT)                    ║"
        else
            echo -e "║  Florence-2: ${YELLOW}● Starting${NC} (port $FLORENCE_PORT)                    ║"
        fi
    else
        echo -e "║  Florence-2: ${RED}○ Stopped${NC}                                   ║"
    fi
    
    echo "╠══════════════════════════════════════════════════════════╣"
    
    # GPU status
    if command -v nvidia-smi &> /dev/null; then
        local gpu_mem=$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
        if [ -n "$gpu_mem" ]; then
            local used=$(echo "$gpu_mem" | cut -d',' -f1 | tr -d ' ')
            local total=$(echo "$gpu_mem" | cut -d',' -f2 | tr -d ' ')
            local percent=$((used * 100 / total))
            echo "║  GPU Memory: ${used}MiB / ${total}MiB (${percent}%)                  ║"
        fi
    fi
    
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
}

show_logs() {
    local service=${1:-all}
    
    case $service in
        vllm)
            docker logs -f "$VLLM_CONTAINER"
            ;;
        florence|florence2)
            docker logs -f "$FLORENCE_CONTAINER"
            ;;
        all|*)
            echo "=== vLLM logs (last 20 lines) ==="
            docker logs --tail 20 "$VLLM_CONTAINER" 2>/dev/null || echo "Container not running"
            echo ""
            echo "=== Florence-2 logs (last 20 lines) ==="
            docker logs --tail 20 "$FLORENCE_CONTAINER" 2>/dev/null || echo "Container not running"
            ;;
    esac
}

# ============================================================
# Health Check
# ============================================================

health_check() {
    echo ""
    echo "Performing health checks..."
    echo ""
    
    local all_healthy=true
    
    # vLLM health
    echo -n "vLLM: "
    if curl -s -f "http://localhost:${VLLM_PORT}/v1/models" > /dev/null 2>&1; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAIL${NC}"
        all_healthy=false
    fi
    
    # Florence-2 health
    echo -n "Florence-2: "
    local florence_resp=$(curl -s "http://localhost:${FLORENCE_PORT}/health" 2>/dev/null)
    if echo "$florence_resp" | grep -q "healthy"; then
        echo -e "${GREEN}OK${NC}"
        echo "  Model loaded: $(echo "$florence_resp" | grep -o '"model_loaded":[^,]*' | cut -d':' -f2)"
        echo "  GPU memory: $(echo "$florence_resp" | grep -o '"gpu_memory_gb":[^}]*' | cut -d':' -f2) GB"
    else
        echo -e "${RED}FAIL${NC}"
        all_healthy=false
    fi
    
    echo ""
    if $all_healthy; then
        log_success "All services healthy"
        return 0
    else
        log_error "Some services are unhealthy"
        return 1
    fi
}

# ============================================================
# Main
# ============================================================

print_usage() {
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  start     Start all services (vLLM first, then Florence-2)"
    echo "  stop      Stop all services"
    echo "  restart   Restart all services"
    echo "  status    Show service status"
    echo "  health    Perform health checks"
    echo "  logs      Show logs (use 'logs vllm' or 'logs florence' for specific)"
    echo "  clean     Stop and remove all containers"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 status"
    echo "  $0 logs vllm"
    echo "  $0 clean"
}

case "${1:-}" in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        start_all
        ;;
    status)
        show_status
        ;;
    health)
        health_check
        ;;
    logs)
        show_logs "${2:-all}"
        ;;
    clean)
        clean_all
        ;;
    *)
        print_usage
        exit 1
        ;;
esac
