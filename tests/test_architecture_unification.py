"""
アーキテクチャ統一テスト

Phase 1: speak()/speak_v2() 非推奨警告
Phase 2: run_continuous() 動作確認
"""

import pytest
import warnings
from src.character import Character
from src.unified_pipeline import UnifiedPipeline
from src.input_source import InputBundle, InputSource, SourceType


class TestPhase1SpeakDeprecation:
    """Phase 1: speak メソッド非推奨化テスト"""

    def test_speak_shows_deprecation_warning(self):
        """speak()が非推奨警告を出すことを確認"""
        char = Character("A", jetracer_mode=False)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = char.speak(
                frame_description="テスト用フレーム",
                partner_speech="こんにちは",
            )

            # 警告が出ていることを確認
            assert len(w) >= 1
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "speak_unified" in str(deprecation_warnings[0].message)

            # 結果は文字列であること
            assert isinstance(result, str)
            assert len(result) > 0

    def test_speak_v2_shows_deprecation_warning(self):
        """speak_v2()が非推奨警告を出すことを確認"""
        char = Character("A", jetracer_mode=False)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = char.speak_v2(
                last_utterance="こんにちは",
                context={"history": []},
                frame_description="テスト用フレーム",
            )

            # 警告が出ていることを確認
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "speak_unified" in str(deprecation_warnings[0].message)

            # 結果形式を確認
            assert result["type"] == "speech"
            assert isinstance(result["content"], str)

    def test_speak_unified_no_warning(self):
        """speak_unified()は警告を出さない（speak関連の警告）"""
        char = Character("A", jetracer_mode=False)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = char.speak_unified(
                frame_description="テスト用フレーム",
                conversation_history=[("B", "こんにちは")],
            )

            # speak_unified自体からのDeprecationWarningは出ない
            # （speak()やspeak_v2()からの警告は内部呼び出しなので除外しない）
            speak_deprecation_warnings = [
                x for x in w
                if issubclass(x.category, DeprecationWarning)
                and "speak_unified" in str(x.message)  # speak_unifiedへの移行を促す警告
            ]
            # speak_unifiedは非推奨ではないので、自身への移行警告は出ない
            assert len(speak_deprecation_warnings) == 0

            # 結果は文字列
            assert isinstance(result, str)


class TestPhase2RunContinuous:
    """Phase 2: run_continuous() テスト"""

    def test_run_continuous_basic(self):
        """run_continuous()の基本動作"""
        pipeline = UnifiedPipeline(jetracer_mode=False)

        frame_count = 0
        max_test_frames = 2

        def input_generator():
            nonlocal frame_count
            if frame_count >= max_test_frames:
                return None
            frame_count += 1
            return InputBundle(sources=[
                InputSource(source_type=SourceType.TEXT, content=f"フレーム{frame_count}のテスト")
            ])

        result = pipeline.run_continuous(
            input_generator=input_generator,
            max_frames=max_test_frames,
            frame_interval=0.1,  # テスト用に短く
            turns_per_frame=2,
        )

        assert result.status == "success"
        assert result.metadata["total_frames"] == max_test_frames
        assert result.metadata["mode"] == "continuous"
        assert len(result.dialogue) == max_test_frames * 2  # 2 turns per frame

    def test_run_continuous_stop_callback(self):
        """stop_callbackで停止"""
        pipeline = UnifiedPipeline(jetracer_mode=False)

        call_count = 0

        def input_generator():
            return InputBundle(sources=[
                InputSource(source_type=SourceType.TEXT, content="テスト")
            ])

        def stop_callback():
            nonlocal call_count
            call_count += 1
            return call_count >= 2  # 2回目で停止

        result = pipeline.run_continuous(
            input_generator=input_generator,
            frame_interval=0.1,
            turns_per_frame=2,
            stop_callback=stop_callback,
        )

        assert result.status == "success"
        assert result.metadata["total_frames"] <= 2

    def test_run_continuous_event_callback(self):
        """event_callbackが呼ばれることを確認"""
        pipeline = UnifiedPipeline(jetracer_mode=False)

        events = []

        def input_generator():
            if len([e for e in events if e[0] == "frame_complete"]) >= 1:
                return None
            return InputBundle(sources=[
                InputSource(source_type=SourceType.TEXT, content="テスト")
            ])

        def event_callback(event_type, data):
            events.append((event_type, data))

        result = pipeline.run_continuous(
            input_generator=input_generator,
            frame_interval=0.1,
            turns_per_frame=2,
            event_callback=event_callback,
        )

        # イベントが記録されていることを確認
        event_types = [e[0] for e in events]
        assert "session_start" in event_types
        assert "session_end" in event_types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
