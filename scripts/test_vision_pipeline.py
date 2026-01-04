#!/usr/bin/env python3
"""
Vision Pipeline テストスクリプト

VLM + Florence-2 パイプラインの統合テスト。
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))


def create_test_image():
    """テスト画像を生成"""
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (640, 480), color=(100, 100, 100))
    draw = ImageDraw.Draw(img)

    # 道路
    draw.polygon([(200, 480), (440, 480), (380, 200), (260, 200)], fill=(60, 60, 60))
    draw.line([(220, 480), (270, 200)], fill=(255, 255, 255), width=3)
    draw.line([(420, 480), (370, 200)], fill=(255, 255, 255), width=3)

    # コーン
    draw.polygon([(450, 400), (480, 400), (465, 350)], fill=(255, 128, 0))

    # 空
    draw.rectangle([(0, 0), (640, 200)], fill=(135, 206, 235))

    return img


def main():
    print("=" * 60)
    print("Vision Pipeline Test")
    print("=" * 60)

    from src.vision_pipeline import (
        get_vision_pipeline,
        VisionPipelineConfig,
        VisionMode
    )

    # テスト画像
    print("\n1. Creating test image...")
    test_image = create_test_image()

    # 各モードでテスト
    modes = [
        (VisionMode.VLM_ONLY, "VLM Only"),
        (VisionMode.FLORENCE_ONLY, "Florence Only"),
        (VisionMode.VLM_WITH_FLORENCE, "VLM + Florence"),
    ]

    for mode, name in modes:
        print(f"\n{'=' * 40}")
        print(f"Testing: {name}")
        print("=" * 40)

        try:
            config = VisionPipelineConfig(
                mode=mode,
                florence_enabled=True,
                florence_auto_unload=True,
            )

            # パイプラインをリセット
            import src.vision_pipeline as vp
            vp._pipeline = None

            pipeline = get_vision_pipeline(config)

            start = time.time()
            result = pipeline.process(test_image, mode=mode)
            elapsed = time.time() - start

            print(f"Processing time: {result.get('processing_time_ms', 0):.0f}ms (total: {elapsed:.1f}s)")

            if result.get("error"):
                print(f"[FAIL] Error: {result['error']}")
            else:
                print("[OK] Success")

                if result.get("description"):
                    desc = result['description'][:100] if result['description'] else ""
                    print(f"Description: {desc}...")

                if result.get("obstacles"):
                    print(f"Obstacles: {len(result['obstacles'])}")
                    for obs in result["obstacles"][:3]:
                        print(f"  - {obs}")

                if result.get("road_info"):
                    print(f"Road info: {result['road_info']}")

        except Exception as e:
            print(f"[FAIL] Exception: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("[PASS] Vision Pipeline test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
