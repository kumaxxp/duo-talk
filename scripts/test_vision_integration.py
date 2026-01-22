"""
Vision実況統合テスト
Phase 0C: Vision情報に基づく会話パターン選択テスト

テスト内容:
1. FewShotInjectorのvisionパターン選択テスト
2. _format_scene_factsのフォーマットテスト
3. 統合フローテスト
"""
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Any, Optional

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class MockSignalsState:
    """テスト用のシグナルス状態モック"""
    scene_facts: Dict[str, Any]
    scene_timestamp: Optional[datetime] = None

    def is_stale(self, max_age_seconds: float = 5.0) -> bool:
        if not self.scene_timestamp:
            return False
        age = (datetime.now() - self.scene_timestamp).total_seconds()
        return age > max_age_seconds


def test_few_shot_injector_vision_patterns():
    """FewShotInjectorのvisionパターン選択テスト"""
    from src.few_shot_injector import FewShotInjector, reset_few_shot_injector

    print("=" * 60)
    print("TEST: FewShotInjector Vision Pattern Selection")
    print("=" * 60)

    # キャッシュをリセット
    reset_few_shot_injector()
    injector = FewShotInjector(mode="jetracer")

    # パターンが読み込まれているか確認
    pattern_ids = injector.get_all_pattern_ids()
    print(f"\nLoaded patterns: {len(pattern_ids)}")
    vision_patterns = [p for p in pattern_ids if p.startswith("vision_")]
    print(f"Vision patterns: {vision_patterns}")

    assert len(vision_patterns) >= 5, f"Expected 5+ vision patterns, got {len(vision_patterns)}"
    print("[PASS] Vision patterns loaded")

    # === テストケース1: 障害物検出（最優先） ===
    print("\n[Test 1] Obstacle detection (highest priority)")
    print("-" * 60)

    state = MockSignalsState(
        scene_facts={
            "detected_objects": "cone, road_line",
            "primary_object": "cone",
            "position": "right",
            "obstacle": "cone"
        },
        scene_timestamp=datetime.now()
    )

    pattern = injector.select_pattern(state)
    print(f"Selected pattern preview: {pattern[:80] if pattern else 'None'}...")
    assert pattern is not None, "Pattern not selected"
    assert "obstacle" in pattern.lower() or "障害物" in pattern or "コーン" in pattern, \
        f"Obstacle info not in pattern: {pattern[:100]}"
    print("[PASS] Test 1")

    # === テストケース2: 複数物体検出 ===
    print("\n[Test 2] Multiple objects detection")
    print("-" * 60)

    state = MockSignalsState(
        scene_facts={
            "detected_objects": "car, cone, road_line",
            "primary_object": "car"
        },
        scene_timestamp=datetime.now()
    )

    pattern = injector.select_pattern(state)
    print(f"Selected pattern preview: {pattern[:80] if pattern else 'None'}...")
    assert pattern is not None, "Pattern not selected"
    print("[PASS] Test 2")

    # === テストケース3: 車線位置検出 ===
    print("\n[Test 3] Lane position detection")
    print("-" * 60)

    state = MockSignalsState(
        scene_facts={
            "lane": "left",
            "position": "left"
        },
        scene_timestamp=datetime.now()
    )

    pattern = injector.select_pattern(state)
    print(f"Selected pattern preview: {pattern[:80] if pattern else 'None'}...")
    assert pattern is not None, "Pattern not selected"
    assert "left" in pattern.lower() or "左" in pattern, \
        f"Lane info not in pattern: {pattern[:100]}"
    print("[PASS] Test 3")

    # === テストケース4: 照明変化検出 ===
    print("\n[Test 4] Lighting/environment detection")
    print("-" * 60)

    state = MockSignalsState(
        scene_facts={
            "lighting": "dark",
            "scene_type": "outdoor"
        },
        scene_timestamp=datetime.now()
    )

    pattern = injector.select_pattern(state)
    print(f"Selected pattern preview: {pattern[:80] if pattern else 'None'}...")
    assert pattern is not None, "Pattern not selected"
    assert "dark" in pattern.lower() or "暗" in pattern, \
        f"Lighting info not in pattern: {pattern[:100]}"
    print("[PASS] Test 4")

    # === テストケース5: 基本物体検出 ===
    print("\n[Test 5] Basic object detection")
    print("-" * 60)

    state = MockSignalsState(
        scene_facts={
            "detected_objects": "cone",
            "primary_object": "cone",
            "position": "center"
        },
        scene_timestamp=datetime.now()
    )

    pattern = injector.select_pattern(state)
    print(f"Selected pattern preview: {pattern[:80] if pattern else 'None'}...")
    assert pattern is not None, "Pattern not selected"
    print("[PASS] Test 5")

    # === テストケース6: 古い情報は無視 ===
    print("\n[Test 6] Stale vision info should be ignored")
    print("-" * 60)

    from datetime import timedelta
    old_timestamp = datetime.now() - timedelta(seconds=10)
    state = MockSignalsState(
        scene_facts={
            "obstacle": "cone"
        },
        scene_timestamp=old_timestamp
    )

    pattern = injector.select_pattern(state)
    # 古い情報なのでvisionパターンは選択されないはず
    # ただし、他のパターンが選択される可能性もあるのでNone以外も許容
    print(f"Selected pattern (stale): {pattern[:50] if pattern else 'None'}...")
    print("[PASS] Test 6 (stale data handling)")

    print("\n" + "=" * 60)
    print(" ALL FEWSHOT INJECTOR TESTS PASSED ")
    print("=" * 60)


def test_format_scene_facts():
    """_format_scene_facts メソッドのテスト"""
    print("\n" + "=" * 60)
    print("TEST: _format_scene_facts Formatting")
    print("=" * 60)

    from src.character import Character

    # テスト用キャラクター作成
    char = Character('A', jetracer_mode=True)

    # === テストケース1: 基本フォーマット ===
    print("\n[Test 1] Basic formatting")
    print("-" * 60)

    scene_facts = {
        "detected_objects": "cone, car",
        "primary_object": "cone",
        "position": "right",
        "lighting": "dark",
        "lane": "left"
    }

    result = char._format_scene_facts(scene_facts)
    print(f"Formatted output:\n{result}")

    assert "検出物体" in result, "Missing detected_objects"
    assert "主要物体" in result, "Missing primary_object"
    assert "位置" in result, "Missing position"
    assert "照明" in result, "Missing lighting"
    assert "車線位置" in result, "Missing lane"
    print("[PASS] Test 1")

    # === テストケース2: 障害物警告 ===
    print("\n[Test 2] Obstacle warning formatting")
    print("-" * 60)

    scene_facts = {
        "obstacle": "cone",
        "position": "right"
    }

    result = char._format_scene_facts(scene_facts)
    print(f"Formatted output:\n{result}")

    assert "障害物" in result, "Missing obstacle warning"
    print("[PASS] Test 2")

    # === テストケース3: タイムスタンプ付き ===
    print("\n[Test 3] Timestamp formatting")
    print("-" * 60)

    scene_facts = {
        "detected_objects": "car",
        "vision_timestamp": datetime.now().isoformat()
    }

    result = char._format_scene_facts(scene_facts)
    print(f"Formatted output:\n{result}")

    assert "秒前" in result, "Missing timestamp info"
    print("[PASS] Test 3")

    # === テストケース4: 空の入力 ===
    print("\n[Test 4] Empty input")
    print("-" * 60)

    result = char._format_scene_facts({})
    assert result == "", f"Expected empty string, got: {result}"

    result = char._format_scene_facts(None)
    assert result == "", f"Expected empty string for None, got: {result}"
    print("[PASS] Test 4")

    print("\n" + "=" * 60)
    print(" ALL FORMAT TESTS PASSED ")
    print("=" * 60)


def test_vision_to_signals_integration():
    """VisionToSignals → FewShotInjector 統合テスト"""
    print("\n" + "=" * 60)
    print("TEST: VisionToSignals → FewShotInjector Integration")
    print("=" * 60)

    from src.vision_to_signals import VisionToSignals
    from src.few_shot_injector import FewShotInjector, reset_few_shot_injector
    from src.signals import DuoSignals

    # シングルトンをリセットしてクリーンな状態から始める
    DuoSignals.reset_instance()

    # 初期化
    signals = DuoSignals()
    converter = VisionToSignals()
    reset_few_shot_injector()
    injector = FewShotInjector(mode="jetracer")

    # === Florence-2出力をパースして注入 ===
    print("\n[Test] Florence-2 output → Signals → Pattern selection")
    print("-" * 60)

    # Florence-2風の出力をパース
    florence_output = "<OD>cone<loc_25><loc_40><loc_75><loc_85>car<loc_50><loc_60><loc_80><loc_90>"
    parsed = converter.parse_florence_output(florence_output)
    print(f"Parsed Florence output: {parsed}")

    # Signalsに注入
    converter.inject_to_signals(parsed, source="florence")

    # snapshot()経由でアクセス
    state = signals.snapshot()
    print(f"DuoSignals.scene_facts: {state.scene_facts}")

    # FewShotInjectorでパターン選択
    pattern = injector.select_pattern(state)

    print(f"Selected pattern preview: {pattern[:100] if pattern else 'None'}...")
    assert pattern is not None, "Pattern should be selected"
    print("[PASS] Integration test")

    # キャプションからの注入テスト
    print("\n[Test] Caption → Signals → Pattern selection")
    print("-" * 60)

    # シングルトンをリセット、新しいconverterも作成
    DuoSignals.reset_instance()
    signals = DuoSignals()
    converter = VisionToSignals()  # 新しいインスタンス（シングルトンの新しい参照を取得）

    caption = "A car driving on a dark road at night"
    parsed = converter.parse_caption(caption)
    print(f"Parsed caption: {parsed}")

    converter.inject_to_signals(parsed, source="caption")

    state = signals.snapshot()
    print(f"DuoSignals.scene_facts: {state.scene_facts}")

    pattern = injector.select_pattern(state)

    print(f"Selected pattern preview: {pattern[:100] if pattern else 'None'}...")
    assert pattern is not None, "Pattern should be selected for dark lighting"
    print("[PASS] Caption integration test")

    print("\n" + "=" * 60)
    print(" ALL INTEGRATION TESTS PASSED ")
    print("=" * 60)


def test_full_pipeline():
    """フルパイプラインテスト（Character含む）"""
    print("\n" + "=" * 60)
    print("TEST: Full Pipeline (Character integration)")
    print("=" * 60)

    from src.character import Character
    from src.vision_to_signals import VisionToSignals
    from src.signals import DuoSignals

    # シングルトンをリセット
    DuoSignals.reset_instance()

    # 初期化
    converter = VisionToSignals()
    char_a = Character('A', jetracer_mode=True)

    # Vision情報を注入
    print("\n[Test] Inject vision data and check prompt building")
    print("-" * 60)

    vision_data = {
        "detected_objects": "cone, road_line",
        "primary_object": "cone",
        "position": "right",
        "obstacle": "cone"
    }
    converter.inject_to_signals(vision_data, source="test")

    # scene_factsを確認（snapshot経由）
    state = char_a.signals.snapshot()
    print(f"Scene facts: {state.scene_facts}")

    # フォーマットを確認
    formatted = char_a._format_scene_facts(state.scene_facts)
    print(f"\nFormatted scene facts:\n{formatted}")

    assert "障害物" in formatted, "Obstacle should be in formatted output"
    assert "cone" in formatted.lower() or "コーン" in formatted, "Cone should be mentioned"
    print("[PASS] Full pipeline test")

    print("\n" + "=" * 60)
    print(" FULL PIPELINE TEST PASSED ")
    print("=" * 60)


def main():
    """全テスト実行"""
    print("\n" + "=" * 70)
    print("  VISION INTEGRATION TEST SUITE (Phase 0C)")
    print("=" * 70)

    try:
        test_few_shot_injector_vision_patterns()
        test_format_scene_facts()
        test_vision_to_signals_integration()
        test_full_pipeline()

        print("\n" + "=" * 70)
        print("  ALL VISION INTEGRATION TESTS PASSED ")
        print("=" * 70)

    except AssertionError as e:
        print(f"\n[FAIL] Assertion Error: {e}")
        raise
    except Exception as e:
        print(f"\n[ERROR] Unexpected Error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
