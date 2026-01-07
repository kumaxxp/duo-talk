#!/usr/bin/env python3
"""
Florence-2 Docker Service Test Script

Tests:
1. Direct server test (without Docker)
2. Docker service test
3. Client API test

Usage:
    # Test direct server (requires transformers==4.49.0)
    python scripts/test_florence2_service.py --direct
    
    # Test Docker service
    python scripts/test_florence2_service.py --docker
    
    # Test with specific image
    python scripts/test_florence2_service.py --docker --image path/to/image.jpg
"""

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_docker_service(url: str, image_path: str = None):
    """Test Florence-2 Docker service"""
    from src.florence2_client import Florence2Client
    
    print("=" * 60)
    print("Florence-2 Docker Service Test")
    print("=" * 60)
    print(f"URL: {url}")
    
    client = Florence2Client(url, timeout=120.0)
    
    # Health check
    print("\n1. Health Check")
    health = client.health()
    print(f"   Status: {health.get('status')}")
    print(f"   Model Loaded: {health.get('model_loaded')}")
    print(f"   Device: {health.get('device')}")
    print(f"   GPU Memory: {health.get('gpu_memory_gb')} GB")
    
    if not client.is_ready():
        print("\n⚠️  Service not ready. Waiting...")
        if client.wait_until_ready(timeout=180):
            print("✅ Service is now ready")
        else:
            print("❌ Service did not become ready in time")
            return False
    
    # List tasks
    print("\n2. Available Tasks")
    tasks = client.list_tasks()
    print(f"   {tasks}")
    
    # Test inference
    if image_path:
        print(f"\n3. Testing with image: {image_path}")
        
        # Caption
        print("\n   [Caption]")
        start = time.time()
        result = client.caption(image_path)
        elapsed = (time.time() - start) * 1000
        if result.success:
            print(f"   Result: {result.text}")
            print(f"   Server time: {result.processing_time_ms:.1f}ms")
            print(f"   Total time: {elapsed:.1f}ms")
        else:
            print(f"   ❌ Error: {result.error}")
        
        # Detailed caption
        print("\n   [Detailed Caption]")
        result = client.caption(image_path, detailed=True)
        if result.success:
            print(f"   Result: {result.text[:200]}...")
            print(f"   Time: {result.processing_time_ms:.1f}ms")
        else:
            print(f"   ❌ Error: {result.error}")
        
        # Object detection
        print("\n   [Object Detection]")
        result = client.detect_objects(image_path)
        if result.success:
            print(f"   Objects: {result.objects[:10]}")  # First 10
            print(f"   Bboxes: {len(result.bboxes)} found")
            print(f"   Time: {result.processing_time_ms:.1f}ms")
        else:
            print(f"   ❌ Error: {result.error}")
        
        # Dense caption
        print("\n   [Dense Region Caption]")
        result = client.dense_caption(image_path)
        if result.success:
            print(f"   Regions: {len(result.objects)}")
            if result.objects:
                print(f"   Sample: {result.objects[0]}")
            print(f"   Time: {result.processing_time_ms:.1f}ms")
        else:
            print(f"   ❌ Error: {result.error}")
        
        # OCR
        print("\n   [OCR]")
        result = client.ocr(image_path)
        if result.success:
            text = result.text
            print(f"   Text: {text[:100] if text else '(no text found)'}...")
            print(f"   Time: {result.processing_time_ms:.1f}ms")
        else:
            print(f"   ❌ Error: {result.error}")
    
    else:
        print("\n3. Inference test skipped (no image provided)")
        print("   Use --image path/to/image.jpg to test inference")
    
    client.close()
    print("\n" + "=" * 60)
    print("✅ Docker service test complete")
    print("=" * 60)
    return True


def test_direct_server():
    """Test Florence-2 server directly (without Docker)"""
    print("=" * 60)
    print("Florence-2 Direct Server Test")
    print("=" * 60)
    
    # Check transformers version
    try:
        import transformers
        print(f"Transformers version: {transformers.__version__}")
        if transformers.__version__ != "4.49.0":
            print(f"⚠️  Warning: transformers {transformers.__version__} may not be compatible")
            print("   Recommended: transformers==4.49.0")
    except ImportError:
        print("❌ transformers not installed")
        return False
    
    # Check torch
    try:
        import torch
        print(f"PyTorch version: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    except ImportError:
        print("❌ torch not installed")
        return False
    
    # Test model loading
    print("\nTesting model loading (this may take a while)...")
    
    try:
        from unittest.mock import patch
        from transformers.dynamic_module_utils import get_imports
        from transformers import AutoModelForCausalLM, AutoProcessor
        
        def fixed_get_imports(filename: str):
            if not str(filename).endswith("modeling_florence2.py"):
                return get_imports(filename)
            imports = get_imports(filename)
            if "flash_attn" in imports:
                imports.remove("flash_attn")
            return imports
        
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        
        start = time.time()
        with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports):
            model = AutoModelForCausalLM.from_pretrained(
                "microsoft/Florence-2-large",
                attn_implementation="sdpa",
                torch_dtype=dtype,
                trust_remote_code=True,
            ).to(device)
        
        processor = AutoProcessor.from_pretrained(
            "microsoft/Florence-2-large",
            trust_remote_code=True,
        )
        
        load_time = time.time() - start
        print(f"✅ Model loaded in {load_time:.1f}s")
        
        if torch.cuda.is_available():
            mem = torch.cuda.memory_allocated() / 1024**3
            print(f"✅ GPU memory used: {mem:.2f} GB")
        
        # Cleanup
        del model
        del processor
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        print("\n✅ Direct server test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="Test Florence-2 service")
    parser.add_argument("--direct", action="store_true", help="Test direct server (without Docker)")
    parser.add_argument("--docker", action="store_true", help="Test Docker service")
    parser.add_argument("--url", default="http://localhost:5001", help="Florence-2 API URL")
    parser.add_argument("--image", help="Test image path")
    
    args = parser.parse_args()
    
    if not args.direct and not args.docker:
        print("Please specify --direct or --docker")
        parser.print_help()
        sys.exit(1)
    
    success = True
    
    if args.direct:
        success = test_direct_server() and success
    
    if args.docker:
        success = test_docker_service(args.url, args.image) and success
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
