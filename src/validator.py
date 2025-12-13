"""
Validation module for character responses.
"""

import unicodedata
import re
from typing import List

from src.types import ValidationResult


class Validator:
    """Validates character responses"""

    # Character tone markers
    TONE_MARKERS = {
        "A": ["ね", "よ", "だよ", "だね", "へ", "わ", "ウケる", "ちょっと待てよ"],
        "B": ["な", "ぞ", "か", "なるほど", "ちょっと待て", "であろう", "かもしれない"],
    }

    # Forbidden expressions (to avoid consensus/summary)
    FORBIDDEN_WORDS = [
        "まとめると",
        "要するに",
        "結論として",
        "最終的に",
        "合意",
        "合意形成",
        "落としどころ",
        "振り返ると",
        "総括すると",
    ]

    @staticmethod
    def is_japanese_only(text: str) -> bool:
        """
        Check if text is primarily Japanese.
        Allows: Hiragana, Katakana, Kanji, CJK symbols, punctuation
        Disallows: Latin script (except for common abbreviations), unexpected languages
        """
        if not text:
            return False

        # Count character types
        cjk_count = 0
        hiragana_count = 0
        katakana_count = 0
        punctuation_count = 0
        other_count = 0

        for char in text:
            if ord(char) >= 0x4E00 and ord(char) <= 0x9FFF:  # Kanji
                cjk_count += 1
            elif ord(char) >= 0x3040 and ord(char) <= 0x309F:  # Hiragana
                hiragana_count += 1
            elif ord(char) >= 0x30A0 and ord(char) <= 0x30FF:  # Katakana
                katakana_count += 1
            elif char in "。、！？ 　\n\t,\":;()[]{}":  # Japanese punctuation & spaces
                punctuation_count += 1
            elif char.isdigit() or (char.isascii() and char.isalpha()):
                other_count += 1
            else:
                other_count += 1

        total = len(text)
        jp_ratio = (cjk_count + hiragana_count + katakana_count + punctuation_count) / total

        # Japanese should be > 80%
        return jp_ratio >= 0.8

    @staticmethod
    def has_tone_markers(text: str, char_id: str) -> bool:
        """Check if text has expected tone markers"""
        if char_id not in Validator.TONE_MARKERS:
            return True

        markers = Validator.TONE_MARKERS[char_id]
        return any(marker in text for marker in markers)

    @staticmethod
    def contains_forbidden_words(text: str) -> bool:
        """Check for consensus/summary words"""
        return any(word in text for word in Validator.FORBIDDEN_WORDS)

    @staticmethod
    def validate(
        text: str,
        char_id: str,
        prev_texts: List[str] = None,
    ) -> ValidationResult:
        """
        Validate a character response.

        Args:
            text: Response text to validate
            char_id: "A" or "B"
            prev_texts: Previous responses for consistency check

        Returns:
            ValidationResult with detailed feedback
        """
        issues = []
        suggestions = []

        # Check 1: Language (Japanese only)
        language_check = Validator.is_japanese_only(text)
        if not language_check:
            issues.append("Non-Japanese content detected")
            suggestions.append("Please respond entirely in Japanese")

        # Check 2: Tone consistency
        tone_check = Validator.has_tone_markers(text, char_id)
        if not tone_check:
            issues.append(f"Missing tone markers for character {char_id}")
            suggestions.append(
                f"Try using: {', '.join(Validator.TONE_MARKERS[char_id][:3])}"
            )

        # Check 3: Forbidden words (consensus)
        has_forbidden = Validator.contains_forbidden_words(text)
        if has_forbidden:
            issues.append("Contains consensus/summary expressions")
            suggestions.append("Avoid conclusions and summaries; keep the discussion flowing")

        # Check 4: Basic consistency (length, not empty, etc.)
        consistency_check = len(text) > 0 and len(text) < 1000

        # Overall validation
        is_valid = language_check and tone_check and consistency_check and not has_forbidden

        return ValidationResult(
            is_valid=is_valid,
            language_check=language_check,
            tone_check=tone_check,
            consistency_check=consistency_check,
            issues=issues,
            suggestions=suggestions,
        )
