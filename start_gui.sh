#!/bin/bash
#
# DUO-TALK GUI + Backend Launcher
# Starts both the React frontend and Flask backend API server
#

set -e

# Process IDs
BACKEND_PID=""
FRONTEND_PID=""

# Cleanup function - called on Ctrl+C or exit
cleanup() {
    echo ""
    echo -e "\n${YELLOW}⏹️  Shutting down services...${NC}"

    # Kill backend
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "   Stopping Backend (PID: $BACKEND_PID)..."
        kill "$BACKEND_PID" 2>/dev/null || true
    fi

    # Kill frontend
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "   Stopping Frontend (PID: $FRONTEND_PID)..."
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi

    # Kill any remaining processes
    pkill -f "python.*api_server.py" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true

    echo -e "${GREEN}✅ All services stopped${NC}"
    exit 0
}

# Trap SIGINT (Ctrl+C) and SIGTERM
trap cleanup SIGINT SIGTERM EXIT

echo "════════════════════════════════════════════════════════════════════════════"
echo "🚀 DUO-TALK GUI + Backend Launcher"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}📍 Project root: $PROJECT_ROOT${NC}"
echo ""

# --- Attempt to activate conda environment 'duo-talk' ---
echo -e "${BLUE}【Conda Environment】${NC}"
if command -v conda &> /dev/null; then
    # initialize conda for this shell and try to activate
    eval "$(conda shell.bash hook)"
    if conda activate duo-talk 2>/dev/null; then
        echo -e "${GREEN}✅ Activated conda environment 'duo-talk'${NC}"
    else
        echo -e "${YELLOW}⚠️  Conda present but environment 'duo-talk' not found or activation failed.${NC}"
        echo -e "${YELLOW}You can create it with: conda env create -f environment.yml or conda create -n duo-talk python=3.x${NC}"
    fi
else
    # Try common install locations
    if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        . "$HOME/miniconda3/etc/profile.d/conda.sh"
        conda activate duo-talk 2>/dev/null && echo -e "${GREEN}✅ Activated conda environment 'duo-talk'${NC}" || echo -e "${YELLOW}⚠️ Failed to activate 'duo-talk' from miniconda.${NC}"
    elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        . "$HOME/anaconda3/etc/profile.d/conda.sh"
        conda activate duo-talk 2>/dev/null && echo -e "${GREEN}✅ Activated conda environment 'duo-talk'${NC}" || echo -e "${YELLOW}⚠️ Failed to activate 'duo-talk' from anaconda.${NC}"
    else
        echo -e "${YELLOW}⚠️ Conda not found in PATH and no common installations detected.${NC}"
        echo -e "${YELLOW}If you want automatic activation, ensure conda is installed and 'conda' is on PATH.${NC}"
    fi
fi


# Check if Node.js and npm are installed
echo -e "${BLUE}【Checking Prerequisites】${NC}"

if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}❌ Node.js not found. Please install Node.js 18+${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Node.js: $(node --version)${NC}"

if ! command -v npm &> /dev/null; then
    echo -e "${YELLOW}❌ npm not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ npm: $(npm --version)${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}❌ Python 3 not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python: $(python3 --version)${NC}"

echo ""

# Setup frontend
echo -e "${BLUE}【Setting up Frontend】${NC}"
cd duo-gui

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    npm install
else
    echo -e "${GREEN}✅ Dependencies already installed${NC}"
fi

echo ""

# Setup backend
echo -e "${BLUE}【Setting up Backend】${NC}"
cd "$PROJECT_ROOT"

# Check if Flask and flask-cors are installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo -e "${YELLOW}Installing Flask...${NC}"
    pip install flask flask-cors
else
    echo -e "${GREEN}✅ Flask already installed${NC}"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# Start services
echo -e "${BLUE}【Starting Services】${NC}"
echo ""

# Backend API server
echo -e "${GREEN}🔧 Starting Backend API Server...${NC}"
export FLASK_PORT=5000
python3 server/api_server.py > server.log 2>&1 &
BACKEND_PID=$!
echo "   PID: $BACKEND_PID"
echo -e "${GREEN}   Backend running on http://localhost:5000${NC}"
echo ""

sleep 2

# Frontend development server
echo -e "${GREEN}🎨 Starting Frontend (Vite)...${NC}"
cd duo-gui
npm run dev > frontend.log 2>&1 &
FRONTEND_PID=$!
echo "   PID: $FRONTEND_PID"
echo ""

# Wait a moment for Vite to start
sleep 3

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo -e "${GREEN}✅ DUO-TALK GUI System is Running!${NC}"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "📌 Frontend (React):    http://localhost:5173"
echo "📌 Backend API:         http://localhost:5000"
echo "📌 v2.1 API Endpoints:"
echo "     - GET  /api/v2/signals          (DuoSignals状態)"
echo "     - GET  /api/v2/novelty/status   (NoveltyGuard状態)"
echo "     - GET  /api/v2/silence/check    (沈黙判定)"
echo "     - POST /api/v2/jetracer/connect (JetRacer接続)"
echo "     - GET  /api/v2/jetracer/fetch   (センサー取得)"
echo "     - POST /api/v2/live/dialogue    (対話生成)"
echo "     - GET  /api/v2/provider/status  (LLM/Docker状態)"
echo "     - POST /api/v2/provider/switch  (バックエンド切替)"
echo "     - GET  /api/ollama/models       (Ollamaモデル一覧)"
echo ""
echo "💡 Press Ctrl+C to stop all services"
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# Wait for both processes
wait
