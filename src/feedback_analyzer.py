"""
Feedback analysis: process, categorize, and extract insights from user feedback.
"""

import json
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict, Counter

from src.config import config
from src.logger import get_logger


class FeedbackAnalyzer:
    """Analyzes feedback patterns and trends"""

    FEEDBACK_FILE = config.log_dir / "feedback.jsonl"

    # Valid issue types
    ISSUE_TYPES = [
        "tone_drift",
        "knowledge_overstep",
        "slow_progress",
        "character_break",
        "language_mix",
        "repetition",
        "contradiction",
        "other",
    ]

    @staticmethod
    def record_feedback(
        run_id: str,
        turn_num: int,
        speaker: str,
        issue_type: str,
        description: str,
        suggested_fix: str = None,
    ) -> None:
        """
        Record user feedback for a specific turn.

        Args:
            run_id: Run ID
            turn_num: Turn number
            speaker: "A" or "B"
            issue_type: Type of issue
            description: User's description
            suggested_fix: Optional suggestion
        """
        logger = get_logger()
        logger.log_feedback(
            run_id=run_id,
            turn_num=turn_num,
            speaker=speaker,
            issue_type=issue_type,
            description=description,
            suggested_fix=suggested_fix,
        )

    @staticmethod
    def analyze_trends() -> Dict[str, int]:
        """
        Analyze feedback trends (issue type frequency).

        Returns:
            Dict mapping issue_type to count
        """
        if not FeedbackAnalyzer.FEEDBACK_FILE.exists():
            return {}

        issue_counts = Counter()

        with open(FeedbackAnalyzer.FEEDBACK_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                    if event.get("event") == "feedback":
                        issue_type = event.get("issue_type", "other")
                        issue_counts[issue_type] += 1
                except json.JSONDecodeError:
                    continue

        return dict(sorted(issue_counts.items(), key=lambda x: x[1], reverse=True))

    @staticmethod
    def analyze_by_character() -> Dict[str, Dict[str, int]]:
        """
        Analyze feedback by character.

        Returns:
            Dict like {"A": {"tone_drift": 2, ...}, "B": {...}}
        """
        if not FeedbackAnalyzer.FEEDBACK_FILE.exists():
            return {}

        char_issues = defaultdict(lambda: Counter())

        with open(FeedbackAnalyzer.FEEDBACK_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                    if event.get("event") == "feedback":
                        speaker = event.get("speaker", "unknown")
                        issue_type = event.get("issue_type", "other")
                        char_issues[speaker][issue_type] += 1
                except json.JSONDecodeError:
                    continue

        # Convert defaultdict to dict
        return {k: dict(v) for k, v in char_issues.items()}

    @staticmethod
    def get_topissues(char_id: str = None, limit: int = 5) -> List[Tuple[str, int]]:
        """
        Get top issues, optionally filtered by character.

        Args:
            char_id: Optional character filter ("A" or "B")
            limit: Number of top issues to return

        Returns:
            List of (issue_type, count) tuples
        """
        if not FeedbackAnalyzer.FEEDBACK_FILE.exists():
            return []

        if char_id:
            char_data = FeedbackAnalyzer.analyze_by_character()
            counts = char_data.get(char_id, {})
            return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        else:
            trends = FeedbackAnalyzer.analyze_trends()
            return sorted(trends.items(), key=lambda x: x[1], reverse=True)[:limit]

    @staticmethod
    def generate_report() -> str:
        """
        Generate a human-readable feedback report.

        Returns:
            Report text
        """
        trends = FeedbackAnalyzer.analyze_trends()
        by_char = FeedbackAnalyzer.analyze_by_character()

        lines = [
            "=" * 60,
            "📊 FEEDBACK ANALYSIS REPORT",
            "=" * 60,
            "",
        ]

        # Overall trends
        if trends:
            lines.append("【Overall Trends】")
            total = sum(trends.values())
            for issue_type, count in trends.items():
                percent = (count / total * 100) if total > 0 else 0
                lines.append(f"  {issue_type}: {count} ({percent:.1f}%)")
        else:
            lines.append("No feedback recorded yet.")

        lines.append("")

        # By character
        if by_char:
            lines.append("【By Character】")
            for char_id in ["A", "B"]:
                if char_id in by_char:
                    lines.append(f"  Character {char_id}:")
                    char_issues = by_char[char_id]
                    for issue_type, count in sorted(char_issues.items(), key=lambda x: x[1], reverse=True):
                        lines.append(f"    - {issue_type}: {count}")

        lines.append("")

        # Recommendations
        if trends:
            lines.append("【Recommendations】")
            top_issue = list(trends.keys())[0]

            if top_issue == "tone_drift":
                lines.append("  → Update system_variable.txt with tone markers")
                lines.append("  → Add more diverse tone examples in templates.txt")

            elif top_issue == "knowledge_overstep":
                lines.append("  → Review character knowledge boundaries")
                lines.append("  → Refine director domain monitoring")

            elif top_issue == "slow_progress":
                lines.append("  → Increase participation prompts")
                lines.append("  → Shorten expected response length")

            elif top_issue == "character_break":
                lines.append("  → Strengthen character consistency checks")
                lines.append("  → Review system prompts for clarity")

            elif top_issue == "language_mix":
                lines.append("  → Add language purity check to validator")
                lines.append("  → Specify Japanese-only in system prompt")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)

    @staticmethod
    def export_for_improvement(issue_type: str = None) -> List[Dict]:
        """
        Export feedback suitable for prompt improvement.

        Args:
            issue_type: Optional filter (e.g., "tone_drift")

        Returns:
            List of feedback items formatted for LLM improvement
        """
        if not FeedbackAnalyzer.FEEDBACK_FILE.exists():
            return []

        improvements = []

        with open(FeedbackAnalyzer.FEEDBACK_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                    if event.get("event") == "feedback":
                        if issue_type and event.get("issue_type") != issue_type:
                            continue

                        improvements.append({
                            "speaker": event.get("speaker"),
                            "issue_type": event.get("issue_type"),
                            "description": event.get("description"),
                            "suggested_fix": event.get("suggested_fix"),
                        })
                except json.JSONDecodeError:
                    continue

        return improvements

    @staticmethod
    def get_sample_feedback(issue_type: str, limit: int = 3) -> List[Dict]:
        """
        Get sample feedback items for a specific issue type.

        Args:
            issue_type: Issue type to filter
            limit: Number of samples

        Returns:
            List of feedback items
        """
        improvements = FeedbackAnalyzer.export_for_improvement(issue_type=issue_type)
        return improvements[:limit]
