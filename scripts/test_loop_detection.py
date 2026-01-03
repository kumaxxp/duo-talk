#!/usr/bin/env python3
"""
ループ検知テスト
NoveltyGuardの動作確認と戦略ローテーションのテスト

テスト内容:
1. 同一トピック連続発言でループ検知
2. 戦略ローテーション確認
3. ループ脱出パターンの検証
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.novelty_guard import NoveltyGuard, LoopBreakStrategy
from src.signals import DuoSignals


def test_basic_loop_detection():
    """基本的なループ検知テスト（同一テキスト繰り返し）"""
    print("=" * 60)
    print("🔄 Basic Loop Detection Test")
    print("=" * 60)

    guard = NoveltyGuard()

    # 同一テキストを繰り返す（NoveltyGuardはハッシュベース）
    repeated_utterance = "センサーの値を確認しました"

    loop_detected_count = 0
    strategies_used = []

    print("\n📝 Repeating identical text:")
    for i in range(6):
        result = guard.check_and_update(repeated_utterance)

        print(f"   Turn {i+1}: loop={result.loop_detected}", end="")

        if result.loop_detected:
            loop_detected_count += 1
            print(f", strategy={result.strategy.value}")
            strategies_used.append(result.strategy)
        else:
            print()

    print(f"\n📊 Summary:")
    print(f"   Total utterances: 6")
    print(f"   Loops detected: {loop_detected_count}")
    print(f"   Strategies used: {[s.value for s in strategies_used]}")

    # 3回目以降でループ検知されるはず
    return loop_detected_count >= 2


def test_strategy_rotation():
    """戦略ローテーションテスト"""
    print("\n" + "=" * 60)
    print("🔄 Strategy Rotation Test")
    print("=" * 60)

    guard = NoveltyGuard()

    # 強制的にループを発生させる
    strategies_observed = []

    for i in range(10):
        # 同じ内容を繰り返す
        result = guard.check_and_update("同じセンサー確認です")

        if result.loop_detected and result.strategy != LoopBreakStrategy.NOOP:
            strategies_observed.append(result.strategy)
            print(f"   Turn {i+1}: {result.strategy.value}")

    # 戦略の多様性を確認
    unique_strategies = set(strategies_observed)
    print(f"\n📊 Unique strategies observed: {len(unique_strategies)}")
    for s in unique_strategies:
        count = strategies_observed.count(s)
        print(f"   {s.value}: {count} times")

    return len(unique_strategies) >= 2


def test_topic_change_resets():
    """トピック変更によるリセットテスト"""
    print("\n" + "=" * 60)
    print("🔄 Topic Change Reset Test")
    print("=" * 60)

    guard = NoveltyGuard()

    # センサートピックで3回発言
    print("\n📝 Phase 1: Sensor topic")
    for i in range(3):
        result = guard.check_and_update(f"センサー確認中 {i+1}")
        print(f"   Turn {i+1}: loop={result.loop_detected}")

    # トピック変更
    print("\n📝 Phase 2: Speed topic (topic change)")
    for i in range(3):
        result = guard.check_and_update(f"速度が上がってきた {i+1}")
        print(f"   Turn {i+1}: loop={result.loop_detected}")

    # 再びセンサートピックに戻る
    print("\n📝 Phase 3: Back to sensor topic")
    for i in range(3):
        result = guard.check_and_update(f"センサー値チェック {i+1}")
        print(f"   Turn {i+1}: loop={result.loop_detected}")

    print("\n✅ Topic change test completed")
    return True


def test_with_character():
    """キャラクターとの統合テスト"""
    print("\n" + "=" * 60)
    print("🔄 Character Integration Test")
    print("=" * 60)

    from unittest.mock import patch, MagicMock
    from src.character import Character

    DuoSignals.reset_instance()

    with patch('src.character.get_llm_client') as mock_llm:
        # モックLLMが同じような返答を返すようにする
        mock_llm_instance = MagicMock()
        responses = [
            "センサー値を確認しました",
            "センサーは正常です",
            "センサーデータ良好です",
            "センサー確認OK",
            "やっぱり速度を上げたい",  # トピック変更
        ]
        mock_llm_instance.call.side_effect = responses
        mock_llm.return_value = mock_llm_instance

        char = Character("A")

        print("\n💬 Simulating character responses:")
        for i, expected in enumerate(responses):
            result = char.speak_v2(
                last_utterance="テスト発言",
                context={},
                frame_description="テストフレーム"
            )

            debug = result.get("debug", {})
            loop_detected = debug.get("loop_detected", False)
            strategy = debug.get("strategy", "none")

            content_preview = result["content"][:30] if result["content"] else "(empty)"
            print(f"   Turn {i+1}: \"{content_preview}...\"")
            print(f"           loop={loop_detected}, strategy={strategy}")

    print("\n✅ Character integration test completed")
    return True


def run_all_tests():
    """全テスト実行"""
    print("=" * 60)
    print("🧪 Loop Detection Test Suite")
    print("=" * 60)

    results = []

    # 1. 基本ループ検知
    try:
        results.append(("Basic Loop Detection", test_basic_loop_detection()))
    except Exception as e:
        print(f"❌ Basic Loop Detection failed: {e}")
        results.append(("Basic Loop Detection", False))

    # 2. 戦略ローテーション
    try:
        results.append(("Strategy Rotation", test_strategy_rotation()))
    except Exception as e:
        print(f"❌ Strategy Rotation failed: {e}")
        results.append(("Strategy Rotation", False))

    # 3. トピック変更リセット
    try:
        results.append(("Topic Change Reset", test_topic_change_resets()))
    except Exception as e:
        print(f"❌ Topic Change Reset failed: {e}")
        results.append(("Topic Change Reset", False))

    # 4. キャラクター統合
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
