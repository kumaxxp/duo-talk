"""
Reviewer: Quality control for character responses.

Checks for tone consistency, knowledge domain violations,
redundancy, logical consistency, and safety issues.
"""

import re
from typing import List, Optional
from dataclasses import dataclass

from src.validator import Validator


@dataclass
class ReviewIssue:
    """A single review issue"""
    issue_type: str  # "tone_drift", "redundancy", "contradiction", "safety", etc.
    severity: str    # "critical", "high", "medium", "low"
    message: str
    suggestion: Optional[str] = None
    location: Optional[str] = None  # e.g., "line 2", "last sentence"


@dataclass
class ReviewResult:
    """Result of a review"""
    is_pass: bool
    issues: List[ReviewIssue]
    summary: str
    fix_suggestions: List[str]


class Reviewer:
    """Quality control for character responses"""

    # Tone markers for each character
    TONE_MARKERS = {
        "A": ["ね", "よ", "だよ", "だね", "へ", "わ", "ウケる", "ちょっと待てよ"],
        "B": ["な", "ぞ", "ぞ", "ちょっと待て", "なるほど", "わかりました"],
    }

    # Forbidden expressions (consensus, summaries)
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

    # Safety keywords
    SAFETY_RED_FLAGS = [
        r"自傷",
        r"自殺",
        r"医学的に",
        r"法的に",
        r"個人情報",
        r"クレジット",
    ]

    @staticmethod
    def review(
        text: str,
        char_id: str,
        history: List[str] = None,
        frame_description: str = None,
    ) -> ReviewResult:
        """
        Comprehensive review of a character's response.

        Args:
            text: Response text to review
            char_id: "A" or "B"
            history: Previous responses (for consistency check)
            frame_description: Current frame description (for relevance check)

        Returns:
            ReviewResult with all detected issues
        """
        issues = []

        # Check 1: Tone consistency
        tone_issues = Reviewer._check_tone(text, char_id)
        issues.extend(tone_issues)

        # Check 2: Forbidden words
        forbidden_issues = Reviewer._check_forbidden_words(text)
        issues.extend(forbidden_issues)

        # Check 3: Safety red flags
        safety_issues = Reviewer._check_safety(text)
        issues.extend(safety_issues)

        # Check 4: Redundancy
        redundancy_issues = Reviewer._check_redundancy(text)
        issues.extend(redundancy_issues)

        # Check 5: Length
        length_issues = Reviewer._check_length(text)
        issues.extend(length_issues)

        # Check 6: Consistency with history
        if history:
            consistency_issues = Reviewer._check_consistency(text, char_id, history)
            issues.extend(consistency_issues)

        # Check 7: Relevance to frame
        if frame_description:
            relevance_issues = Reviewer._check_relevance(text, frame_description)
            issues.extend(relevance_issues)

        # Determine overall pass/fail
        critical_issues = [i for i in issues if i.severity == "critical"]
        is_pass = len(critical_issues) == 0 and len([i for i in issues if i.severity == "high"]) == 0

        # Build summary
        summary = Reviewer._build_summary(issues, char_id)

        # Build fix suggestions
        fix_suggestions = [i.suggestion for i in issues if i.suggestion]

        return ReviewResult(
            is_pass=is_pass,
            issues=issues,
            summary=summary,
            fix_suggestions=fix_suggestions,
        )

    @staticmethod
    def _check_tone(text: str, char_id: str) -> List[ReviewIssue]:
        """Check if text has character-appropriate tone markers"""
        issues = []

        if char_id not in Reviewer.TONE_MARKERS:
            return issues

        markers = Reviewer.TONE_MARKERS[char_id]
        has_marker = any(m in text for m in markers)

        if not has_marker:
            issues.append(ReviewIssue(
                issue_type="tone_drift",
                severity="high",
                message=f"Missing tone markers for character {char_id}",
                suggestion=f"Use: {', '.join(markers[:3])}",
                location="entire response",
            ))

        return issues

    @staticmethod
    def _check_forbidden_words(text: str) -> List[ReviewIssue]:
        """Check for forbidden consensus/summary expressions"""
        issues = []

        found_forbidden = []
        for word in Reviewer.FORBIDDEN_WORDS:
            if word in text:
                found_forbidden.append(word)

        if found_forbidden:
            issues.append(ReviewIssue(
                issue_type="forbidden_words",
                severity="high",
                message=f"Contains forbidden summary expressions: {', '.join(found_forbidden)}",
                suggestion="Remove or replace with more natural continuations",
                location=text,
            ))

        return issues

    @staticmethod
    def _check_safety(text: str) -> List[ReviewIssue]:
        """Check for safety red flags"""
        issues = []

        for pattern in Reviewer.SAFETY_RED_FLAGS:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append(ReviewIssue(
                    issue_type="safety",
                    severity="critical",
                    message=f"Potential safety issue detected: {pattern}",
                    suggestion="Review and remove unsafe content",
                    location="entire response",
                ))

        return issues

    @staticmethod
    def _check_redundancy(text: str) -> List[ReviewIssue]:
        """Check for redundant or repetitive phrasing"""
        issues = []

        sentences = text.split("。")
        if len(sentences) > 1:
            # Check for repeated sentence structures
            for i, sent1 in enumerate(sentences[:-1]):
                for sent2 in sentences[i+1:]:
                    # Simple similarity: share > 50% of tokens
                    tokens1 = set(sent1.split())
                    tokens2 = set(sent2.split())
                    if tokens1 and tokens2:
                        overlap = len(tokens1 & tokens2) / max(len(tokens1), len(tokens2))
                        if overlap > 0.5:
                            issues.append(ReviewIssue(
                                issue_type="redundancy",
                                severity="medium",
                                message="Redundant or repetitive phrasing detected",
                                suggestion="Vary sentence structure and vocabulary",
                                location=f"sentences {i} and {i+1}",
                            ))
                            break

        return issues

    @staticmethod
    def _check_length(text: str) -> List[ReviewIssue]:
        """Check response length"""
        issues = []

        sentence_count = len([s for s in text.split("。") if s.strip()])

        if sentence_count > 5:
            issues.append(ReviewIssue(
                issue_type="length",
                severity="high",
                message=f"Response too long: {sentence_count} sentences (max 5)",
                suggestion="Shorten to 2-4 sentences",
                location="entire response",
            ))
        elif sentence_count == 0:
            issues.append(ReviewIssue(
                issue_type="empty",
                severity="critical",
                message="Empty response",
                suggestion="Generate a non-empty response",
                location="entire response",
            ))

        return issues

    @staticmethod
    def _check_consistency(text: str, char_id: str, history: List[str]) -> List[ReviewIssue]:
        """Check consistency with previous responses"""
        issues = []

        if not history or len(history) == 0:
            return issues

        # Simple check: if last response mentioned a topic, don't contradict it
        last_response = history[-1] if history else ""

        # Check for direct contradictions (e.g., "I don't know X" then "X is...")
        contradiction_patterns = [
            (r"(詳しくない|わかりません|知りません)", r"(\w+)は(.+)"),  # "don't know X" then "X is..."
        ]

        for neg_pattern, pos_pattern in contradiction_patterns:
            if re.search(neg_pattern, last_response) and re.search(pos_pattern, text):
                issues.append(ReviewIssue(
                    issue_type="contradiction",
                    severity="high",
                    message="Possible contradiction with previous statement",
                    suggestion="Ensure consistency with previous response",
                    location="entire response",
                ))
                break

        return issues

    @staticmethod
    def _check_relevance(text: str, frame_description: str) -> List[ReviewIssue]:
        """Check if response is relevant to the current frame"""
        issues = []

        # Simple relevance check: do they share common keywords?
        frame_tokens = set(frame_description.split())
        response_tokens = set(text.split())

        overlap = len(frame_tokens & response_tokens)
        total_frame_tokens = len(frame_tokens)

        if total_frame_tokens > 0:
            relevance_score = overlap / total_frame_tokens

            if relevance_score < 0.1:  # Very low relevance
                issues.append(ReviewIssue(
                    issue_type="relevance",
                    severity="medium",
                    message="Response seems disconnected from the current frame",
                    suggestion="Address specific aspects of the frame description",
                    location="entire response",
                ))

        return issues

    @staticmethod
    def _build_summary(issues: List[ReviewIssue], char_id: str) -> str:
        """Build a summary of review results"""
        if not issues:
            return f"✅ Character {char_id} response passed review"

        critical = len([i for i in issues if i.severity == "critical"])
        high = len([i for i in issues if i.severity == "high"])
        medium = len([i for i in issues if i.severity == "medium"])

        summary = f"Review issues for character {char_id}: "
        parts = []
        if critical:
            parts.append(f"{critical} critical")
        if high:
            parts.append(f"{high} high")
        if medium:
            parts.append(f"{medium} medium")

        summary += ", ".join(parts)
        return summary
