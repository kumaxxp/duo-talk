"""
モックJetRacer-Agent（テスト用）

実機がない環境でVision実況システムをテストするためのモックサーバー。
ランダムな画像とセンサーデータを返す。

使用方法:
    python scripts/mock_jetracer_agent.py [port]

デフォルトポート: 5000
"""
import io
import random
import sys
from datetime import datetime

from flask import Flask, send_file, jsonify
from PIL import Image, ImageDraw

app = Flask(__name__)

# グローバル状態（テスト用にシナリオを変更可能）
SCENARIO = {
    "objects": ["cone", "car", "road_line", "barrier", "person"],
    "modes": ["SENSOR_ONLY", "VISION", "FULL_AUTONOMY"],
    "frame_count": 0
}


@app.route('/health')
def health():
    """ヘルスチェックエンドポイント"""
    return jsonify({
        "status": "ok",
        "service": "mock-jetracer-agent",
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/camera/capture')
def camera_capture():
    """ダミーカメラ画像を生成"""
    SCENARIO["frame_count"] += 1

    # 640x480のダミー画像（道路っぽい背景）
    img = Image.new('RGB', (640, 480), color=(80, 80, 80))  # グレーの道路
    draw = ImageDraw.Draw(img)

    # 道路の白線
    draw.line([(200, 480), (280, 200)], fill="white", width=3)
    draw.line([(440, 480), (360, 200)], fill="white", width=3)

    # 空（上部）
    for y in range(150):
        shade = 150 + y // 2
        draw.line([(0, y), (640, y)], fill=(shade, shade + 30, shade + 50))

    # ランダムな物体を1-3個描画
    num_objects = random.randint(1, 3)
    detected_objects = []

    for i in range(num_objects):
        obj = random.choice(SCENARIO["objects"])
        detected_objects.append(obj)

        # ランダムな位置
        x1 = random.randint(50, 500)
        y1 = random.randint(150, 350)
        w = random.randint(40, 120)
        h = random.randint(40, 100)

        # 物体の色
        colors = {
            "cone": (255, 140, 0),  # オレンジ
            "car": (0, 100, 200),   # 青
            "road_line": (255, 255, 255),  # 白
            "barrier": (255, 0, 0),  # 赤
            "person": (0, 200, 100)  # 緑
        }
        color = colors.get(obj, (200, 200, 200))

        # 矩形描画
        draw.rectangle([x1, y1, x1 + w, y1 + h], outline=color, width=3)
        draw.rectangle([x1, y1, x1 + w, y1 + h], fill=color + (100,))

        # ラベル
        try:
            draw.text((x1, y1 - 15), obj, fill=color)
        except Exception:
            pass

    # フレーム番号
    draw.text((10, 10), f"Frame: {SCENARIO['frame_count']}", fill="white")
    draw.text((10, 30), f"Objects: {', '.join(detected_objects)}", fill="white")

    # 画像をバイトストリームに変換
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG', quality=85)
    img_bytes.seek(0)

    return send_file(img_bytes, mimetype='image/jpeg')


@app.route('/api/sensors')
def sensors():
    """ダミーセンサーデータを生成"""
    # ランダムなセンサー値（リアルな範囲）
    return jsonify({
        "distance_front": round(random.uniform(0.3, 2.5), 2),
        "distance_left": round(random.uniform(0.2, 1.5), 2),
        "distance_right": round(random.uniform(0.2, 1.5), 2),
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/state')
def state():
    """ダミー車両状態を生成"""
    return jsonify({
        "speed": round(random.uniform(0.0, 2.5), 2),
        "steering": round(random.uniform(-0.5, 0.5), 2),
        "mode": random.choice(SCENARIO["modes"]),
        "battery": round(random.uniform(70, 100), 1),
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/scenario', methods=['GET'])
def get_scenario():
    """現在のシナリオ設定を取得"""
    return jsonify(SCENARIO)


@app.route('/api/scenario/reset', methods=['POST'])
def reset_scenario():
    """シナリオをリセット"""
    SCENARIO["frame_count"] = 0
    return jsonify({"status": "reset", "frame_count": 0})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

    print("=" * 60)
    print("  Mock JetRacer-Agent")
    print("=" * 60)
    print(f"Starting on http://0.0.0.0:{port}")
    print(f"Health check: http://localhost:{port}/health")
    print(f"Camera: http://localhost:{port}/api/camera/capture")
    print(f"Sensors: http://localhost:{port}/api/sensors")
    print(f"State: http://localhost:{port}/api/state")
    print("=" * 60)
    print("Press Ctrl+C to stop")
    print()

    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
