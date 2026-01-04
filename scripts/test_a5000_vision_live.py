#!/usr/bin/env python3
"""
A5000 Vision Pipeline ライブテスト

Florence-2 + VLM パイプラインの実機動作確認。
JetRacerカメラ画像を使った統合テストも実施。

使用方法:
    python scripts/test_a5000_vision_live.py [OPTIONS]

Options:
    --skip-florence    Florence-2テストをスキップ
    --skip-vlm         VLMテストをスキップ
    --skip-pipeline    Pipelineテストをスキップ
    --jetracer URL     JetRacerから画像を取得してテスト
    --image PATH       指定した画像でテスト
"""
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")


def print_subheader(text: str):
    print(f"\n{Colors.CYAN}--- {text} ---{Colors.RESET}")


def print_success(text: str):
    print(f"{Colors.GREEN}[OK] {text}{Colors.RESET}")


def print_error(text: str):
    print(f"{Colors.RED}[FAIL] {text}{Colors.RESET}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.RESET}")


def print_info(text: str):
    print(f"{Colors.BLUE}[INFO] {text}{Colors.RESET}")


def create_test_image():
    """テスト用の道路画像を生成"""
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (640, 480), color=(100, 100, 100))
    draw = ImageDraw.Draw(img)

    # 道路（中央）
    draw.polygon([(200, 480), (440, 480), (380, 200), (260, 200)], fill=(60, 60, 60))

    # 白線（左右）
    draw.line([(220, 480), (270, 200)], fill=(255, 255, 255), width=4)
    draw.line([(420, 480), (370, 200)], fill=(255, 255, 255), width=4)

    # 中央線（点線）
    for y in range(200, 480, 40):
        draw.line([(320, y), (320, min(y + 20, 480))], fill=(255, 255, 0), width=2)

    # コーン（右側）- オレンジ色の三角
    draw.polygon([(480, 380), (520, 380), (500, 320)], fill=(255, 100, 0))
    draw.polygon([(485, 375), (515, 375), (500, 325)], fill=(255, 140, 0))

    # 障害物（左側）- 茶色のボックス
    draw.rectangle([(120, 350), (180, 400)], fill=(139, 90, 43))

    # 空
    draw.rectangle([(0, 0), (640, 200)], fill=(135, 206, 235))

    # 太陽
    draw.ellipse([(50, 30), (100, 80)], fill=(255, 255, 0))

    return img


def fetch_jetracer_image(url: str) -> Optional[bytes]:
    """JetRacerから画像を取得"""
    import requests

    try:
        # カメラ画像エンドポイント
        image_url = f"{url}/camera/image"
        response = requests.get(image_url, timeout=10)

        if response.status_code == 200:
            return response.content
        else:
            print_warning(f"Failed to fetch image: HTTP {response.status_code}")
            return None
    except Exception as e:
        print_warning(f"Failed to connect to JetRacer: {e}")
        return None


def check_gpu_status():
    """GPU状態を確認"""
    import torch

    print_subheader("GPU Status")

    if not torch.cuda.is_available():
        print_error("CUDA not available")
        return False

    device_name = torch.cuda.get_device_name(0)
    total_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
    allocated = torch.cuda.memory_allocated(0) / 1024**3
    reserved = torch.cuda.memory_reserved(0) / 1024**3

    print_info(f"Device: {device_name}")
    print_info(f"Total VRAM: {total_memory:.1f} GB")
    print_info(f"Allocated: {allocated:.2f} GB")
    print_info(f"Reserved: {reserved:.2f} GB")
    print_info(f"Free: {total_memory - reserved:.1f} GB")

    return True


def test_florence2(image, auto_unload: bool = True) -> Dict[str, Any]:
    """Florence-2テスト"""
    print_header("Florence-2 Test")

    from src.florence2_detector import (
        get_florence2_detector,
        Florence2Detector,
        Florence2Config
    )

    results: Dict[str, Any] = {
        "load_time": 0,
        "detection_time": 0,
        "objects": [],
        "caption": "",
        "driving_result": {},
        "error": None,
    }

    try:
        # シングルトンリセット
        Florence2Detector._instance = None

        # 設定
        config = Florence2Config(
            model_name="microsoft/Florence-2-large",
            device="cuda",
            attn_implementation="eager",  # flash-attn不要
        )

        detector = get_florence2_detector(config)

        # ロード
        print_subheader("Loading Model")
        start = time.time()
        success = detector.load()
        results["load_time"] = time.time() - start

        if not success:
            results["error"] = "Failed to load model"
            print_error(results["error"])
            return results

        print_success(f"Loaded in {results['load_time']:.1f}s")

        # VRAM確認
        import torch
        vram_gb = torch.cuda.memory_allocated() / 1024**3
        print_info(f"VRAM after load: {vram_gb:.2f} GB")

        # Object Detection
        print_subheader("Object Detection (<OD>)")
        start = time.time()
        od_result = detector.detect(image, task="<OD>")
        results["detection_time"] = time.time() - start

        print_info(f"Processing time: {od_result.processing_time_ms:.0f}ms")
        print_info(f"Objects detected: {len(od_result.objects)}")

        for obj in od_result.objects[:10]:
            print(f"    - {obj['label']}: {obj['position']} ({obj['size']['width']:.2f}x{obj['size']['height']:.2f})")

        results["objects"] = od_result.objects

        # Caption
        print_subheader("Caption (<CAPTION>)")
        caption_result = detector.detect(image, task="<CAPTION>")
        results["caption"] = caption_result.caption
        print_info(f"Caption: {caption_result.caption}")

        # Detailed Caption
        print_subheader("Detailed Caption")
        detailed_result = detector.detect(image, task="<DETAILED_CAPTION>")
        caption_text = detailed_result.caption[:150] if detailed_result.caption else "(no caption)"
        print_info(f"Detailed: {caption_text}...")

        # Driving Detection
        print_subheader("Driving Detection")
        driving_result = detector.detect_for_driving(image)
        results["driving_result"] = driving_result

        print_info(f"Obstacles: {len(driving_result.get('obstacles', []))}")
        for obs in driving_result.get("obstacles", []):
            print(f"    - {obs['type']}: {obs['position']}, distance={obs.get('distance_estimate', '?')}")

        print_info(f"Objects: {len(driving_result.get('objects', []))}")

        # アンロード
        if auto_unload:
            print_subheader("Unloading Model")
            detector.unload()

            import torch
            torch.cuda.empty_cache()
            vram_gb = torch.cuda.memory_allocated() / 1024**3
            print_info(f"VRAM after unload: {vram_gb:.2f} GB")
            print_success("Model unloaded")

        print_success("Florence-2 test passed!")

    except Exception as e:
        results["error"] = str(e)
        print_error(f"Florence-2 test failed: {e}")
        import traceback
        traceback.print_exc()

    return results


def test_vlm(image) -> Dict[str, Any]:
    """VLMテスト"""
    print_header("VLM Test")

    from src.llm_provider import get_llm_provider
    import base64
    import io
    from PIL import Image

    results: Dict[str, Any] = {
        "backend": "",
        "model": "",
        "response": "",
        "processing_time": 0,
        "error": None,
    }

    try:
        provider = get_llm_provider()
        status = provider.get_status()

        results["backend"] = status["current_backend"]
        results["model"] = status["current_model"]

        print_info(f"Backend: {results['backend']}")
        print_info(f"Model: {results['model']}")

        # 画像をBase64に変換
        if isinstance(image, Image.Image):
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        else:
            image_b64 = base64.b64encode(image).decode("utf-8")

        # VLM呼び出し
        print_subheader("VLM Analysis")
        client = provider.get_client()
        model_name = provider.get_model_name()

        prompt = """この画像は自動運転ロボットのカメラ映像です。
以下を簡潔に報告してください：
1. 路面状態
2. 障害物の位置
3. 走行可能な領域"""

        start = time.time()
        response = client.chat.completions.create(
            model=model_name,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{image_b64}"
                    }}
                ]
            }],
            max_tokens=300,
            temperature=0.3,
        )
        results["processing_time"] = time.time() - start

        results["response"] = response.choices[0].message.content or ""

        print_info(f"Processing time: {results['processing_time']:.1f}s")
        print(f"\n{Colors.CYAN}VLM Response:{Colors.RESET}")
        print(results["response"])

        print_success("VLM test passed!")

    except Exception as e:
        results["error"] = str(e)
        print_error(f"VLM test failed: {e}")
        import traceback
        traceback.print_exc()

    return results


def test_vision_pipeline(image, modes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Vision Pipelineテスト"""
    print_header("Vision Pipeline Test")

    from src.vision_pipeline import (
        get_vision_pipeline,
        VisionPipelineConfig,
        VisionMode
    )
    import src.vision_pipeline as vp
    from src.florence2_detector import Florence2Detector

    results: Dict[str, Any] = {
        "modes_tested": [],
        "results": {},
        "error": None,
    }

    if modes is None:
        modes = ["vlm_only", "florence_only", "vlm_with_florence"]

    mode_map = {
        "vlm_only": VisionMode.VLM_ONLY,
        "florence_only": VisionMode.FLORENCE_ONLY,
        "vlm_with_florence": VisionMode.VLM_WITH_FLORENCE,
        "florence_then_llm": VisionMode.FLORENCE_THEN_LLM,
    }

    for mode_name in modes:
        if mode_name not in mode_map:
            continue

        mode = mode_map[mode_name]
        print_subheader(f"Mode: {mode_name}")

        try:
            # パイプラインをリセット
            vp._pipeline = None
            Florence2Detector._instance = None

            config = VisionPipelineConfig(
                mode=mode,
                florence_enabled=True,
                florence_auto_unload=True,
            )

            pipeline = get_vision_pipeline(config)

            start = time.time()
            result = pipeline.process(image, mode=mode)
            elapsed = time.time() - start

            results["modes_tested"].append(mode_name)
            results["results"][mode_name] = result

            print_info(f"Processing time: {result.get('processing_time_ms', 0):.0f}ms (total: {elapsed:.1f}s)")

            if result.get("error"):
                print_error(f"Error: {result['error']}")
            else:
                print_success(f"Mode {mode_name} passed")

                if result.get("description"):
                    desc_text = result["description"]
                    desc = desc_text[:150] + "..." if len(desc_text) > 150 else desc_text
                    print(f"    Description: {desc}")

                if result.get("obstacles"):
                    print(f"    Obstacles: {len(result['obstacles'])}")

                if result.get("road_info"):
                    print(f"    Road info: {result['road_info']}")

            # VRAM確認
            import torch
            if torch.cuda.is_available():
                vram_gb = torch.cuda.memory_allocated() / 1024**3
                print_info(f"VRAM: {vram_gb:.2f} GB")

        except Exception as e:
            print_error(f"Mode {mode_name} failed: {e}")
            results["results"][mode_name] = {"error": str(e)}
            import traceback
            traceback.print_exc()

    return results


def test_with_jetracer(url: str) -> Dict[str, Any]:
    """JetRacer画像でテスト"""
    print_header("JetRacer Integration Test")

    from PIL import Image
    import io

    results: Dict[str, Any] = {
        "jetracer_url": url,
        "image_fetched": False,
        "pipeline_result": {},
        "error": None,
    }

    try:
        # 画像取得
        print_subheader("Fetching Image from JetRacer")
        image_bytes = fetch_jetracer_image(url)

        if image_bytes is None:
            results["error"] = "Failed to fetch image"
            print_error(results["error"])
            return results

        results["image_fetched"] = True
        print_success(f"Image fetched: {len(image_bytes)} bytes")

        # PIL Imageに変換
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        print_info(f"Image size: {image.size}")

        # 保存
        image.save("/tmp/jetracer_test.png")
        print_info("Saved to /tmp/jetracer_test.png")

        # VLM + Florenceでテスト
        from src.vision_pipeline import (
            get_vision_pipeline,
            VisionPipelineConfig,
            VisionMode
        )
        import src.vision_pipeline as vp
        from src.florence2_detector import Florence2Detector

        vp._pipeline = None
        Florence2Detector._instance = None

        config = VisionPipelineConfig(
            mode=VisionMode.VLM_WITH_FLORENCE,
            florence_enabled=True,
            florence_auto_unload=True,
        )

        pipeline = get_vision_pipeline(config)

        print_subheader("Processing with VLM + Florence")
        start = time.time()
        result = pipeline.process(image, mode=VisionMode.VLM_WITH_FLORENCE)
        elapsed = time.time() - start

        results["pipeline_result"] = result

        print_info(f"Processing time: {result.get('processing_time_ms', 0):.0f}ms (total: {elapsed:.1f}s)")

        if result.get("error"):
            print_error(f"Error: {result['error']}")
        else:
            print_success("JetRacer integration test passed!")

            print(f"\n{Colors.CYAN}Scene Analysis:{Colors.RESET}")
            if result.get("description"):
                print(result["description"][:300])

            if result.get("obstacles"):
                print(f"\nObstacles detected: {len(result['obstacles'])}")
                for obs in result["obstacles"][:5]:
                    print(f"  - {obs}")

    except Exception as e:
        results["error"] = str(e)
        print_error(f"JetRacer test failed: {e}")
        import traceback
        traceback.print_exc()

    return results


def main():
    parser = argparse.ArgumentParser(
        description="A5000 Vision Pipeline Live Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic test (synthetic image)
  python scripts/test_a5000_vision_live.py

  # Florence-2 only
  python scripts/test_a5000_vision_live.py --skip-vlm --skip-pipeline

  # VLM only
  python scripts/test_a5000_vision_live.py --skip-florence --skip-pipeline

  # JetRacer integration
  python scripts/test_a5000_vision_live.py --jetracer http://192.168.1.65:8000

  # Test with specific image
  python scripts/test_a5000_vision_live.py --image /path/to/image.jpg
"""
    )
    parser.add_argument("--skip-florence", action="store_true", help="Skip Florence-2 test")
    parser.add_argument("--skip-vlm", action="store_true", help="Skip VLM test")
    parser.add_argument("--skip-pipeline", action="store_true", help="Skip Pipeline test")
    parser.add_argument("--jetracer", type=str, help="JetRacer URL (e.g., http://192.168.1.65:8000)")
    parser.add_argument("--image", type=str, help="Path to test image")

    args = parser.parse_args()

    print_header("A5000 Vision Pipeline Live Test")
    print(f"Start time: {datetime.now().isoformat()}")

    # GPU確認
    if not check_gpu_status():
        print_error("GPU check failed, aborting")
        sys.exit(1)

    # テスト画像の準備
    if args.image:
        from PIL import Image
        print_info(f"Using image: {args.image}")
        test_image = Image.open(args.image).convert("RGB")
    else:
        print_info("Creating synthetic test image")
        test_image = create_test_image()
        test_image.save("/tmp/test_road_synthetic.png")
        print_info("Saved to /tmp/test_road_synthetic.png")

    all_results: Dict[str, Any] = {}

    # Florence-2テスト
    if not args.skip_florence:
        all_results["florence2"] = test_florence2(test_image, auto_unload=True)

    # VLMテスト
    if not args.skip_vlm:
        all_results["vlm"] = test_vlm(test_image)

    # Pipelineテスト
    if not args.skip_pipeline:
        all_results["pipeline"] = test_vision_pipeline(test_image)

    # JetRacerテスト
    if args.jetracer:
        all_results["jetracer"] = test_with_jetracer(args.jetracer)

    # サマリー
    print_header("Test Summary")

    passed = 0
    failed = 0

    for test_name, result in all_results.items():
        if result.get("error"):
            print_error(f"{test_name}: FAILED - {result['error']}")
            failed += 1
        else:
            print_success(f"{test_name}: PASSED")
            passed += 1

    print(f"\nTotal: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print(f"End time: {datetime.now().isoformat()}")

    # 最終VRAM状態
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        vram_gb = torch.cuda.memory_allocated() / 1024**3
        print_info(f"Final VRAM: {vram_gb:.2f} GB")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
