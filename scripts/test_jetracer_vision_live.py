"""
JetRacer Vision実況 ライブテスト

使用方法:
    # モックサーバーでテスト（Florence-2なし）
    python scripts/test_jetracer_vision_live.py --mock

    # モックサーバーでテスト（Florence-2あり）
    python scripts/test_jetracer_vision_live.py --mock --florence

    # 実機でテスト
    python scripts/test_jetracer_vision_live.py http://192.168.1.100:8000

    # カスタム間隔
    python scripts/test_jetracer_vision_live.py --mock --interval 3.0
"""
import sys
import argparse
import subprocess
import time
import threading
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def start_mock_server(port: int = 5000) -> subprocess.Popen:
    """モックサーバーを起動"""
    print(f"Starting mock JetRacer-Agent on port {port}...")
    mock_script = project_root / "scripts" / "mock_jetracer_agent.py"

    # バックグラウンドで起動
    proc = subprocess.Popen(
        [sys.executable, str(mock_script), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # 起動待ち
    time.sleep(2)

    if proc.poll() is not None:
        print("Mock server failed to start")
        stdout, stderr = proc.communicate()
        print(f"stdout: {stdout.decode()}")
        print(f"stderr: {stderr.decode()}")
        return None

    print(f"Mock server started (PID: {proc.pid})")
    return proc


def test_connection_only(url: str) -> bool:
    """接続テストのみ実行"""
    from src.jetracer_client import JetRacerClient

    print(f"\n{'='*60}")
    print("Connection Test")
    print(f"{'='*60}")
    print(f"URL: {url}")

    client = JetRacerClient(url)

    # ヘルスチェック
    print("\n1. Health check...")
    if client.health_check():
        print("   Health check passed")
    else:
        print("   Health check failed")
        return False

    # 画像取得
    print("\n2. Camera image fetch...")
    image = client.get_camera_image_pil()
    if image:
        print(f"   Image size: {image.size}")
    else:
        print("   Image fetch failed (may be OK for some JetRacer configs)")

    # センサーデータ
    print("\n3. Sensor data fetch...")
    sensors = client.get_sensor_data_simple()
    if sensors:
        print(f"   Sensors: {sensors}")
    else:
        print("   Sensor fetch failed (may be OK for some JetRacer configs)")

    # 車両状態
    print("\n4. Vehicle state fetch...")
    state = client.get_vehicle_state_simple()
    if state:
        print(f"   State: {state}")
    else:
        print("   State fetch failed (may be OK for some JetRacer configs)")

    print(f"\n{'='*60}")
    print("Connection Test Complete")
    print(f"{'='*60}")

    return True


def run_vision_loop(url: str, interval: float, max_cycles: int, load_florence: bool):
    """Vision実況ループを実行"""
    from src.vision_commentary_loop import VisionCommentaryLoop

    print(f"\n{'='*60}")
    print("Vision Commentary Loop")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Interval: {interval}s")
    print(f"Max cycles: {max_cycles if max_cycles > 0 else 'unlimited'}")
    print(f"Florence-2: {'enabled' if load_florence else 'disabled'}")
    print(f"{'='*60}")

    # コールバック関数
    results = []

    def callback(result):
        results.append(result)
        # WebSocket配信などはここで実装

    # ループ初期化
    loop = VisionCommentaryLoop(
        jetracer_url=url,
        interval_sec=interval,
        callback=callback,
        load_florence=load_florence
    )

    # 実行
    max_c = max_cycles if max_cycles > 0 else None
    loop.run(max_cycles=max_c)

    return results


def main():
    parser = argparse.ArgumentParser(description="JetRacer Vision Live Test")
    parser.add_argument("url", nargs="?", default="http://localhost:5000",
                        help="JetRacer-Agent URL (default: http://localhost:5000)")
    parser.add_argument("--mock", action="store_true",
                        help="Start mock JetRacer-Agent server")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Commentary interval in seconds (default: 5.0)")
    parser.add_argument("--cycles", type=int, default=3,
                        help="Max cycles to run (0 for unlimited, default: 3)")
    parser.add_argument("--florence", action="store_true",
                        help="Load Florence-2 for real detection")
    parser.add_argument("--connection-only", action="store_true",
                        help="Only test connection, skip commentary loop")
    parser.add_argument("--port", type=int, default=5000,
                        help="Mock server port (default: 5000)")

    args = parser.parse_args()

    mock_proc = None

    try:
        # モックサーバー起動
        if args.mock:
            mock_proc = start_mock_server(args.port)
            if mock_proc is None:
                print("Failed to start mock server")
                return 1
            args.url = f"http://localhost:{args.port}"

        # 接続テストのみ
        if args.connection_only:
            success = test_connection_only(args.url)
            return 0 if success else 1

        # Vision実況ループ
        results = run_vision_loop(
            url=args.url,
            interval=args.interval,
            max_cycles=args.cycles,
            load_florence=args.florence
        )

        # 結果サマリー
        if results:
            print(f"\n{'='*60}")
            print("Sample Outputs")
            print(f"{'='*60}")
            for i, r in enumerate(results[:3], 1):
                print(f"\n--- Cycle {r.cycle_number} ---")
                print(f"[やな] {r.yana_comment}")
                print(f"[あゆ] {r.ayu_comment}")
                print(f"Vision: {r.vision_data}")
                print(f"Total time: {sum(r.timing.values()):.2f}s")

        return 0

    finally:
        # モックサーバー停止
        if mock_proc:
            print("\nStopping mock server...")
            mock_proc.terminate()
            mock_proc.wait(timeout=5)
            print("Mock server stopped")


if __name__ == "__main__":
    sys.exit(main())
