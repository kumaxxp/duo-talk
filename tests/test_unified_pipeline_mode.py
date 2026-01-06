"""UnifiedPipeline モード切り替えテスト"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.unified_pipeline import UnifiedPipeline
from src.input_source import InputBundle, InputSource, SourceType


class TestUnifiedPipelineModeDetection:
    """UnifiedPipelineのモード自動判定テスト"""

    def test_text_only_uses_general_mode(self):
        """テキストのみ入力で一般会話モードになることを確認"""
        pipeline = UnifiedPipeline()
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="お正月について話しましょう")
        ])

        mode = pipeline._determine_jetracer_mode(bundle)
        assert mode is False, "テキストのみ入力は一般会話モードになるべき"

    def test_jetracer_sensor_uses_jetracer_mode(self):
        """JetRacerセンサー入力でJetRacerモードになることを確認"""
        pipeline = UnifiedPipeline()
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="走行中の状況"),
            InputSource(source_type=SourceType.JETRACER_SENSOR)
        ])

        mode = pipeline._determine_jetracer_mode(bundle)
        assert mode is True, "JetRacerセンサー入力はJetRacerモードになるべき"

    def test_jetracer_cam_uses_jetracer_mode(self):
        """JetRacerカメラ入力でJetRacerモードになることを確認"""
        pipeline = UnifiedPipeline()
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.JETRACER_CAM0)
        ])

        mode = pipeline._determine_jetracer_mode(bundle)
        assert mode is True, "JetRacerカメラ入力はJetRacerモードになるべき"

    def test_override_forces_jetracer_mode(self):
        """jetracer_mode=Trueでオーバーライドできることを確認"""
        pipeline = UnifiedPipeline(jetracer_mode=True)
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="普通のテキスト")
        ])

        mode = pipeline._determine_jetracer_mode(bundle)
        assert mode is True, "オーバーライドでJetRacerモードを強制できるべき"

    def test_override_forces_general_mode(self):
        """jetracer_mode=Falseでオーバーライドできることを確認"""
        pipeline = UnifiedPipeline(jetracer_mode=False)
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="JetRacer関連"),
            InputSource(source_type=SourceType.JETRACER_SENSOR)
        ])

        mode = pipeline._determine_jetracer_mode(bundle)
        assert mode is False, "オーバーライドで一般会話モードを強制できるべき"


class TestUnifiedPipelineModeIntegration:
    """UnifiedPipelineのモード切り替え統合テスト"""

    def test_run_with_general_mode(self):
        """一般会話モードで実行が完了することを確認"""
        pipeline = UnifiedPipeline(jetracer_mode=False)
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="今年の抱負について")
        ])

        result = pipeline.run(
            initial_input=bundle,
            max_turns=2,
        )

        assert result.status == "success"
        assert len(result.dialogue) == 2
        # キャラクターが一般会話モードで初期化されていることを確認
        assert pipeline.char_a.jetracer_mode is False
        assert pipeline.char_b.jetracer_mode is False

    def test_run_with_jetracer_mode(self):
        """JetRacerモードで実行が完了することを確認"""
        pipeline = UnifiedPipeline(jetracer_mode=True)
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="走行テスト")
        ])

        result = pipeline.run(
            initial_input=bundle,
            max_turns=2,
        )

        assert result.status == "success"
        assert len(result.dialogue) == 2
        # キャラクターがJetRacerモードで初期化されていることを確認
        assert pipeline.char_a.jetracer_mode is True
        assert pipeline.char_b.jetracer_mode is True

    def test_mode_reinitializes_characters(self):
        """モードが変わった場合にキャラクターが再初期化されることを確認"""
        # 最初に一般会話モードで実行
        pipeline = UnifiedPipeline(jetracer_mode=False)
        bundle_general = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="一般会話")
        ])

        result1 = pipeline.run(initial_input=bundle_general, max_turns=2)
        assert pipeline.char_a.jetracer_mode is False

        # オーバーライドを変更してJetRacerモードで再実行
        pipeline._jetracer_mode_override = True
        bundle_jetracer = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="JetRacer走行")
        ])

        result2 = pipeline.run(initial_input=bundle_jetracer, max_turns=2)
        # キャラクターが再初期化されてJetRacerモードになっていることを確認
        assert pipeline.char_a.jetracer_mode is True
        assert pipeline.char_b.jetracer_mode is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
