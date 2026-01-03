#!/usr/bin/env python3
"""
センサーシミュレーションテスト
実機を走行させずに様々なセンサー状況をシミュレート

シナリオ:
1. 通常走行（センサー値安定）
2. 障害物接近（距離センサー急減）
3. 高温警告（温度上昇）
4. センサー異常（値の乖離）
5. 高速走行（沈黙テスト）
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass
from typing import List, Dict, Any
from src.signals import DuoSignals, SignalEvent, EventType
from src.character import Character
from src.silence_controller import SilenceController


@dataclass
class SimulatedSensorState:
    """シミュレートするセンサー状態"""
    name: str
    speed: float
    steering: float
    distance: int
    temperature: float
    road_percentage: float
    scenario_description: str


# テストシナリオ定義
SCENARIOS: List[SimulatedSensorState] = [
    SimulatedSensorState(
        name="通常走行",
        speed=1.5, steering=5.0, distance=800,
        temperature=42.0, road_percentage=75.0,
        scenario_description="スロットル50%で直進中。温度42度。前方80cmに物体。走行可能領域75%。"
    ),
    SimulatedSensorState(
        name="右カーブ進入",
        speed=1.2, steering=25.0, distance=600,
        temperature=43.0, road_percentage=60.0,
        scenario_description="右カーブに進入。ステアリング25度。前方60cmに壁。走行可能領域60%。"
    ),
    SimulatedSensorState(
        name="障害物接近",
        speed=0.8, steering=0.0, distance=250,
        temperature=44.0, road_percentage=40.0,
        scenario_description="前方25cmに障害物接近！減速中。走行可能領域40%まで低下。"
    ),
    SimulatedSensorState(
        name="高温警告",
        speed=1.0, steering=-10.0, distance=700,
        temperature=58.0, road_percentage=70.0,
        scenario_description="温度58度で高め。左に微調整中。前方70cm。"
    ),
    SimulatedSensorState(
        name="高速走行",
        speed=3.2, steering=0.0, distance=1200,
        temperature=45.0, road_percentage=85.0,
        scenario_description="高速走行中！速度3.2m/s。前方クリア。走行可能領域85%。"
    ),
    SimulatedSensorState(
        name="緊急停止後",
        speed=0.0, steering=0.0, distance=150,
        temperature=50.0, road_percentage=30.0,
        scenario_description="緊急停止。前方15cmに障害物。走行可能領域30%。"
    ),
]


def update_signals_with_scenario(signals: DuoSignals, scenario: SimulatedSensorState):
    """シナリオに基づいてDuoSignalsを更新"""
    # センサーイベント
    signals.update(SignalEvent(
        event_type=EventType.SENSOR,
        data={
            "speed": scenario.speed,
            "steering": scenario.steering,
            "sensors": {
                "distance": scenario.distance,
                "temperature": scenario.temperature
            }
        }
    ))

    # VLM観測
    signals.update(SignalEvent(
        event_type=EventType.VLM,
        data={
            "facts": {
                "road_percentage": f"{scenario.road_percentage:.0f}%",
                "upcoming": "difficult_corner" if scenario.steering > 20 else "straight"
            }
        }
    ))


def run_scenario_test():
    """シナリオベーステスト実行"""
    print("=" * 60)
    print("🧪 Sensor Simulation Test")
    print("=" * 60)

    # 初期化
    DuoSignals.reset_instance()
    signals = DuoSignals()
    silence_controller = SilenceController()

    print("\n📦 Loading characters...")
    char_a = Character("A")
    char_b = Character("B")
    print("✅ Characters loaded")

    history = []
    silence_count = 0
    utterance_count = 0

    for i, scenario in enumerate(SCENARIOS):
        print(f"\n{'='*60}")
        print(f"📊 Scenario {i+1}: {scenario.name}")
        print(f"{'='*60}")
        print(f"   Speed: {scenario.speed} m/s")
        print(f"   Steering: {scenario.steering}°")
        print(f"   Distance: {scenario.distance}mm")
        print(f"   Temperature: {scenario.temperature}°C")
        print(f"   Road: {scenario.road_percentage}%")
        print(f"\n📝 {scenario.scenario_description}")

        # シグナル更新
        update_signals_with_scenario(signals, scenario)
        state = signals.snapshot()

        # 沈黙判定
        silence = silence_controller.should_silence(state)
        if silence:
            print(f"\n🤫 SilenceController: {silence.silence_type.value}")
            print(f"   Duration: {silence.duration_seconds}s")
            print(f"   BGM Intensity: {silence.suggested_bgm_intensity}")
            silence_count += 1
            continue  # 沈黙時は対話スキップ

        # 2ターンの対話
        print(f"\n💬 Dialogue:")
        for turn in range(2):
            speaker = char_a if turn == 0 else char_b
            speaker_name = "やな" if turn == 0 else "あゆ"
            other_name = "あゆ" if turn == 0 else "やな"

            last_utterance = history[-1]["content"] if history else f"（{other_name}がモニターを見ている）"

            result = speaker.speak_v2(
                last_utterance=last_utterance,
                context={"history": history[-3:]},
                frame_description=scenario.scenario_description
            )

            if result["type"] == "speech":
                print(f"   👧 {speaker_name}: {result['content']}")
                history.append({"speaker": speaker_name, "content": result["content"]})
                utterance_count += 1

                # デバッグ情報
                debug = result.get("debug", {})
                if debug.get("loop_detected"):
                    print(f"      ⚠️ ループ検知: {debug.get('strategy')}")
                if debug.get("unfilled_slots"):
                    print(f"      📝 未充足: {debug.get('unfilled_slots')}")

        time.sleep(0.5)  # API負荷軽減

    print(f"\n{'='*60}")
    print("✅ Scenario test completed!")
    print(f"   Total scenarios: {len(SCENARIOS)}")
    print(f"   Silence events: {silence_count}")
    print(f"   Total utterances: {utterance_count}")
    print("=" * 60)


if __name__ == "__main__":
    run_scenario_test()
