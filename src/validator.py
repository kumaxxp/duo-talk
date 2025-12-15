"""
Validation module for character responses.
"""

import unicodedata
import re
from typing import List

from src.types import ValidationResult
from src.beat_tracker import get_beat_tracker


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


def check_forbidden_expressions(text: str, character: str) -> list[str]:
    """
    Check for forbidden expressions specific to each character.

    Args:
        text: Text to check
        character: "char_a" / "A" / "yana" for やな, or "char_b" / "B" / "ayu" for あゆ

    Returns:
        List of forbidden expressions found (empty if none)
    """
    beat_tracker = get_beat_tracker()
    forbidden = beat_tracker.get_forbidden_expressions(character)

    violations = []
    for expr in forbidden:
        if expr in text:
            violations.append(expr)

    return violations


def check_ayu_forbidden(text: str) -> list[str]:
    """
    Check for forbidden expressions specific to あゆ (younger sister).

    Forbidden expressions:
    - 「いい観点ですね」
    - 「いい質問ですね」
    - 「さすがですね」
    - 「鋭いですね」
    - 「おっしゃる通りです」
    - 「という背景があります」
    - 「という特徴があります」
    - 「という意味があります」

    Args:
        text: Text to check

    Returns:
        List of forbidden expressions found
    """
    return check_forbidden_expressions(text, "ayu")


def check_yana_forbidden(text: str) -> list[str]:
    """
    Check for forbidden expressions specific to やな (elder sister).

    Forbidden expressions:
    - 「姉様」（自分が姉なので使えない）
    - 「やな姉様」（同上）
    - 「です」（敬語を使わない）
    - 「ます」（敬語を使わない）

    Args:
        text: Text to check

    Returns:
        List of forbidden expressions found
    """
    return check_forbidden_expressions(text, "yana")


def validate_character_response(
    text: str,
    character: str,
    prev_texts: list[str] | None = None,
) -> dict:
    """
    Comprehensive validation of a character response.

    Combines standard validation with forbidden expression checks.

    Args:
        text: Response text to validate
        character: "char_a" / "A" for やな, "char_b" / "B" for あゆ
        prev_texts: Previous responses for consistency check

    Returns:
        Dictionary with validation results:
        {
            "is_valid": bool,
            "validation_result": ValidationResult,
            "forbidden_violations": list[str],
            "all_issues": list[str]
        }
    """
    # Normalize character ID
    char_id = "A" if character.lower() in ("char_a", "a", "yana") else "B"

    # Standard validation
    validation_result = Validator.validate(text, char_id, prev_texts)

    # Forbidden expression check
    forbidden_violations = check_forbidden_expressions(text, character)

    # Combine issues
    all_issues = validation_result.issues.copy()
    if forbidden_violations:
        all_issues.append(f"禁止表現を検出: {', '.join(forbidden_violations)}")

    # Overall validity
    is_valid = validation_result.is_valid and len(forbidden_violations) == 0

    return {
        "is_valid": is_valid,
        "validation_result": validation_result,
        "forbidden_violations": forbidden_violations,
        "all_issues": all_issues,
    }
