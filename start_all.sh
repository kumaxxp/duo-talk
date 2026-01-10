#!/bin/bash
#
# DUO-TALK Completel Launcher
# Starts Docker services (LLM/Vision) AND the GUI System
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "════════════════════════════════════════════════════════════════════════════"
echo "🚀 DUO-TALK COMPLETE LAUNCHER"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# 1. Start Docker Services
echo -e "${BLUE}【Step 1/2】 Starting AI Engine (Docker)...${NC}"
./scripts/docker_services.sh start

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}⚠️  Docker services failed to start correctly.${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}✅ AI Engine is ready!${NC}"
echo ""

# 2. Start GUI System
echo -e "${BLUE}【Step 2/2】 Starting GUI System...${NC}"
./start_gui.sh
