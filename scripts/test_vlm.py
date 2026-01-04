#!/usr/bin/env python3
"""
VLM (Vision Language Model) テストスクリプト
単独実行用
"""
import sys
import base64
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image
except ImportError:
    print("Installing Pillow...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image

from src.llm_provider import get_llm_provider


def create_test_image():
    """テスト画像を生成（赤青縞模様）"""
    img = Image.new('RGB', (100, 100))
    pixels = img.load()

    for y in range(100):
        for x in range(100):
            if (x // 20) % 2 == 0:
                pixels[x, y] = (255, 0, 0)
            else:
                pixels[x, y] = (0, 0, 255)

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def main():
    print("=" * 60)
    print("VLM Test - Image Input")
    print("=" * 60)

    provider = get_llm_provider()
    client = provider.get_client()
    model_name = provider.get_model_name()

    print(f"\nModel: {model_name}")

    print("\nGenerating test image...")
    test_image_b64 = create_test_image()
    print(f"Image size: {len(test_image_b64)} bytes (base64)")

    print("\nCalling VLM API...")
    response = client.chat.completions.create(
        model=model_name,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe the colors and pattern in this image."},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{test_image_b64}"
                }}
            ]
        }],
        max_tokens=200
    )

    print("\n" + "=" * 60)
    print("VLM Response:")
    print("=" * 60)
    print(response.choices[0].message.content)
    print("\n[PASS] VLM test completed!")


if __name__ == "__main__":
    main()
