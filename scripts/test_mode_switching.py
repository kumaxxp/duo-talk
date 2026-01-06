#!/usr/bin/env python3
"""
JetRacer/一般会話 モード切り替え統合テスト

テスト項目:
1. 一般会話モード: テキスト入力で実行し、一般会話用プロンプトが使われることを確認
2. JetRacerモード: JetRacerセンサー入力で実行し、JetRacer用プロンプトが使われることを確認
3. モード間の切り替え: 同一パイプラインでモードを切り替えて実行
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.unified_pipeline import UnifiedPipeline
from src.input_source import InputBundle, InputSource, SourceType
from src.character import Character


def test_general_conversation_mode():
    """一般会話モードの統合テスト"""
    print("\n" + "=" * 60)
    print("Test 1: 一般会話モード")
    print("=" * 60)

    pipeline = UnifiedPipeline(jetracer_mode=False)
    bundle = InputBundle(sources=[
        InputSource(source_type=SourceType.TEXT, content="今年の目標について話しましょう")
    ])

    result = pipeline.run(
        initial_input=bundle,
        max_turns=4,
    )

    print(f"\nStatus: {result.status}")
    print(f"Turns: {len(result.dialogue)}")
    print(f"Character A mode: {'JetRacer' if pipeline.char_a.jetracer_mode else 'General'}")
    print(f"Character B mode: {'JetRacer' if pipeline.char_b.jetracer_mode else 'General'}")

    print("\n--- 対話内容 ---")
    for turn in result.dialogue:
        speaker_name = "みう" if turn.speaker == "A" else "あゆ"
        print(f"[{speaker_name}] {turn.text[:80]}{'...' if len(turn.text) > 80 else ''}")

    # 検証
    assert result.status == "success", f"Expected success, got {result.status}"
    assert len(result.dialogue) == 4, f"Expected 4 turns, got {len(result.dialogue)}"
    assert pipeline.char_a.jetracer_mode is False, "Character A should be in general mode"
    assert pipeline.char_b.jetracer_mode is False, "Character B should be in general mode"

    print("\n[PASS] 一般会話モードテスト成功")
    return True


def test_jetracer_mode():
    """JetRacerモードの統合テスト"""
    print("\n" + "=" * 60)
    print("Test 2: JetRacerモード")
    print("=" * 60)

    pipeline = UnifiedPipeline(jetracer_mode=True)
    bundle = InputBundle(sources=[
        InputSource(source_type=SourceType.TEXT, content="走行中のセンサーデータを見てみよう"),
        InputSource(source_type=SourceType.JETRACER_SENSOR)
    ])

    result = pipeline.run(
        initial_input=bundle,
        max_turns=4,
    )

    print(f"\nStatus: {result.status}")
    print(f"Turns: {len(result.dialogue)}")
    print(f"Character A mode: {'JetRacer' if pipeline.char_a.jetracer_mode else 'General'}")
    print(f"Character B mode: {'JetRacer' if pipeline.char_b.jetracer_mode else 'General'}")

    print("\n--- 対話内容 ---")
    for turn in result.dialogue:
        speaker_name = "みう" if turn.speaker == "A" else "あゆ"
        print(f"[{speaker_name}] {turn.text[:80]}{'...' if len(turn.text) > 80 else ''}")

    # 検証
    assert result.status == "success", f"Expected success, got {result.status}"
    assert len(result.dialogue) == 4, f"Expected 4 turns, got {len(result.dialogue)}"
    assert pipeline.char_a.jetracer_mode is True, "Character A should be in JetRacer mode"
    assert pipeline.char_b.jetracer_mode is True, "Character B should be in JetRacer mode"

    print("\n[PASS] JetRacerモードテスト成功")
    return True


def test_mode_switching():
    """モード切り替えの統合テスト"""
    print("\n" + "=" * 60)
    print("Test 3: モード切り替え")
    print("=" * 60)

    # 1. 一般会話モードで開始
    pipeline = UnifiedPipeline(jetracer_mode=False)
    bundle1 = InputBundle(sources=[
        InputSource(source_type=SourceType.TEXT, content="最近の趣味は何？")
    ])

    print("\n[Phase 1] 一般会話モードで実行")
    result1 = pipeline.run(initial_input=bundle1, max_turns=2)

    print(f"Status: {result1.status}")
    print(f"Mode: {'JetRacer' if pipeline.char_a.jetracer_mode else 'General'}")
    for turn in result1.dialogue:
        speaker_name = "みう" if turn.speaker == "A" else "あゆ"
        print(f"[{speaker_name}] {turn.text[:60]}...")

    assert pipeline.char_a.jetracer_mode is False, "Phase 1: Should be general mode"

    # 2. JetRacerモードに切り替え
    print("\n[Phase 2] JetRacerモードに切り替えて実行")
    pipeline._jetracer_mode_override = True
    bundle2 = InputBundle(sources=[
        InputSource(source_type=SourceType.TEXT, content="センサーデータをチェックしよう")
    ])

    result2 = pipeline.run(initial_input=bundle2, max_turns=2)

    print(f"Status: {result2.status}")
    print(f"Mode: {'JetRacer' if pipeline.char_a.jetracer_mode else 'General'}")
    for turn in result2.dialogue:
        speaker_name = "みう" if turn.speaker == "A" else "あゆ"
        print(f"[{speaker_name}] {turn.text[:60]}...")

    assert pipeline.char_a.jetracer_mode is True, "Phase 2: Should be JetRacer mode"

    # 3. 一般会話モードに戻す
    print("\n[Phase 3] 一般会話モードに戻して実行")
    pipeline._jetracer_mode_override = False
    bundle3 = InputBundle(sources=[
        InputSource(source_type=SourceType.TEXT, content="今日の夕飯は何にする？")
    ])

    result3 = pipeline.run(initial_input=bundle3, max_turns=2)

    print(f"Status: {result3.status}")
    print(f"Mode: {'JetRacer' if pipeline.char_a.jetracer_mode else 'General'}")
    for turn in result3.dialogue:
        speaker_name = "みう" if turn.speaker == "A" else "あゆ"
        print(f"[{speaker_name}] {turn.text[:60]}...")

    assert pipeline.char_a.jetracer_mode is False, "Phase 3: Should be general mode again"

    print("\n[PASS] モード切り替えテスト成功")
    return True


def test_prompt_content_differs_by_mode():
    """モードによってプロンプト内容が異なることを確認"""
    print("\n" + "=" * 60)
    print("Test 4: プロンプト内容の違い確認")
    print("=" * 60)

    char_general = Character("A", jetracer_mode=False)
    char_jetracer = Character("A", jetracer_mode=True)

    general_reminder = "\n".join(char_general._get_tone_reminder())
    jetracer_reminder = "\n".join(char_jetracer._get_tone_reminder())

    print("\n[一般会話モードの口調リマインダー]")
    print(general_reminder[:200] + "..." if len(general_reminder) > 200 else general_reminder)

    print("\n[JetRacerモードの口調リマインダー]")
    print(jetracer_reminder[:200] + "..." if len(jetracer_reminder) > 200 else jetracer_reminder)

    # 内容が異なることを確認
    assert general_reminder != jetracer_reminder, "プロンプト内容はモードによって異なるべき"

    print("\n[PASS] プロンプト内容の違いを確認")
    return True


def main():
    """全テストを実行"""
    print("\n" + "=" * 60)
    print("JetRacer/一般会話 モード切り替え統合テスト")
    print("=" * 60)

    tests = [
        ("一般会話モード", test_general_conversation_mode),
        ("JetRacerモード", test_jetracer_mode),
        ("モード切り替え", test_mode_switching),
        ("プロンプト内容の違い", test_prompt_content_differs_by_mode),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"\n[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"統合テスト結果: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
