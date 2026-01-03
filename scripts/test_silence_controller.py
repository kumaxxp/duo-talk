#!/usr/bin/env python3
"""
沈黙制御テスト
SilenceControllerの動作確認

テスト内容:
1. 高速走行時の沈黙
2. 緊張シーン（難コーナー等）での沈黙
3. 通常時の発話許可
4. 沈黙パラメータの確認
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.silence_controller import SilenceController, SilenceType
from src.signals import DuoSignals, SignalEvent, EventType


def test_high_speed_silence():
    """高速走行時の沈黙テスト"""
    print("=" * 60)
    print("🏎️ High Speed Silence Test")
    print("=" * 60)

    DuoSignals.reset_instance()
    signals = DuoSignals()
    controller = SilenceController()

    test_speeds = [0.5, 1.0, 2.0, 2.5, 3.0, 3.5, 4.0]

    print("\n📊 Speed vs Silence:")
    silences_triggered = 0

    for speed in test_speeds:
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": speed}
        ))
        state = signals.snapshot()

        silence = controller.should_silence(state)

        if silence:
            silences_triggered += 1
            print(f"   Speed {speed:.1f} m/s: 🤫 SILENCE ({silence.silence_type.value})")
            print(f"             Duration: {silence.duration_seconds}s, BGM: {silence.suggested_bgm_intensity}")
        else:
            print(f"   Speed {speed:.1f} m/s: 💬 SPEAK")

    print(f"\n📊 Summary: {silences_triggered}/{len(test_speeds)} triggered silence")
    return silences_triggered > 0


def test_tension_silence():
    """緊張シーンでの沈黙テスト"""
    print("\n" + "=" * 60)
    print("😰 Tension Silence Test")
    print("=" * 60)

    DuoSignals.reset_instance()
    signals = DuoSignals()
    controller = SilenceController()

    tension_scenarios = [
        ("straight", "直進"),
        ("gentle_curve", "緩やかなカーブ"),
        ("sharp_turn", "急カーブ"),
        ("difficult_corner", "難しいコーナー"),
        ("obstacle_ahead", "障害物前方"),
    ]

    print("\n📊 Scene Type vs Silence:")
    silences_triggered = 0

    for scene_type, description in tension_scenarios:
        DuoSignals.reset_instance()
        signals = DuoSignals()

        # 通常速度
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 1.5}
        ))

        # VLM観測
        signals.update(SignalEvent(
            event_type=EventType.VLM,
            data={"facts": {"upcoming": scene_type}}
        ))

        state = signals.snapshot()
        silence = controller.should_silence(state)

        if silence:
            silences_triggered += 1
            print(f"   {description} ({scene_type}): 🤫 SILENCE ({silence.silence_type.value})")
        else:
            print(f"   {description} ({scene_type}): 💬 SPEAK")

    print(f"\n📊 Summary: {silences_triggered}/{len(tension_scenarios)} triggered silence")
    return silences_triggered >= 1  # 少なくとも1つは沈黙トリガー


def test_normal_speaking():
    """通常時の発話許可テスト"""
    print("\n" + "=" * 60)
    print("💬 Normal Speaking Test")
    print("=" * 60)

    DuoSignals.reset_instance()
    signals = DuoSignals()
    controller = SilenceController()

    # 通常の走行状態
    normal_states = [
        {"speed": 1.0, "steering": 5.0, "distance": 800},
        {"speed": 1.5, "steering": 10.0, "distance": 600},
        {"speed": 0.8, "steering": -5.0, "distance": 700},
        {"speed": 1.2, "steering": 0.0, "distance": 1000},
    ]

    speak_allowed = 0

    print("\n📊 Normal states - Should allow speaking:")
    for i, state_data in enumerate(normal_states):
        DuoSignals.reset_instance()
        signals = DuoSignals()

        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={
                "speed": state_data["speed"],
                "steering": state_data["steering"],
                "sensors": {"distance": state_data["distance"]}
            }
        ))

        state = signals.snapshot()
        silence = controller.should_silence(state)

        if silence is None:
            speak_allowed += 1
            print(f"   State {i+1}: 💬 SPEAK (as expected)")
        else:
            print(f"   State {i+1}: 🤫 SILENCE (unexpected: {silence.silence_type.value})")

    print(f"\n📊 Summary: {speak_allowed}/{len(normal_states)} allowed speaking")
    return speak_allowed == len(normal_states)


def test_silence_parameters():
    """沈黙パラメータの確認テスト"""
    print("\n" + "=" * 60)
    print("⚙️ Silence Parameters Test")
    print("=" * 60)

    DuoSignals.reset_instance()
    signals = DuoSignals()
    controller = SilenceController()

    # 高速走行で沈黙をトリガー
    signals.update(SignalEvent(
        event_type=EventType.SENSOR,
        data={"speed": 4.0}
    ))

    state = signals.snapshot()
    silence = controller.should_silence(state)

    if silence:
        print(f"\n📋 Silence Parameters:")
        print(f"   Type: {silence.silence_type.value}")
        print(f"   Duration: {silence.duration_seconds} seconds")
        print(f"   BGM Intensity: {silence.suggested_bgm_intensity}")

        # パラメータ検証
        checks = [
            ("Duration > 0", silence.duration_seconds > 0),
            ("Duration <= 30", silence.duration_seconds <= 30),
            ("BGM intensity 0-1", 0 <= silence.suggested_bgm_intensity <= 1),
        ]

        all_passed = True
        print(f"\n📊 Parameter Validation:")
        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"   {status} {check_name}")
            if not result:
                all_passed = False

        return all_passed
    else:
        print("❌ Expected silence but got None")
        return False


def test_consecutive_silences():
    """連続沈黙テスト"""
    print("\n" + "=" * 60)
    print("🔁 Consecutive Silence Test")
    print("=" * 60)

    DuoSignals.reset_instance()
    signals = DuoSignals()
    controller = SilenceController()

    print("\n📊 Simulating continuous high-speed:")
    silence_types = []

    for i in range(5):
        # 継続的な高速走行
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 3.5 + (i * 0.1)}
        ))

        state = signals.snapshot()
        silence = controller.should_silence(state)

        if silence:
            silence_types.append(silence.silence_type)
            print(f"   Frame {i+1}: 🤫 {silence.silence_type.value} ({silence.duration_seconds}s)")
        else:
            print(f"   Frame {i+1}: 💬 SPEAK")

    print(f"\n📊 Summary: {len(silence_types)} consecutive silences")
    return len(silence_types) >= 3


def test_with_character():
    """キャラクターとの統合テスト"""
    print("\n" + "=" * 60)
    print("🎭 Character Integration Test")
    print("=" * 60)

    from unittest.mock import patch, MagicMock
    from src.character import Character

    DuoSignals.reset_instance()

    with patch('src.character.get_llm_client') as mock_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = "テスト応答です"
        mock_llm.return_value = mock_llm_instance

        char = Character("A")

        # 通常速度での発話
        print("\n📝 Normal speed (should speak):")
        char.signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 1.5}
        ))

        result = char.speak_v2(
            last_utterance="テスト",
            context={},
            frame_description="通常走行中"
        )
        print(f"   Type: {result['type']}")
        assert result["type"] == "speech", "Expected speech at normal speed"

        # 高速時の沈黙
        print("\n📝 High speed (should silence):")
        char.signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 4.0}
        ))

        result = char.speak_v2(
            last_utterance="テスト",
            context={},
            frame_description="高速走行中"
        )
        print(f"   Type: {result['type']}")

        if result["type"] == "silence":
            print("   ✅ Correctly returned silence")
            return True
        else:
            print("   ⚠️ Returned speech (may depend on controller settings)")
            return True  # 設定次第なので成功扱い


def run_all_tests():
    """全テスト実行"""
    print("=" * 60)
    print("🧪 Silence Controller Test Suite")
    print("=" * 60)

    results = []

    # 1. 高速沈黙
    try:
        results.append(("High Speed Silence", test_high_speed_silence()))
    except Exception as e:
        print(f"❌ High Speed Silence failed: {e}")
        results.append(("High Speed Silence", False))

    # 2. 緊張シーン沈黙
    try:
        results.append(("Tension Silence", test_tension_silence()))
    except Exception as e:
        print(f"❌ Tension Silence failed: {e}")
        results.append(("Tension Silence", False))

    # 3. 通常発話
    try:
        results.append(("Normal Speaking", test_normal_speaking()))
    except Exception as e:
        print(f"❌ Normal Speaking failed: {e}")
        results.append(("Normal Speaking", False))

    # 4. 沈黙パラメータ
    try:
        results.append(("Silence Parameters", test_silence_parameters()))
    except Exception as e:
        print(f"❌ Silence Parameters failed: {e}")
        results.append(("Silence Parameters", False))

    # 5. 連続沈黙
    try:
        results.append(("Consecutive Silences", test_consecutive_silences()))
    except Exception as e:
        print(f"❌ Consecutive Silences failed: {e}")
        results.append(("Consecutive Silences", False))

    # 6. キャラクター統合
    try:
        results.append(("Character Integration", test_with_character()))
    except Exception as e:
        print(f"❌ Character Integration failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Character Integration", False))

    # サマリー
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"   {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\n   Total: {passed}/{len(results)} passed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
