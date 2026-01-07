#!/usr/bin/env python3
"""
duo-talk Startup Script

Ensures all Docker services are running before starting the application.

Usage:
    python scripts/start_duo_talk.py [--mode jetracer|general]
"""

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_dependencies():
    """Check if required dependencies are available"""
    missing = []
    
    try:
        import httpx
    except ImportError:
        missing.append("httpx")
    
    try:
        import docker
    except ImportError:
        # docker package is optional, we use subprocess
        pass
    
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        return False
    
    return True


def ensure_services():
    """Ensure Docker services are running"""
    from src.docker_manager import DockerServiceManager, ServiceState
    
    print("=" * 60)
    print("Checking Docker services...")
    print("=" * 60)
    print()
    
    with DockerServiceManager() as manager:
        status = manager.status()
        
        # Check current status
        vllm_running = status["vllm"].state == ServiceState.RUNNING
        florence_running = status["florence"].state == ServiceState.RUNNING
        
        if vllm_running and florence_running:
            print("✅ All services are already running")
            manager.print_status()
            return True
        
        # Need to start services
        if not vllm_running:
            print("vLLM is not running, starting...")
        if not florence_running:
            print("Florence-2 is not running, starting...")
        
        print()
        print("Starting services (this may take 2-5 minutes)...")
        print()
        
        if manager.ensure_running():
            print()
            print("✅ All services started successfully!")
            manager.print_status()
            return True
        else:
            print()
            print("❌ Failed to start services")
            print()
            print("Troubleshooting:")
            print("1. Check GPU availability: nvidia-smi")
            print("2. Check Docker: docker ps")
            print("3. Check logs: docker logs duo-talk-vllm")
            print("4. Try manual start: ./scripts/docker_services.sh start")
            return False


def test_connections():
    """Test connections to all services"""
    from src.florence2_client import Florence2Client
    from openai import OpenAI
    
    print()
    print("=" * 60)
    print("Testing service connections...")
    print("=" * 60)
    print()
    
    success = True
    
    # Test Florence-2
    print("Testing Florence-2...", end=" ")
    try:
        client = Florence2Client("http://localhost:5001")
        if client.is_ready():
            print("✅ OK")
        else:
            print("❌ Not ready")
            success = False
        client.close()
    except Exception as e:
        print(f"❌ Error: {e}")
        success = False
    
    # Test vLLM
    print("Testing vLLM...", end=" ")
    try:
        client = OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")
        models = client.models.list()
        if models.data:
            print(f"✅ OK ({models.data[0].id})")
        else:
            print("❌ No models")
            success = False
    except Exception as e:
        print(f"❌ Error: {e}")
        success = False
    
    return success


def main():
    parser = argparse.ArgumentParser(description="Start duo-talk with Docker services")
    parser.add_argument("--mode", choices=["jetracer", "general"], default="general",
                       help="Operating mode (default: general)")
    parser.add_argument("--skip-services", action="store_true",
                       help="Skip Docker service startup check")
    parser.add_argument("--test-only", action="store_true",
                       help="Only test connections, don't start application")
    
    args = parser.parse_args()
    
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║              duo-talk Startup                            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Ensure Docker services are running
    if not args.skip_services:
        if not ensure_services():
            sys.exit(1)
    
    # Test connections
    if not test_connections():
        print()
        print("⚠️  Some services are not responding correctly")
        if not args.test_only:
            print("Continuing anyway...")
    
    if args.test_only:
        print()
        print("Test complete. Exiting.")
        sys.exit(0)
    
    # Start the application
    print()
    print("=" * 60)
    print(f"Starting duo-talk in {args.mode} mode...")
    print("=" * 60)
    print()
    
    # Import and run the main application
    # TODO: Integrate with actual duo-talk main script
    print("Ready to run duo-talk!")
    print()
    print("Available commands:")
    print("  python -m src.main_gui           # Start NiceGUI interface")
    print("  python scripts/run_commentary.py # Run commentary mode")
    print()


if __name__ == "__main__":
    main()
