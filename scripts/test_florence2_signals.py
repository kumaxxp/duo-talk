#!/usr/bin/env python3
"""
Florence-2 → DuoSignals統合テスト

テスト内容:
1. Florence2ToSignals単体テスト
2. DuoSignalsへの注入確認
3. Character.speak_unified()でのscene_facts活用確認
4. UnifiedPipelineでのエンドツーエンドテスト

使用方法:
    # Florence-2サービスが起動している状態で実行
    python scripts/test_florence2_signals.py
    
    # テスト用画像を指定
    python scripts/test_florence2_signals.py path/to/image.jpg
"""

import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_florence2_to_signals(image_path: str = None):
    """Florence2ToSignals単体テスト"""
    print("=" * 60)
    print("Test 1: Florence2ToSignals")
    print("=" * 60)
    
    from src.florence2_to_signals import Florence2ToSignals
    from src.signals import DuoSignals
    
    # シングルトンをリセット
    DuoSignals.reset_instance()
    
    bridge = Florence2ToSignals()
    
    # サービス確認
    if not bridge.is_service_ready():
        print("❌ Florence-2 service not ready!")
        print("   Run: ./scripts/docker_services.sh start")
        return False
    
    print("✅ Florence-2 service is ready")
    
    # テスト画像
    if image_path is None:
        # デフォルトのテスト画像を探す
        test_images = [
            project_root / "tests" / "fixtures" / "test_image.jpg",
            project_root / "data" / "test_image.jpg",
        ]
        for p in test_images:
            if p.exists():
                image_path = str(p)
                break
        
        if image_path is None:
            print("⚠️ No test image found, creating dummy test...")
            # ダミーの画像データを生成
            import base64
            # 1x1 red pixel PNG
            dummy_png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIA6Bxx0QAAAABJRU5ErkJggg=="
            )
            result = bridge.process_image(dummy_png)
            print(f"   Success: {result.success}")
            print(f"   Caption: {result.caption}")
            return result.success
    
    print(f"   Image: {image_path}")
    
    # 解析実行
    result = bridge.process_image(image_path)
    
    print(f"   Success: {result.success}")
    print(f"   Caption: {result.caption}")
    print(f"   Objects: {result.objects}")
    print(f"   Scene Type: {result._estimate_scene_type()}")
    print(f"   Processing Time: {result.processing_time_ms:.1f}ms")
    
    if result.error:
        print(f"   Error: {result.error}")
    
    # scene_facts確認
    facts = result.to_scene_facts()
    print("\n   Scene Facts:")
    for k, v in facts.items():
        print(f"     {k}: {v}")
    
    return result.success


def test_signals_injection(image_path: str = None):
    """DuoSignalsへの注入確認"""
    print("\n" + "=" * 60)
    print("Test 2: DuoSignals Injection")
    print("=" * 60)
    
    from src.florence2_to_signals import Florence2ToSignals
    from src.signals import DuoSignals
    
    # シングルトンをリセット
    DuoSignals.reset_instance()
    signals = DuoSignals()
    
    bridge = Florence2ToSignals(signals=signals, auto_inject=True)
    
    if not bridge.is_service_ready():
        print("❌ Florence-2 service not ready!")
        return False
    
    # 解析前の状態
    state_before = signals.snapshot()
    print(f"   Before: scene_facts = {state_before.scene_facts}")
    
    # テスト画像で解析（auto_inject=True）
    if image_path:
        result = bridge.process_image(image_path)
    else:
        # ダミー画像
        import base64
        dummy_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIA6Bxx0QAAAABJRU5ErkJggg=="
        )
        result = bridge.process_image(dummy_png)
    
    # 解析後の状態
    state_after = signals.snapshot()
    print(f"   After: scene_facts = {state_after.scene_facts}")
    
    # 注入確認
    if state_after.scene_facts:
        print("✅ scene_facts injected successfully")
        return True
    else:
        print("❌ scene_facts not injected")
        return False


def test_character_scene_facts():
    """Character.speak_unified()でのscene_facts活用確認"""
    print("\n" + "=" * 60)
    print("Test 3: Character scene_facts Integration")
    print("=" * 60)
    
    from src.character import Character
    from src.signals import DuoSignals, SignalEvent, EventType
    
    # シングルトンをリセット
    DuoSignals.reset_instance()
    
    # Characterを初期化
    char_a = Character("A", jetracer_mode=False)
    
    # scene_factsを手動で設定
    char_a.signals.update(SignalEvent(
        event_type=EventType.VLM,
        data={
            "facts": {
                "caption": "A living room with a sofa and a TV",
                "objects": "sofa, TV, lamp",
                "scene_type": "indoor",
            }
        }
    ))
    
    # 状態確認
    state = char_a.signals.snapshot()
    print(f"   scene_facts: {state.scene_facts}")
    
    # _format_scene_facts()のテスト
    formatted = char_a._format_scene_facts(state.scene_facts)
    print(f"\n   Formatted:\n{formatted}")
    
    print("\n✅ Character scene_facts integration ready")
    return True


def test_unified_pipeline_integration(image_path: str = None):
    """UnifiedPipelineでのエンドツーエンドテスト"""
    print("\n" + "=" * 60)
    print("Test 4: UnifiedPipeline Integration")
    print("=" * 60)
    
    from src.unified_pipeline import UnifiedPipeline
    from src.input_source import InputBundle, InputSource, SourceType
    from src.signals import DuoSignals
    
    # シングルトンをリセット
    DuoSignals.reset_instance()
    
    # パイプライン作成（JetRacerなし、Florence-2あり）
    pipeline = UnifiedPipeline(
        jetracer_client=None,
        enable_florence2=True,
        jetracer_mode=False,  # 一般会話モード
    )
    
    # Florence-2サービス確認
    bridge = pipeline.florence2_bridge
    if bridge:
        print("✅ Florence-2 bridge initialized")
    else:
        print("⚠️ Florence-2 bridge not available (service may be down)")
    
    # 一般会話モードでテスト
    bundle = InputBundle(sources=[
        InputSource(source_type=SourceType.TEXT, content="今日の天気について話して")
    ])
    
    print("   Running dialogue...")
    result = pipeline.run(initial_input=bundle, max_turns=2)
    
    print(f"\n   Status: {result.status}")
    print(f"   Turns: {len(result.dialogue)}")
    
    if result.dialogue:
        print("\n   Dialogue:")
        for turn in result.dialogue:
            print(f"     [{turn.speaker_name}] {turn.text}")
    
    if result.error:
        print(f"   Error: {result.error}")
    
    print("\n✅ UnifiedPipeline integration test completed")
    return result.status == "success"


def main():
    """メインテスト実行"""
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    
    print("Florence-2 → DuoSignals Integration Test")
    print("=" * 60)
    
    results = []
    
    # Test 1: Florence2ToSignals
    try:
        results.append(("Florence2ToSignals", test_florence2_to_signals(image_path)))
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
        results.append(("Florence2ToSignals", False))
    
    # Test 2: Signals Injection
    try:
        results.append(("Signals Injection", test_signals_injection(image_path)))
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
        results.append(("Signals Injection", False))
    
    # Test 3: Character Integration
    try:
        results.append(("Character Integration", test_character_scene_facts()))
    except Exception as e:
        print(f"❌ Test 3 failed: {e}")
        results.append(("Character Integration", False))
    
    # Test 4: UnifiedPipeline
    try:
        results.append(("UnifiedPipeline", test_unified_pipeline_integration(image_path)))
    except Exception as e:
        print(f"❌ Test 4 failed: {e}")
        results.append(("UnifiedPipeline", False))
    
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
