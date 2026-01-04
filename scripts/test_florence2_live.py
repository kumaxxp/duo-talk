#!/usr/bin/env python3
"""
Florence-2 ライブテストスクリプト

実際にモデルをロードしてテスト画像で検出を実行。
A5000マシンで実行してください。
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))


def create_test_image():
    """テスト画像を生成"""
    from PIL import Image, ImageDraw

    # 640x480の道路風画像
    img = Image.new('RGB', (640, 480), color=(100, 100, 100))
    draw = ImageDraw.Draw(img)

    # 道路（中央）
    draw.polygon([(200, 480), (440, 480), (380, 200), (260, 200)], fill=(60, 60, 60))

    # 白線
    draw.line([(220, 480), (270, 200)], fill=(255, 255, 255), width=3)
    draw.line([(420, 480), (370, 200)], fill=(255, 255, 255), width=3)

    # コーン（右側）
    draw.polygon([(450, 400), (480, 400), (465, 350)], fill=(255, 128, 0))

    # 空
    draw.rectangle([(0, 0), (640, 200)], fill=(135, 206, 235))

    return img


def main():
    print("=" * 60)
    print("Florence-2 Live Test")
    print("=" * 60)

    # テスト画像生成
    print("\n1. Creating test image...")
    test_image = create_test_image()
    test_image.save("/tmp/test_road.png")
    print("   Saved to /tmp/test_road.png")

    # Florence-2 ロード
    print("\n2. Loading Florence-2...")
    from src.florence2_detector import get_florence2_detector, Florence2Detector

    # シングルトンリセット
    Florence2Detector._instance = None

    detector = get_florence2_detector()

    start = time.time()
    success = detector.load()
    load_time = time.time() - start

    if success:
        print(f"   [OK] Loaded in {load_time:.1f}s")
    else:
        print("   [FAIL] Failed to load")
        return

    # 物体検出
    print("\n3. Running object detection...")
    result = detector.detect(test_image, task="<OD>")

    print(f"   Processing time: {result.processing_time_ms:.0f}ms")
    print(f"   Objects detected: {len(result.objects)}")
    for obj in result.objects:
        print(f"     - {obj['label']}: {obj['position']}")

    # キャプション
    print("\n4. Getting caption...")
    caption_result = detector.detect(test_image, task="<CAPTION>")
    print(f"   Caption: {caption_result.caption}")

    # 詳細キャプション
    print("\n5. Getting detailed caption...")
    detailed_result = detector.detect(test_image, task="<DETAILED_CAPTION>")
    caption_text = detailed_result.caption[:200] if detailed_result.caption else "(no caption)"
    print(f"   Detailed: {caption_text}...")

    # 自動運転向け検出
    print("\n6. Running driving detection...")
    driving_result = detector.detect_for_driving(test_image)
    print(f"   Obstacles: {len(driving_result.get('obstacles', []))}")
    print(f"   Objects: {len(driving_result.get('objects', []))}")
    for obs in driving_result.get('obstacles', []):
        print(f"     - {obs['type']}: {obs['position']}, {obs.get('distance_estimate', '?')}")

    # アンロード
    print("\n7. Unloading model...")
    detector.unload()
    print("   [OK] Unloaded")

    # VRAM確認
    import torch
    if torch.cuda.is_available():
        vram_mb = torch.cuda.memory_allocated() / 1024**2
        print(f"   VRAM after unload: {vram_mb:.0f} MB")

    print("\n" + "=" * 60)
    print("[PASS] Florence-2 live test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
