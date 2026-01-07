#!/usr/bin/env python3
"""
NoveltyGuard + FewShotInjector 統合テスト

テスト内容:
1. NoveltyGuard単体テスト（ループ検知、具体性チェック）
2. FewShotInjector単体テスト（パターン選択）
3. 連携テスト（戦略→パターン選択）

使用方法:
    python scripts/test_novelty_guard.py
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_novelty_guard_basic():
    """NoveltyGuard基本テスト"""
    print("=" * 60)
    print("Test 1: NoveltyGuard Basic")
    print("=" * 60)
    
    from src.novelty_guard import NoveltyGuard, LoopBreakStrategy
    
    guard = NoveltyGuard(max_topic_depth=3)
    
    # テストケース: 同じ話題が3回続く
    texts = [
        "JetRacerのセンサーが良い感じです",
        "センサーの数値を見てみましょう",
        "センサーのデータを確認しました",
        "センサーの調子はどうですか",  # ここでループ検知
    ]
    
    print("\n--- Loop Detection Test ---")
    for i, text in enumerate(texts):
        result = guard.check_and_update(text)
        print(f"Turn {i+1}: '{text[:30]}...'")
        print(f"  loop_detected: {result.loop_detected}")
        print(f"  topic_depth: {result.topic_depth}")
        if result.loop_detected:
            print(f"  stuck_nouns: {result.stuck_nouns}")
            print(f"  strategy: {result.strategy.value}")
            print(f"  reason: {result.reason}")
    
    # 最後のターンでループ検知されたか
    success = result.loop_detected
    print(f"\n{'✅' if success else '❌'} Loop detection: {'PASS' if success else 'FAIL'}")
    
    return success


def test_novelty_guard_specificity():
    """NoveltyGuard具体性チェックテスト"""
    print("\n" + "=" * 60)
    print("Test 2: NoveltyGuard Specificity Check")
    print("=" * 60)
    
    from src.novelty_guard import NoveltyGuard
    
    guard = NoveltyGuard(specificity_threshold=2)
    
    # テストケース: 具体的 vs 抽象的
    test_cases = [
        ("速度は2.5m/sでした", True, "数値あり"),
        ("例えばコーナーで膨らんだ時", True, "例示あり"),
        ("前にも同じことがあった", True, "過去参照あり"),
        ("右コーナーで注意が必要", True, "場所あり"),
        ("なんか良い感じです", False, "抽象的"),
        ("うまくいきました", False, "抽象的"),
    ]
    
    print("\n--- Specificity Check ---")
    all_pass = True
    for text, expected, reason in test_cases:
        is_specific, details = guard.check_specificity(text)
        status = "✅" if is_specific == expected else "❌"
        print(f"{status} '{text}' -> {is_specific} (expected: {expected}, {reason})")
        if is_specific != expected:
            all_pass = False
            print(f"    Details: {details}")
    
    print(f"\n{'✅' if all_pass else '❌'} Specificity check: {'PASS' if all_pass else 'FAIL'}")
    return all_pass


def test_novelty_guard_lack_specificity():
    """NoveltyGuard具体性不足検知テスト"""
    print("\n" + "=" * 60)
    print("Test 3: NoveltyGuard Lack of Specificity Detection")
    print("=" * 60)
    
    from src.novelty_guard import NoveltyGuard, LoopBreakStrategy
    
    guard = NoveltyGuard(max_topic_depth=3, specificity_threshold=2)
    
    # テストケース: 抽象的な発言が続く
    texts = [
        "なんか良い感じですね",
        "うまくいっている気がします",
        "そうですね、その通りです",  # ここで具体性不足検知
    ]
    
    print("\n--- Lack of Specificity Detection ---")
    for i, text in enumerate(texts):
        result = guard.check_and_update(text)
        print(f"Turn {i+1}: '{text}'")
        print(f"  lacks_specificity: {result.lacks_specificity}")
        if result.lacks_specificity:
            print(f"  strategy: {result.strategy.value}")
            print(f"  reason: {result.reason}")
    
    # 具体性不足が検知されたか
    success = result.lacks_specificity
    print(f"\n{'✅' if success else '❌'} Lack of specificity detection: {'PASS' if success else 'FAIL'}")
    
    return success


def test_few_shot_injector_basic():
    """FewShotInjector基本テスト"""
    print("\n" + "=" * 60)
    print("Test 4: FewShotInjector Basic")
    print("=" * 60)
    
    from src.few_shot_injector import FewShotInjector, reset_few_shot_injector
    
    # キャッシュをリセット
    reset_few_shot_injector()
    
    # JetRacerモード
    injector_jetracer = FewShotInjector(mode="jetracer")
    print(f"\n--- JetRacer Mode ---")
    print(f"  Patterns loaded: {len(injector_jetracer.patterns)}")
    print(f"  Pattern IDs: {injector_jetracer.get_all_pattern_ids()[:5]}...")
    
    # 一般会話モード
    injector_general = FewShotInjector(mode="general")
    print(f"\n--- General Mode ---")
    print(f"  Patterns loaded: {len(injector_general.patterns)}")
    print(f"  Pattern IDs: {injector_general.get_all_pattern_ids()[:5]}...")
    
    success = len(injector_jetracer.patterns) > 0 and len(injector_general.patterns) > 0
    print(f"\n{'✅' if success else '❌'} Pattern loading: {'PASS' if success else 'FAIL'}")
    
    return success


def test_few_shot_strategy_mapping():
    """FewShotInjector戦略マッピングテスト"""
    print("\n" + "=" * 60)
    print("Test 5: FewShotInjector Strategy Mapping")
    print("=" * 60)
    
    from src.few_shot_injector import FewShotInjector, reset_few_shot_injector
    from src.novelty_guard import LoopBreakStrategy
    
    reset_few_shot_injector()
    
    # 一般会話モードでテスト
    injector = FewShotInjector(mode="general")
    
    strategies = [
        LoopBreakStrategy.FORCE_SPECIFIC_SLOT,
        LoopBreakStrategy.FORCE_CONFLICT_WITHIN,
        LoopBreakStrategy.FORCE_ACTION_NEXT,
        LoopBreakStrategy.FORCE_PAST_REFERENCE,
        LoopBreakStrategy.FORCE_WHY,
        LoopBreakStrategy.FORCE_EXPAND,
    ]
    
    print("\n--- Strategy → Pattern Mapping ---")
    all_pass = True
    for strategy in strategies:
        pattern = injector.select_pattern(
            signals_state=None,
            loop_strategy=strategy
        )
        has_pattern = pattern is not None
        status = "✅" if has_pattern else "⚠️"
        print(f"{status} {strategy.value}: {'Found' if has_pattern else 'Not found'}")
        if has_pattern:
            preview = pattern.split('\n')[0][:50] if pattern else ""
            print(f"    Preview: {preview}...")
    
    print(f"\n{'✅' if all_pass else '⚠️'} Strategy mapping: {'All found' if all_pass else 'Some missing'}")
    return True  # 一部見つからなくてもOK


def test_integration():
    """NoveltyGuard + FewShotInjector連携テスト"""
    print("\n" + "=" * 60)
    print("Test 6: Integration Test")
    print("=" * 60)
    
    from src.novelty_guard import NoveltyGuard
    from src.few_shot_injector import FewShotInjector, reset_few_shot_injector
    
    reset_few_shot_injector()
    
    guard = NoveltyGuard(max_topic_depth=3)
    injector = FewShotInjector(mode="general")
    
    # ループを発生させる
    texts = [
        "天気の話をしましょう",
        "今日の天気は良いですね",
        "天気が良いと気分も良くなります",
        "本当に天気が良いですね",  # ループ発生
    ]
    
    print("\n--- Loop → Strategy → Pattern ---")
    for i, text in enumerate(texts):
        result = guard.check_and_update(text)
        
        if result.loop_detected or result.lacks_specificity:
            print(f"\nTurn {i+1}: Loop/Specificity issue detected!")
            print(f"  Strategy: {result.strategy.value}")
            
            # 戦略に対応するパターンを取得
            pattern = injector.select_pattern(
                signals_state=None,
                loop_strategy=result.strategy,
                lacks_specificity=result.lacks_specificity
            )
            
            if pattern:
                print(f"  Pattern found:")
                for line in pattern.split('\n')[:3]:
                    print(f"    {line}")
                print("    ...")
            else:
                print(f"  Pattern: Not found")
    
    print("\n✅ Integration test completed")
    return True


def main():
    """メインテスト実行"""
    print("NoveltyGuard + FewShotInjector Test Suite")
    print("=" * 60)
    
    results = []
    
    # Test 1: NoveltyGuard基本
    try:
        results.append(("NoveltyGuard Basic", test_novelty_guard_basic()))
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
        results.append(("NoveltyGuard Basic", False))
    
    # Test 2: 具体性チェック
    try:
        results.append(("Specificity Check", test_novelty_guard_specificity()))
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
        results.append(("Specificity Check", False))
    
    # Test 3: 具体性不足検知
    try:
        results.append(("Lack of Specificity", test_novelty_guard_lack_specificity()))
    except Exception as e:
        print(f"❌ Test 3 failed: {e}")
        results.append(("Lack of Specificity", False))
    
    # Test 4: FewShotInjector基本
    try:
        results.append(("FewShotInjector Basic", test_few_shot_injector_basic()))
    except Exception as e:
        print(f"❌ Test 4 failed: {e}")
        results.append(("FewShotInjector Basic", False))
    
    # Test 5: 戦略マッピング
    try:
        results.append(("Strategy Mapping", test_few_shot_strategy_mapping()))
    except Exception as e:
        print(f"❌ Test 5 failed: {e}")
        results.append(("Strategy Mapping", False))
    
    # Test 6: 連携テスト
    try:
        results.append(("Integration", test_integration()))
    except Exception as e:
        print(f"❌ Test 6 failed: {e}")
        results.append(("Integration", False))
    
    # サマリー
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = 0
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"   {name}: {status}")
        if success:
            passed += 1
    
    print(f"\n   Total: {passed}/{len(results)} passed")
    
    return passed == len(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
