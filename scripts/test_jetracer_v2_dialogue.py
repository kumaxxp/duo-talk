#!/usr/bin/env python3
"""
JetRacer v2.1 対話生成テスト
- センサーデータからの対話生成
- speak_v2メソッドの動作確認
- SilenceController / NoveltyGuard の動作確認
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.jetracer_client import JetRacerClient
from src.jetracer_provider import JetRacerProvider, DataMode
from src.signals import DuoSignals, SignalEvent, EventType
from src.character import Character


def update_signals_from_jetracer(signals: DuoSignals, provider: JetRacerProvider):
    """JetRacerデータをDuoSignalsに反映"""
    full_state = provider.fetch()

    if not full_state.valid or full_state.sensor is None:
        return None, "センサーデータ取得失敗"

    sensor = full_state.sensor

    # センサーイベント
    signals.update(SignalEvent(
        event_type=EventType.SENSOR,
        data={
            "speed": abs(sensor.throttle) * 3.0,
            "steering": sensor.steering * 45,
            "sensors": {
                "distance": sensor.min_distance,
                "temperature": sensor.temperature,
                "accel_x": sensor.accel_x,
                "accel_y": sensor.accel_y
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

    # フレーム説明生成
    frame_desc = provider.to_frame_description(full_state)
    return full_state, frame_desc


def run_dialogue_test(url: str, turns: int = 4, interval: float = 3.0):
    """対話生成テスト実行"""
    print("=" * 60)
    print("🎬 JetRacer v2.1 Dialogue Test")
    print("=" * 60)

    # 初期化
    DuoSignals.reset_instance()
    signals = DuoSignals()
    provider = JetRacerProvider(JetRacerClient(url))

    print("\n📦 Loading characters...")
    char_a = Character("A")  # やな
    char_b = Character("B")  # あゆ
    print("✅ Characters loaded (using speak_v2)")

    # 会話履歴
    history = []

    print(f"\n🔄 Running {turns} turns (interval: {interval}s)")
    print("-" * 60)

    for turn in range(turns):
        # JetRacerデータ取得
        full_state, frame_desc = update_signals_from_jetracer(signals, provider)

        if full_state is None:
            print(f"⚠️  Turn {turn+1}: {frame_desc}")
            time.sleep(interval)
            continue

        print(f"\n📊 Turn {turn+1}")
        frame_preview = frame_desc[:80] if frame_desc else "(no frame)"
        print(f"   Frame: {frame_preview}...")

        # 話者選択（交互）
        if turn % 2 == 0:
            speaker = char_a
            speaker_name = "やな"
            other_name = "あゆ"
        else:
            speaker = char_b
            speaker_name = "あゆ"
            other_name = "やな"

        # 直前の発言を取得
        last_utterance = history[-1]["content"] if history else f"（{other_name}が画面を見ている）"

        # speak_v2で発言生成
        result = speaker.speak_v2(
            last_utterance=last_utterance,
            context={"history": history[-5:]},  # 直近5ターン
            frame_description=frame_desc or ""
        )

        # 結果表示
        if result["type"] == "speech":
            print(f"   👧 {speaker_name}: {result['content']}")

            # デバッグ情報
            debug = result.get("debug", {})
            if debug.get("loop_detected"):
                print(f"   ⚠️  ループ検知 → 戦略: {debug.get('strategy')}")
            if debug.get("unfilled_slots"):
                print(f"   📝 未充足スロット: {debug.get('unfilled_slots')}")
            if debug.get("few_shot_used"):
                print(f"   📋 Few-shot使用")

            # 履歴に追加
            history.append({
                "speaker": speaker_name,
                "content": result["content"]
            })

        elif result["type"] == "silence":
            silence_info = result["content"]
            silence_type = silence_info.get('silence_type', 'unknown') if isinstance(silence_info, dict) else 'unknown'
            print(f"   🤫 {speaker_name}: （沈黙 - {silence_type}）")

        time.sleep(interval)

    provider.close()

    print("\n" + "=" * 60)
    print("✅ Dialogue test completed!")
    print("=" * 60)

    # サマリー
    print("\n📊 Summary:")
    print(f"   Total turns: {len(history)}")
    for i, h in enumerate(history):
        content_preview = h['content'][:40] if len(h['content']) > 40 else h['content']
        print(f"   {i+1}. {h['speaker']}: {content_preview}...")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="JetRacer v2.1 Dialogue Test")
    parser.add_argument("--url", "-u", default="http://192.168.1.65:8000",
                        help="JetRacer API URL")
    parser.add_argument("--turns", "-t", type=int, default=4,
                        help="Number of dialogue turns")
    parser.add_argument("--interval", "-i", type=float, default=3.0,
                        help="Interval between turns (seconds)")
    args = parser.parse_args()

    try:
        run_dialogue_test(args.url, args.turns, args.interval)
        return 0
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
