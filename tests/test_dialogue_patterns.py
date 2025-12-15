"""
Integration tests for dialogue pattern system.
Tests beat tracking, pattern selection, and character constraints.
"""

import pytest
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.beat_tracker import BeatTracker, get_beat_tracker, reset_beat_tracker
from src.types import DirectorEvaluation, DirectorStatus, BeatStage, DialoguePattern
from src.validator import (
    check_forbidden_expressions,
    check_ayu_forbidden,
    check_yana_forbidden,
    validate_character_response,
)


class TestBeatTracker:
    """Tests for BeatTracker class"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset beat tracker before each test"""
        reset_beat_tracker()
        yield
        reset_beat_tracker()

    def test_beat_tracker_initialization(self):
        """BeatTracker should load policy from YAML"""
        tracker = get_beat_tracker()
        assert tracker is not None
        assert len(tracker.beats) > 0
        assert len(tracker.patterns) > 0

    def test_beat_tracker_setup_turns(self):
        """Turns 1-2 should return SETUP beat"""
        tracker = get_beat_tracker()
        assert tracker.get_current_beat(1) == "SETUP"
        assert tracker.get_current_beat(2) == "SETUP"

    def test_beat_tracker_exploration_turns(self):
        """Turns 3-5 should return EXPLORATION beat"""
        tracker = get_beat_tracker()
        assert tracker.get_current_beat(3) == "EXPLORATION"
        assert tracker.get_current_beat(4) == "EXPLORATION"
        assert tracker.get_current_beat(5) == "EXPLORATION"

    def test_beat_tracker_personal_turns(self):
        """Turns 6-7 should return PERSONAL beat"""
        tracker = get_beat_tracker()
        assert tracker.get_current_beat(6) == "PERSONAL"
        assert tracker.get_current_beat(7) == "PERSONAL"

    def test_beat_tracker_wrap_up_turns(self):
        """Turns 8-10 should return WRAP_UP beat"""
        tracker = get_beat_tracker()
        assert tracker.get_current_beat(8) == "WRAP_UP"
        assert tracker.get_current_beat(9) == "WRAP_UP"
        assert tracker.get_current_beat(10) == "WRAP_UP"

    def test_beat_tracker_beyond_range(self):
        """Turns beyond 10 should default to WRAP_UP"""
        tracker = get_beat_tracker()
        assert tracker.get_current_beat(11) == "WRAP_UP"
        assert tracker.get_current_beat(15) == "WRAP_UP"

    def test_get_preferred_patterns_setup(self):
        """SETUP beat should prefer patterns A, B"""
        tracker = get_beat_tracker()
        patterns = tracker.get_preferred_patterns("SETUP")
        assert "A" in patterns
        assert "B" in patterns

    def test_get_preferred_patterns_exploration(self):
        """EXPLORATION beat should prefer patterns B, C"""
        tracker = get_beat_tracker()
        patterns = tracker.get_preferred_patterns("EXPLORATION")
        assert "B" in patterns
        assert "C" in patterns

    def test_get_preferred_patterns_personal(self):
        """PERSONAL beat should prefer patterns D, E"""
        tracker = get_beat_tracker()
        patterns = tracker.get_preferred_patterns("PERSONAL")
        assert "D" in patterns
        assert "E" in patterns

    def test_pattern_not_allowed_three_times(self):
        """Same pattern should not be allowed 3 times in a row"""
        tracker = get_beat_tracker()
        recent_patterns = ["A", "A"]
        # Third consecutive "A" should not be allowed
        assert not tracker.is_pattern_allowed("A", recent_patterns)
        # But "B" should be allowed
        assert tracker.is_pattern_allowed("B", recent_patterns)

    def test_pattern_allowed_after_different(self):
        """Pattern should be allowed after a different pattern"""
        tracker = get_beat_tracker()
        recent_patterns = ["A", "B"]
        # "A" should be allowed after "B"
        assert tracker.is_pattern_allowed("A", recent_patterns)

    def test_suggest_pattern_respects_beat(self):
        """suggest_pattern should prefer patterns for current beat"""
        tracker = get_beat_tracker()
        # Turn 1 is SETUP, should prefer A or B
        suggested = tracker.suggest_pattern(1, [])
        assert suggested in ["A", "B"]

    def test_suggest_pattern_avoids_repetition(self):
        """suggest_pattern should avoid repeating the same pattern"""
        tracker = get_beat_tracker()
        # If A was used twice, should suggest something else
        suggested = tracker.suggest_pattern(1, ["A", "A"])
        assert suggested != "A"

    def test_get_pattern_info(self):
        """get_pattern_info should return pattern details"""
        tracker = get_beat_tracker()
        info_a = tracker.get_pattern_info("A")
        assert info_a.get("name") == "発見→補足"
        assert "yana_role" in info_a
        assert "ayu_role" in info_a

    def test_get_beat_info(self):
        """get_beat_info should return beat details"""
        tracker = get_beat_tracker()
        info = tracker.get_beat_info("SETUP")
        assert info.get("goal") is not None
        assert info.get("tone") is not None


class TestForbiddenExpressions:
    """Tests for forbidden expression checking"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset beat tracker before each test"""
        reset_beat_tracker()
        yield
        reset_beat_tracker()

    def test_ayu_forbidden_iitendesu(self):
        """'いい観点ですね' should be detected for あゆ"""
        text = "姉様、いい観点ですね。それは鎌倉時代の建築様式です。"
        violations = check_ayu_forbidden(text)
        assert "いい観点ですね" in violations

    def test_ayu_forbidden_iishitsumon(self):
        """'いい質問ですね' should be detected for あゆ"""
        text = "いい質問ですね、姉様。"
        violations = check_ayu_forbidden(text)
        assert "いい質問ですね" in violations

    def test_ayu_forbidden_sasuga(self):
        """'さすがですね' should be detected for あゆ"""
        text = "さすがですね、姉様。"
        violations = check_ayu_forbidden(text)
        assert "さすがですね" in violations

    def test_ayu_forbidden_haikei(self):
        """'という背景があります' should be detected for あゆ"""
        text = "これには歴史的な理由という背景があります。"
        violations = check_ayu_forbidden(text)
        assert "という背景があります" in violations

    def test_ayu_clean_response(self):
        """Clean response should have no violations"""
        text = "やな姉様、あれは金閣寺ですよ。室町時代に建てられた建物です。"
        violations = check_ayu_forbidden(text)
        assert len(violations) == 0

    def test_yana_forbidden_anesama(self):
        """'姉様' should be detected for やな"""
        text = "姉様、これを見て！"
        violations = check_yana_forbidden(text)
        assert "姉様" in violations

    def test_yana_forbidden_desu(self):
        """'です' should be detected for やな"""
        text = "これは金閣寺です。"
        violations = check_yana_forbidden(text)
        assert "です" in violations

    def test_yana_forbidden_masu(self):
        """'ます' should be detected for やな"""
        text = "私はここが好きでします。"
        violations = check_yana_forbidden(text)
        # Note: 'ます' would be in 'でします' if present
        # Let's test a clear case
        text2 = "私もそう思います。"
        violations2 = check_yana_forbidden(text2)
        assert "ます" in violations2

    def test_yana_clean_response(self):
        """Clean response should have no violations for やな"""
        text = "わ、金色だ！すごいね、あゆ。"
        violations = check_yana_forbidden(text)
        assert len(violations) == 0


class TestDirectorEvaluation:
    """Tests for DirectorEvaluation with new fields"""

    def test_director_evaluation_new_fields(self):
        """DirectorEvaluation should have new fields"""
        eval_result = DirectorEvaluation(
            status=DirectorStatus.PASS,
            reason="Good response",
            next_pattern="A",
            next_instruction="次は質問してください",
            beat_stage="SETUP",
        )

        assert eval_result.next_pattern == "A"
        assert eval_result.next_instruction == "次は質問してください"
        assert eval_result.beat_stage == "SETUP"

    def test_director_evaluation_optional_fields(self):
        """New fields should be optional"""
        eval_result = DirectorEvaluation(
            status=DirectorStatus.PASS,
            reason="Good response",
        )

        assert eval_result.next_pattern is None
        assert eval_result.next_instruction is None
        assert eval_result.beat_stage is None


class TestEnums:
    """Tests for new enum types"""

    def test_beat_stage_enum(self):
        """BeatStage enum should have correct values"""
        assert BeatStage.SETUP.value == "SETUP"
        assert BeatStage.EXPLORATION.value == "EXPLORATION"
        assert BeatStage.PERSONAL.value == "PERSONAL"
        assert BeatStage.WRAP_UP.value == "WRAP_UP"

    def test_dialogue_pattern_enum(self):
        """DialoguePattern enum should have A-E values"""
        assert DialoguePattern.A.value == "A"
        assert DialoguePattern.B.value == "B"
        assert DialoguePattern.C.value == "C"
        assert DialoguePattern.D.value == "D"
        assert DialoguePattern.E.value == "E"


class TestValidateCharacterResponse:
    """Tests for comprehensive character validation"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset beat tracker before each test"""
        reset_beat_tracker()
        yield
        reset_beat_tracker()

    def test_validate_ayu_with_forbidden(self):
        """Validation should catch forbidden expressions for あゆ"""
        text = "いい観点ですね、姉様。"
        result = validate_character_response(text, "ayu")
        assert not result["is_valid"]
        assert "いい観点ですね" in result["forbidden_violations"]

    def test_validate_yana_with_forbidden(self):
        """Validation should catch forbidden expressions for やな"""
        text = "これは金閣寺です。"
        result = validate_character_response(text, "yana")
        assert not result["is_valid"]
        assert "です" in result["forbidden_violations"]

    def test_validate_ayu_clean(self):
        """Clean あゆ response should pass validation"""
        text = "やな姉様、あれは反りという技法ですよ。鎌倉時代の建築なんです。"
        result = validate_character_response(text, "ayu")
        # May have other validation issues but should not have forbidden violations
        assert len(result["forbidden_violations"]) == 0

    def test_validate_yana_clean(self):
        """Clean やな response should pass validation"""
        text = "わ、あの屋根の形、変わってるね。なんか反ってる？"
        result = validate_character_response(text, "yana")
        # May have other validation issues but should not have forbidden violations
        assert len(result["forbidden_violations"]) == 0


class TestPatternSelection:
    """Tests for pattern selection logic"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset beat tracker before each test"""
        reset_beat_tracker()
        yield
        reset_beat_tracker()

    def test_pattern_sequence_no_triple_repeat(self):
        """Pattern selection should never allow 3 consecutive same patterns"""
        tracker = get_beat_tracker()
        patterns_used = []

        # Simulate 10 turns of pattern selection
        for turn in range(1, 11):
            suggested = tracker.suggest_pattern(turn, patterns_used)
            patterns_used.append(suggested)

            # Check no triple repeats
            if len(patterns_used) >= 3:
                last_three = patterns_used[-3:]
                assert not (last_three[0] == last_three[1] == last_three[2]), \
                    f"Triple repeat detected: {last_three}"

    def test_pattern_variety_in_dialogue(self):
        """Dialogue should use variety of patterns"""
        tracker = get_beat_tracker()
        patterns_used = []

        # Simulate 10 turns
        for turn in range(1, 11):
            suggested = tracker.suggest_pattern(turn, patterns_used)
            patterns_used.append(suggested)

        # Should use at least 2 different patterns
        unique_patterns = set(patterns_used)
        assert len(unique_patterns) >= 2, \
            f"Too little variety: only used {unique_patterns}"
