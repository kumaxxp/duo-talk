#!/usr/bin/env python3
"""
GUI動作確認用インポートテスト

GUIのRUNSタブが動作するために必要なモジュールを
すべてインポートできるか確認します。

使用方法:
    python scripts/test_gui_imports.py
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_core_imports():
    """コアモジュールのインポートテスト"""
    print("=" * 60)
    print("Test 1: Core Module Imports")
    print("=" * 60)
    
    errors = []
    
    modules = [
        ("src.config", "config"),
        ("src.signals", "DuoSignals"),
        ("src.injection", "PromptBuilder, Priority"),
        ("src.novelty_guard", "NoveltyGuard, LoopBreakStrategy"),
        ("src.few_shot_injector", "FewShotInjector"),
        ("src.character", "Character"),
        ("src.director", "Director"),
        ("src.unified_pipeline", "UnifiedPipeline"),
        ("src.input_source", "InputBundle"),
    ]
    
    for module_path, components in modules:
        try:
            module = __import__(module_path, fromlist=[components.split(",")[0].strip()])
            print(f"  ✅ {module_path}")
        except Exception as e:
            print(f"  ❌ {module_path}: {e}")
            errors.append((module_path, str(e)))
    
    return len(errors) == 0, errors


def test_novelty_guard_strategies():
    """NoveltyGuard戦略のテスト"""
    print("\n" + "=" * 60)
    print("Test 2: NoveltyGuard Strategies")
    print("=" * 60)
    
    from src.novelty_guard import LoopBreakStrategy
    
    expected_strategies = [
        "FORCE_SPECIFIC_SLOT",
        "FORCE_CONFLICT_WITHIN",
        "FORCE_ACTION_NEXT",
        "FORCE_PAST_REFERENCE",
        "FORCE_WHY",
        "FORCE_EXPAND",
        "NOOP",
    ]
    
    all_present = True
    for name in expected_strategies:
        if hasattr(LoopBreakStrategy, name):
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name} - NOT FOUND")
            all_present = False
    
    return all_present


def test_few_shot_patterns():
    """FewShotパターンのロードテスト"""
    print("\n" + "=" * 60)
    print("Test 3: FewShot Patterns Load")
    print("=" * 60)
    
    from src.few_shot_injector import FewShotInjector, reset_few_shot_injector
    
    reset_few_shot_injector()
    
    # JetRacerモード
    injector_jetracer = FewShotInjector(mode="jetracer")
    jetracer_count = len(injector_jetracer.patterns)
    print(f"  JetRacer mode: {jetracer_count} patterns")
    
    # 必要なパターンIDの確認
    required_jetracer = [
        "specific_slot_example",
        "conflict_within_example", 
        "depth_why",
        "depth_expand",
    ]
    
    jetracer_ids = injector_jetracer.get_all_pattern_ids()
    for pid in required_jetracer:
        if pid in jetracer_ids:
            print(f"    ✅ {pid}")
        else:
            print(f"    ❌ {pid} - MISSING")
    
    # 一般会話モード
    injector_general = FewShotInjector(mode="general")
    general_count = len(injector_general.patterns)
    print(f"  General mode: {general_count} patterns")
    
    return jetracer_count >= 10 and general_count >= 10


def test_character_initialization():
    """Characterの初期化テスト"""
    print("\n" + "=" * 60)
    print("Test 4: Character Initialization")
    print("=" * 60)
    
    from src.character import Character
    
    errors = []
    
    # JetRacerモード
    try:
        char_a_jetracer = Character("A", jetracer_mode=True)
        print(f"  ✅ Character A (JetRacer): {char_a_jetracer.char_name}")
        
        # deep_valuesの確認
        if char_a_jetracer._deep_values:
            print(f"    deep_values loaded: {list(char_a_jetracer._deep_values.keys())[:3]}...")
        else:
            print(f"    ⚠️ deep_values is empty")
    except Exception as e:
        print(f"  ❌ Character A (JetRacer): {e}")
        errors.append(("A-JetRacer", str(e)))
    
    try:
        char_b_jetracer = Character("B", jetracer_mode=True)
        print(f"  ✅ Character B (JetRacer): {char_b_jetracer.char_name}")
    except Exception as e:
        print(f"  ❌ Character B (JetRacer): {e}")
        errors.append(("B-JetRacer", str(e)))
    
    # 一般会話モード
    try:
        char_a_general = Character("A", jetracer_mode=False)
        print(f"  ✅ Character A (General): {char_a_general.char_name}")
    except Exception as e:
        print(f"  ❌ Character A (General): {e}")
        errors.append(("A-General", str(e)))
    
    try:
        char_b_general = Character("B", jetracer_mode=False)
        print(f"  ✅ Character B (General): {char_b_general.char_name}")
    except Exception as e:
        print(f"  ❌ Character B (General): {e}")
        errors.append(("B-General", str(e)))
    
    return len(errors) == 0, errors


def test_unified_pipeline():
    """UnifiedPipelineの初期化テスト"""
    print("\n" + "=" * 60)
    print("Test 5: UnifiedPipeline Initialization")
    print("=" * 60)
    
    from src.unified_pipeline import UnifiedPipeline
    
    try:
        # JetRacerモード
        pipeline_jetracer = UnifiedPipeline(jetracer_mode=True)
        print(f"  ✅ UnifiedPipeline (JetRacer)")
        print(f"    char_a: {pipeline_jetracer.char_a.char_name}")
        print(f"    char_b: {pipeline_jetracer.char_b.char_name}")
    except Exception as e:
        print(f"  ❌ UnifiedPipeline (JetRacer): {e}")
        return False
    
    try:
        # 一般会話モード
        pipeline_general = UnifiedPipeline(jetracer_mode=False)
        print(f"  ✅ UnifiedPipeline (General)")
    except Exception as e:
        print(f"  ❌ UnifiedPipeline (General): {e}")
        return False
    
    return True


def test_deep_values_format():
    """deep_valuesのフォーマットテスト"""
    print("\n" + "=" * 60)
    print("Test 6: Deep Values Format")
    print("=" * 60)
    
    from src.character import Character
    
    char_a = Character("A", jetracer_mode=False)
    char_b = Character("B", jetracer_mode=False)
    
    # やなのdeep_values
    print("\n  --- やな (char_a) ---")
    formatted_a = char_a._format_deep_values()
    if formatted_a:
        print(formatted_a[:200] + "..." if len(formatted_a) > 200 else formatted_a)
    else:
        print("  ⚠️ Empty")
    
    # あゆのdeep_values
    print("\n  --- あゆ (char_b) ---")
    formatted_b = char_b._format_deep_values()
    if formatted_b:
        print(formatted_b[:200] + "..." if len(formatted_b) > 200 else formatted_b)
    else:
        print("  ⚠️ Empty")
    
    return bool(formatted_a) and bool(formatted_b)


def main():
    """メインテスト実行"""
    print("GUI Import & Initialization Test Suite")
    print("=" * 60)
    
    results = []
    
    # Test 1
    success, errors = test_core_imports()
    results.append(("Core Imports", success))
    if not success:
        print(f"\n  Errors: {errors}")
    
    # Test 2
    success = test_novelty_guard_strategies()
    results.append(("NoveltyGuard Strategies", success))
    
    # Test 3
    success = test_few_shot_patterns()
    results.append(("FewShot Patterns", success))
    
    # Test 4
    success, errors = test_character_initialization()
    results.append(("Character Init", success))
    if not success:
        print(f"\n  Errors: {errors}")
    
    # Test 5
    success = test_unified_pipeline()
    results.append(("UnifiedPipeline", success))
    
    # Test 6
    success = test_deep_values_format()
    results.append(("Deep Values Format", success))
    
    # サマリー
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = 0
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {name}: {status}")
        if success:
            passed += 1
    
    print(f"\n  Total: {passed}/{len(results)} passed")
    
    if passed == len(results):
        print("\n🎉 All tests passed! GUI should work correctly.")
    else:
        print("\n⚠️ Some tests failed. Check errors above.")
    
    return passed == len(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
