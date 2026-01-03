#!/usr/bin/env python3
"""
v2.1 Live Commentary Test
JetRacer実機に接続してライブ対話をテスト
"""
import sys
import os
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.signals import DuoSignals, SignalEvent, EventType
from src.character import Character
from src.silence_controller import SilenceController
from src.novelty_guard import NoveltyGuard
from src.jetracer_client import JetRacerClient
from src.jetracer_provider import JetRacerProvider, DataMode


def run_live_test(
    jetracer_url: str = "http://192.168.1.65:8000",
    turns: int = 10,
    interval: float = 3.0,
    mode: str = "vision"
):
    """ライブ対話テスト実行"""
    print("=" * 60)
    print("Live Commentary Test v2.1")
    print("=" * 60)
    print(f"   JetRacer URL: {jetracer_url}")
    print(f"   Mode: {mode}")
    print(f"   Turns: {turns}")
    print(f"   Interval: {interval}s")
    print("=" * 60)

    # 初期化
    print("\nInitializing...")
    DuoSignals.reset_instance()
    signals = DuoSignals()
    silence_controller = SilenceController()
    novelty_guard = NoveltyGuard()

    char_a = Character("A")
    char_b = Character("B")
    print("   Characters loaded")

    # JetRacer接続
    print(f"\nConnecting to JetRacer...")
    try:
        client = JetRacerClient(jetracer_url, timeout=5.0)
        status = client.get_status()
        if not status:
            print("   Connection failed")
            return False
        print(f"   Connected")
        print(f"   Mode: {status.get('mode', 'unknown')}")
    except Exception as e:
        print(f"   Error: {e}")
        return False

    # Provider作成
    data_mode = DataMode.VISION if mode == "vision" else DataMode.SENSOR_ONLY
    provider = JetRacerProvider(client, data_mode)

    # 対話ループ
    history = []
    stats = {
        "total_turns": 0,
        "silences": 0,
        "loop_detections": 0,
        "errors": 0
    }

    print(f"\nStarting live commentary ({turns} turns)...")
    print("-" * 60)

    try:
        for turn_idx in range(turns):
            print(f"\n[Turn {turn_idx + 1}/{turns}]")

            # センサーデータ取得
            try:
                full_state = provider.fetch()
                if not full_state.valid or full_state.sensor is None:
                    print("   Sensor data unavailable")
                    stats["errors"] += 1
                    time.sleep(interval)
                    continue

                sensor = full_state.sensor

                # DuoSignals更新
                signals.update(SignalEvent(
                    event_type=EventType.SENSOR,
                    data={
                        "speed": abs(sensor.throttle) * 3.0,
                        "steering": sensor.steering * 45,
                        "sensors": {
                            "distance": sensor.min_distance,
                            "temperature": sensor.temperature
                        }
                    }
                ))

                # VLM観測（VISIONモード時）
                if full_state.vision and full_state.vision.road_percentage > 0:
                    signals.update(SignalEvent(
                        event_type=EventType.VLM,
                        data={
                            "facts": {
                                "road_percentage": f"{full_state.vision.road_percentage:.0f}%",
                                "inference_time": f"{full_state.vision.inference_time_ms:.0f}ms"
                            }
                        }
                    ))

                frame_desc = provider.to_frame_description(full_state)
                print(f"   Frame: {frame_desc[:60]}...")

            except Exception as e:
                print(f"   Fetch error: {e}")
                stats["errors"] += 1
                time.sleep(interval)
                continue

            # 沈黙チェック
            state = signals.snapshot()
            silence = silence_controller.should_silence(state)
            if silence:
                print(f"   Silence: {silence.silence_type.value} ({silence.duration_seconds}s)")
                stats["silences"] += 1
                time.sleep(silence.duration_seconds)
                continue

            # 対話生成（2ターン）
            for sub_turn in range(2):
                speaker = char_a if sub_turn == 0 else char_b
                speaker_name = "yana" if sub_turn == 0 else "ayu"

                last_utterance = history[-1]["content"] if history else "(watching screen)"

                result = speaker.speak_v2(
                    last_utterance=last_utterance,
                    context={"history": history[-5:]},
                    frame_description=frame_desc
                )

                if result["type"] == "speech":
                    content = result["content"]
                    print(f"   {speaker_name}: {content}")

                    history.append({
                        "speaker": speaker_name,
                        "content": content,
                        "timestamp": datetime.now().isoformat()
                    })
                    stats["total_turns"] += 1

                    # デバッグ情報
                    debug = result.get("debug", {})
                    if debug.get("loop_detected"):
                        print(f"      Loop: {debug.get('strategy')}")
                        stats["loop_detections"] += 1

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")

    # サマリー
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"   Total turns: {stats['total_turns']}")
    print(f"   Silences: {stats['silences']}")
    print(f"   Loop detections: {stats['loop_detections']}")
    print(f"   Errors: {stats['errors']}")
    print(f"   History length: {len(history)}")

    if history:
        print(f"\nSample dialogue (last 4):")
        for h in history[-4:]:
            print(f"   {h['speaker']}: {h['content'][:50]}...")

    print("=" * 60)
    return True


def main():
    parser = argparse.ArgumentParser(description="v2.1 Live Commentary Test")
    parser.add_argument("--url", "-u", default="http://192.168.1.65:8000",
                       help="JetRacer API URL")
    parser.add_argument("--turns", "-t", type=int, default=10,
                       help="Number of turn cycles")
    parser.add_argument("--interval", "-i", type=float, default=3.0,
                       help="Interval between cycles (seconds)")
    parser.add_argument("--mode", "-m", choices=["sensor_only", "vision"],
                       default="vision", help="Data mode")
    args = parser.parse_args()

    success = run_live_test(
        jetracer_url=args.url,
        turns=args.turns,
        interval=args.interval,
        mode=args.mode
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
