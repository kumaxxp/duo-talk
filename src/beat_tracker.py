"""
Beat tracker for dialogue progression management.
Tracks dialogue beats and recommends patterns based on beat_policy.yaml.
"""

from pathlib import Path
from typing import Optional

import yaml


class BeatTracker:
    """Tracks dialogue beat progression and pattern selection"""

    def __init__(self, policy_path: str = "beats/beat_policy.yaml"):
        """
        Initialize BeatTracker with policy configuration.

        Args:
            policy_path: Path to beat_policy.yaml file
        """
        self.policy_path = Path(policy_path)
        self._load_policy()

    def _load_policy(self) -> None:
        """Load beat policy from YAML file"""
        if not self.policy_path.exists():
            raise FileNotFoundError(f"Beat policy file not found: {self.policy_path}")

        with open(self.policy_path, encoding="utf-8") as f:
            self.policy = yaml.safe_load(f)

        self.beats = self.policy.get("beats", [])
        self.patterns = self.policy.get("patterns", {})
        self.pattern_rules = self.policy.get("pattern_rules", {})
        self.forbidden_expressions = self.policy.get("forbidden_expressions", {})

    def get_current_beat(self, turn_number: int) -> str:
        """
        Determine the current beat stage based on turn number.

        Args:
            turn_number: Current turn number (1-indexed)

        Returns:
            Beat stage name: "SETUP", "EXPLORATION", "PERSONAL", or "WRAP_UP"
        """
        for beat in self.beats:
            turn_range = beat.get("turn_range", [0, 0])
            if turn_range[0] <= turn_number <= turn_range[1]:
                return beat.get("name", "SETUP")

        # Default to WRAP_UP for turns beyond defined range
        return "WRAP_UP"

    def get_beat_info(self, beat_stage: str) -> dict:
        """
        Get detailed information about a beat stage.

        Args:
            beat_stage: Beat stage name

        Returns:
            Beat information dictionary
        """
        for beat in self.beats:
            if beat.get("name") == beat_stage:
                return beat
        return {}

    def get_preferred_patterns(self, beat_stage: str) -> list[str]:
        """
        Get preferred dialogue patterns for a beat stage.

        Args:
            beat_stage: Beat stage name ("SETUP", "EXPLORATION", etc.)

        Returns:
            List of preferred pattern letters (e.g., ["A", "B"])
        """
        for beat in self.beats:
            if beat.get("name") == beat_stage:
                return beat.get("preferred_patterns", ["A", "B"])
        return ["A", "B"]

    def get_pattern_info(self, pattern: str) -> dict:
        """
        Get information about a specific dialogue pattern.

        Args:
            pattern: Pattern letter ("A", "B", "C", "D", "E")

        Returns:
            Pattern information dictionary
        """
        return self.patterns.get(pattern, {})

    def is_pattern_allowed(self, pattern: str, recent_patterns: list[str]) -> bool:
        """
        Check if a pattern can be used (not exceeding max consecutive uses).

        Args:
            pattern: Pattern to check
            recent_patterns: List of recently used patterns

        Returns:
            True if pattern is allowed, False if it would exceed max consecutive
        """
        max_consecutive = self.pattern_rules.get("max_consecutive", 2)

        if len(recent_patterns) < max_consecutive:
            return True

        # Check if the last N patterns are all the same as the proposed pattern
        recent_n = recent_patterns[-max_consecutive:]
        return not all(p == pattern for p in recent_n)

    def suggest_pattern(
        self,
        turn_number: int,
        recent_patterns: list[str],
    ) -> str:
        """
        Suggest a dialogue pattern for the current turn.

        Args:
            turn_number: Current turn number
            recent_patterns: List of recently used patterns

        Returns:
            Suggested pattern letter
        """
        beat_stage = self.get_current_beat(turn_number)
        preferred = self.get_preferred_patterns(beat_stage)

        # Try preferred patterns first
        for pattern in preferred:
            if self.is_pattern_allowed(pattern, recent_patterns):
                return pattern

        # Fallback: try any pattern that's allowed
        all_patterns = ["A", "B", "C", "D", "E"]
        for pattern in all_patterns:
            if self.is_pattern_allowed(pattern, recent_patterns):
                return pattern

        # Last resort: use fallback patterns from policy
        fallback = self.pattern_rules.get("fallback_on_stall", ["B", "C"])
        return fallback[0] if fallback else "A"

    def get_forbidden_expressions(self, character: str) -> list[str]:
        """
        Get forbidden expressions for a character.

        Args:
            character: "ayu" or "yana" (or "char_a" / "char_b")

        Returns:
            List of forbidden expressions
        """
        # Normalize character name
        char_key = character.lower()
        if char_key in ("char_a", "a", "yana"):
            char_key = "yana"
        elif char_key in ("char_b", "b", "ayu"):
            char_key = "ayu"

        return self.forbidden_expressions.get(char_key, [])


# Singleton instance
_beat_tracker: Optional[BeatTracker] = None


def get_beat_tracker(policy_path: str = "beats/beat_policy.yaml") -> BeatTracker:
    """
    Get or create BeatTracker singleton instance.

    Args:
        policy_path: Path to beat_policy.yaml

    Returns:
        BeatTracker instance
    """
    global _beat_tracker
    if _beat_tracker is None:
        _beat_tracker = BeatTracker(policy_path)
    return _beat_tracker


def reset_beat_tracker() -> None:
    """Reset the BeatTracker singleton (useful for testing)"""
    global _beat_tracker
    _beat_tracker = None
