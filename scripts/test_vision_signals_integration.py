"""
Vision → Signals 統合テスト
"""
import sys
sys.path.insert(0, "/home/owner/work/duo-talk")

from src.signals import DuoSignals
from src.vision_to_signals import VisionToSignals
from datetime import datetime


def test_florence_parsing():
    """Florence-2出力のパースをテスト"""
    print("=" * 60)
    print("TEST 1: Florence-2 Output Parsing")
    print("=" * 60)

    converter = VisionToSignals()

    # サンプル出力（実際のFlorence-2出力形式）
    florence_od = "<OD>car<loc_25><loc_40><loc_75><loc_85>cone<loc_10><loc_20><loc_30><loc_40>"

    result = converter.parse_florence_output(florence_od)

    print(f"Input: {florence_od}")
    print(f"Output: {result}")

    # アサーション
    assert "detected_objects" in result, "検出物体が抽出されていない"
    assert "car" in result.get("detected_objects", ""), "carが検出されていない"
    assert "primary_object" in result, "primary_objectが設定されていない"
    assert result.get("primary_object") == "car", "primary_objectがcarでない"

    print("[PASS] TEST 1")
    return result


def test_caption_parsing():
    """キャプション出力のパースをテスト"""
    print("\n" + "=" * 60)
    print("TEST 2: Caption Parsing")
    print("=" * 60)

    converter = VisionToSignals()

    # テストケース
    test_cases = [
        ("A car driving on a dark road at night", {"lighting": "dark", "scene_type": "outdoor"}),
        ("Indoor room with a table and chairs", {"scene_type": "indoor"}),
        ("Racing track with cones", {"scene_type": "racing"}),
        ("Sunny park with trees and people walking", {"lighting": "bright", "activity": "moving"}),
    ]

    all_passed = True
    for caption, expected in test_cases:
        result = converter.parse_caption(caption)
        print(f"\nInput: {caption}")
        print(f"Output: {result}")

        for key, value in expected.items():
            if result.get(key) != value:
                print(f"  [FAIL] Expected {key}={value}, got {result.get(key)}")
                all_passed = False
            else:
                print(f"  [OK] {key}={value}")

    if all_passed:
        print("\n[PASS] TEST 2")
    else:
        print("\n[FAIL] TEST 2")
        raise AssertionError("Caption parsing failed")


def test_vlm_parsing():
    """VLM出力のパースをテスト"""
    print("\n" + "=" * 60)
    print("TEST 3: VLM Output Parsing")
    print("=" * 60)

    converter = VisionToSignals()

    # テストケース（日本語・英語混在）
    test_cases = [
        ("画像には赤い車が道路の右側を走っています", {"color": "red", "lane": "right"}),
        ("A white car on the left lane", {"color": "white", "lane": "left"}),
        ("前方にコーンがあります。カーブが見えます", {"obstacle": "コーン", "upcoming": "curve"}),
        ("The road ahead is straight with no obstacles", {"upcoming": "straight"}),
    ]

    all_passed = True
    for vlm_text, expected in test_cases:
        result = converter.parse_vlm_output(vlm_text)
        print(f"\nInput: {vlm_text}")
        print(f"Output: {result}")

        for key, value in expected.items():
            if result.get(key) != value:
                print(f"  [FAIL] Expected {key}={value}, got {result.get(key)}")
                all_passed = False
            else:
                print(f"  [OK] {key}={value}")

    if all_passed:
        print("\n[PASS] TEST 3")
    else:
        print("\n[FAIL] TEST 3")
        raise AssertionError("VLM parsing failed")


def test_signals_injection():
    """DuoSignalsへの注入をテスト"""
    print("\n" + "=" * 60)
    print("TEST 4: Signals Injection")
    print("=" * 60)

    # 新しいDuoSignalsインスタンスを作成（テスト用）
    signals = DuoSignals()
    converter = VisionToSignals(signals=signals)

    # 初期状態確認
    initial_state = signals.snapshot()
    print(f"Before injection: scene_facts = {initial_state.scene_facts}")

    # テストデータ
    vision_data = {
        "detected_objects": "car, cone",
        "primary_object": "car",
        "position": "center",
        "lane": "right"
    }

    # 注入
    converter.inject_to_signals(vision_data, source="florence")

    # 注入後の状態確認
    after_state = signals.snapshot()
    print(f"After injection: scene_facts = {after_state.scene_facts}")

    # アサーション
    assert "detected_objects" in after_state.scene_facts, "注入失敗: detected_objectsがない"
    assert after_state.scene_facts.get("vision_source") == "florence", "vision_sourceが設定されていない"
    assert "vision_timestamp" in after_state.scene_facts, "vision_timestampがない"

    print(f"Timestamp: {after_state.scene_timestamp}")

    print("\n[PASS] TEST 4")


def test_process_methods():
    """process_* メソッドのテスト"""
    print("\n" + "=" * 60)
    print("TEST 5: Process Methods")
    print("=" * 60)

    signals = DuoSignals()
    converter = VisionToSignals(signals=signals)

    # Florence処理
    florence_result = converter.process_florence(
        "<OD>car<loc_50><loc_50><loc_100><loc_100>",
        inject=True
    )
    print(f"Florence result: {florence_result}")

    # Caption処理
    caption_result = converter.process_caption(
        "A sunny day with cars on the road",
        inject=True
    )
    print(f"Caption result: {caption_result}")

    # VLM処理
    vlm_result = converter.process_vlm(
        "前方は直線です",
        inject=True
    )
    print(f"VLM result: {vlm_result}")

    # 最終状態確認
    final_facts = converter.get_current_scene_facts()
    print(f"Final scene_facts: {final_facts}")

    # アサーション
    assert "vision_source" in final_facts, "vision_sourceがない"

    print("\n[PASS] TEST 5")


def test_segmentation_parsing():
    """セグメンテーション結果のパースをテスト"""
    print("\n" + "=" * 60)
    print("TEST 6: Segmentation Parsing")
    print("=" * 60)

    converter = VisionToSignals()

    seg_result = {
        "road_percentage": 75.5,
        "navigation_hint": "straight",
        "inference_time": 42.3
    }

    result = converter.parse_segmentation_result(seg_result)
    print(f"Input: {seg_result}")
    print(f"Output: {result}")

    assert result.get("road_percentage") == "76%", f"road_percentageが不正: {result.get('road_percentage')}"
    assert result.get("navigation_hint") == "straight", "navigation_hintが不正"
    assert "ms" in result.get("inference_time", ""), "inference_timeにmsがない"

    print("\n[PASS] TEST 6")


if __name__ == "__main__":
    try:
        test_florence_parsing()
        test_caption_parsing()
        test_vlm_parsing()
        test_signals_injection()
        test_process_methods()
        test_segmentation_parsing()

        print("\n" + "=" * 60)
        print(" ALL TESTS PASSED ")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
