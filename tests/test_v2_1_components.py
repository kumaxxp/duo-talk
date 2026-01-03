"""
duo-talk v2.1 コンポーネントテスト
"""

import pytest
from datetime import datetime, timedelta
import threading
import time


class TestDuoSignals:
    """DuoSignals のテスト"""

    def setup_method(self):
        from src.signals import DuoSignals
        DuoSignals.reset_instance()

    def test_singleton(self):
        from src.signals import DuoSignals
        s1 = DuoSignals()
        s2 = DuoSignals()
        assert s1 is s2

    def test_update_and_snapshot(self):
        from src.signals import DuoSignals, SignalEvent, EventType

        signals = DuoSignals()
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 1.5, "sensors": {"left": 0.3}}
        ))

        state = signals.snapshot()
        assert state.current_speed == 1.5
        assert state.distance_sensors == {"left": 0.3}

    def test_thread_safety(self):
        from src.signals import DuoSignals, SignalEvent, EventType

        signals = DuoSignals()
        errors = []

        def writer():
            for i in range(100):
                try:
                    signals.update(SignalEvent(
                        event_type=EventType.SENSOR,
                        data={"speed": float(i)}
                    ))
                except Exception as e:
                    errors.append(e)

        def reader():
            for _ in range(100):
                try:
                    state = signals.snapshot()
                    _ = state.current_speed
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestPromptBuilder:
    """PromptBuilder のテスト"""

    def test_priority_order(self):
        from src.injection import PromptBuilder, Priority

        builder = PromptBuilder()
        builder.add("Last", Priority.FEW_SHOT, "few_shot")
        builder.add("First", Priority.SYSTEM, "system")
        builder.add("Middle", Priority.HISTORY, "history")

        prompt = builder.build()
        assert prompt.index("First") < prompt.index("Middle") < prompt.index("Last")

    def test_last_utterance_after_history(self):
        from src.injection import PromptBuilder, Priority

        builder = PromptBuilder()
        builder.add("会話履歴", Priority.HISTORY, "history")
        builder.add("直前の発言", Priority.LAST_UTTERANCE, "last")
        builder.add("シーン情報", Priority.SCENE_FACTS, "scene")

        prompt = builder.build()
        # HISTORY(50) < LAST_UTTERANCE(55) < SCENE_FACTS(65)
        assert prompt.index("会話履歴") < prompt.index("直前の発言") < prompt.index("シーン情報")

    def test_slot_injection(self):
        from src.injection import PromptBuilder, Priority

        builder = PromptBuilder()
        builder.add("一般的な話", Priority.HISTORY, "history")

        # 具体性スロットが未充足
        unfilled = builder.check_and_inject_slots("センサー")

        assert "具体性" in unfilled
        prompt = builder.build()
        assert "【必須】" in prompt


class TestNoveltyGuard:
    """NoveltyGuard のテスト"""

    def test_no_loop_initially(self):
        from src.novelty_guard import NoveltyGuard

        guard = NoveltyGuard(max_topic_depth=3)
        result = guard.check_and_update("センサーの値が変です")

        assert result.loop_detected == False

    def test_loop_detection(self):
        from src.novelty_guard import NoveltyGuard, LoopBreakStrategy

        guard = NoveltyGuard(max_topic_depth=3)

        # 同じ名詞を含む発言を4回（max_topic_depth + 1回で検出される）
        guard.check_and_update("センサーの値が変です")
        guard.check_and_update("センサーを確認しましょう")
        guard.check_and_update("センサーの調子が悪いかも")
        result = guard.check_and_update("センサーのデータを見てください")

        assert result.loop_detected == True
        assert "センサー" in result.stuck_nouns
        assert result.strategy != LoopBreakStrategy.NOOP
        assert result.injection is not None

    def test_strategy_rotation(self):
        from src.novelty_guard import NoveltyGuard, LoopBreakStrategy

        # 同じトピックで継続してループを発生させる
        guard = NoveltyGuard(max_topic_depth=2)
        strategies = []

        # 同じセンサーというトピックで継続的にループ
        for i in range(10):
            result = guard.check_and_update(f"センサーの値が変です。{i}回目の確認。")
            if result.loop_detected:
                strategies.append(result.strategy)

        # ループが複数回検出されていることを確認
        assert len(strategies) >= 3, f"Expected at least 3 loop detections, got {len(strategies)}"

        # 戦略選択が機能していることを確認（NOOPではない）
        for s in strategies:
            assert s != LoopBreakStrategy.NOOP, "Strategy should not be NOOP"


class TestSilenceController:
    """SilenceController のテスト"""

    def test_high_speed_silence(self):
        from src.silence_controller import SilenceController, SilenceType
        from dataclasses import dataclass

        @dataclass
        class MockState:
            current_speed: float = 3.0
            scene_facts: dict = None
            recent_events: list = None

            def __post_init__(self):
                self.scene_facts = self.scene_facts or {}
                self.recent_events = self.recent_events or []

        controller = SilenceController(high_speed_threshold=2.5)
        state = MockState(current_speed=3.0)

        result = controller.should_silence(state)

        assert result is not None
        assert result.silence_type == SilenceType.CONCENTRATION

    def test_no_silence_normal_speed(self):
        from src.silence_controller import SilenceController
        from dataclasses import dataclass

        @dataclass
        class MockState:
            current_speed: float = 1.0
            scene_facts: dict = None
            recent_events: list = None

            def __post_init__(self):
                self.scene_facts = self.scene_facts or {}
                self.recent_events = self.recent_events or []

        controller = SilenceController()
        state = MockState()

        result = controller.should_silence(state)

        assert result is None

    def test_tension_silence_on_difficult_corner(self):
        from src.silence_controller import SilenceController, SilenceType
        from dataclasses import dataclass

        @dataclass
        class MockState:
            current_speed: float = 1.0
            scene_facts: dict = None
            recent_events: list = None

            def __post_init__(self):
                self.scene_facts = self.scene_facts or {}
                self.recent_events = self.recent_events or []

        controller = SilenceController()
        state = MockState(
            current_speed=1.0,
            scene_facts={"upcoming": "difficult_corner"}
        )

        result = controller.should_silence(state)

        assert result is not None
        assert result.silence_type == SilenceType.TENSION


class TestSlotChecker:
    """SlotChecker のテスト"""

    def test_check_text_specificity(self):
        from src.injection import SlotChecker

        checker = SlotChecker()

        # 具体的な数値を含む
        filled = checker.check_text("速度は2.5m/sです")
        assert "具体性" in filled

        # 時間を含む
        filled = checker.check_text("前回は5秒で到達した")
        assert "具体性" in filled

    def test_check_text_relationship(self):
        from src.injection import SlotChecker

        checker = SlotChecker()

        filled = checker.check_text("私たちでやってみよう")
        assert "関係性" in filled

        filled = checker.check_text("姉様に確認してもらいましょう")
        assert "関係性" in filled

    def test_unfilled_slots(self):
        from src.injection import SlotChecker

        checker = SlotChecker()
        checker.update("普通の会話です")

        unfilled = checker.get_unfilled(["具体性", "関係性"])
        assert "具体性" in unfilled
        assert "関係性" in unfilled


class TestWorldRules:
    """world_rules.yaml のテスト"""

    def test_world_rules_loads(self):
        import yaml
        from pathlib import Path

        world_rules_path = Path("persona/world_rules.yaml")
        assert world_rules_path.exists(), "world_rules.yaml should exist"

        with open(world_rules_path, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)

        assert "world_state" in rules
        assert "core_rule" in rules["world_state"]
        assert "conversation_rules" in rules


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
