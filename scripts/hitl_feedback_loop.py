#!/usr/bin/env python3
"""
HITL (Human-In-The-Loop) Feedback Loop System

This script:
1. Analyzes feedback from previous narration runs
2. Identifies patterns and recurring issues
3. Generates improvement suggestions
4. Updates character knowledge bases based on feedback
5. Provides summary reports for manual review
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feedback_analyzer import FeedbackAnalyzer
from src.knowledge_manager import get_knowledge_manager
from src.config import config
from src.llm_client import get_llm_client


class HITLFeedbackLoop:
    """Manages human-in-the-loop feedback and improvements"""

    def __init__(self):
        self.feedback_analyzer = FeedbackAnalyzer()
        self.llm = get_llm_client()
        self.km_a = get_knowledge_manager("A")
        self.km_b = get_knowledge_manager("B")

    def analyze_feedback_patterns(self) -> Dict:
        """Analyze feedback and identify patterns"""
        print("=" * 70)
        print("📊 HITL Feedback Analysis")
        print("=" * 70)

        trends = self.feedback_analyzer.analyze_trends()
        by_char = self.feedback_analyzer.analyze_by_character()
        top_issues = self.feedback_analyzer.get_topissues(limit=3)

        analysis = {
            "trends": trends,
            "by_character": by_char,
            "top_issues": top_issues,
        }

        # Print summary
        if trends:
            print("\n【Feedback Trends】")
            total = sum(trends.values())
            for issue_type, count in trends.items():
                percent = (count / total * 100) if total > 0 else 0
                print(f"  {issue_type}: {count} ({percent:.1f}%)")
        else:
            print("\nNo feedback recorded yet.")

        if by_char:
            print("\n【By Character】")
            for char_id in ["A", "B"]:
                if char_id in by_char:
                    print(f"  Character {char_id}:")
                    for issue_type, count in sorted(
                        by_char[char_id].items(),
                        key=lambda x: x[1],
                        reverse=True,
                    ):
                        print(f"    - {issue_type}: {count}")

        return analysis

    def suggest_improvements(self, issue_type: str = None) -> List[Dict]:
        """
        Generate improvement suggestions based on feedback.

        Args:
            issue_type: Optional filter (e.g., "tone_drift")

        Returns:
            List of improvement suggestions
        """
        print(f"\n【Generating Improvement Suggestions】")
        if issue_type:
            print(f"  Issue Type: {issue_type}")

        improvements = self.feedback_analyzer.export_for_improvement(
            issue_type=issue_type
        )

        suggestions = []

        if not improvements:
            print("  No feedback to improve from.")
            return suggestions

        # Group by character
        by_char = {"A": [], "B": []}
        for item in improvements:
            char = item.get("speaker", "unknown")
            if char in by_char:
                by_char[char].append(item)

        # Generate suggestions for each character
        for char_id in ["A", "B"]:
            if by_char[char_id]:
                print(f"\n  Character {char_id}: {len(by_char[char_id])} feedback items")

                # Summarize issues
                issues = [item["issue_type"] for item in by_char[char_id]]
                from collections import Counter

                issue_freq = Counter(issues)
                for issue, freq in issue_freq.most_common(3):
                    print(f"    - {issue}: {freq} occurrences")

                    # Create suggestion
                    suggestion = self._create_specific_suggestion(
                        char_id=char_id,
                        issue_type=issue,
                        samples=by_char[char_id][:3],
                    )
                    suggestions.append(suggestion)

        return suggestions

    def _create_specific_suggestion(
        self, char_id: str, issue_type: str, samples: List[Dict]
    ) -> Dict:
        """Create specific improvement suggestion based on issue type"""

        suggestion_text = ""

        if issue_type == "tone_drift":
            suggestion_text = f"""
Character {char_id} has tone inconsistency issues. Suggestions:
1. Review and strengthen tone markers in system_variable.txt
2. Add more character-specific tone examples
3. Increase tone consistency checks in templates

Sample feedback:
{self._format_samples(samples)}
"""

        elif issue_type == "knowledge_overstep":
            suggestion_text = f"""
Character {char_id} is discussing topics outside their domain. Suggestions:
1. Review knowledge domain boundaries in Director evaluation
2. Strengthen knowledge domain checks in character prompts
3. Add explicit "stay in domain" reminders

Sample feedback:
{self._format_samples(samples)}
"""

        elif issue_type == "slow_progress":
            suggestion_text = f"""
Character {char_id}'s dialogue is not progressing naturally. Suggestions:
1. Reduce response length constraints
2. Add more action-oriented prompts
3. Increase participation encouragement

Sample feedback:
{self._format_samples(samples)}
"""

        elif issue_type == "character_break":
            suggestion_text = f"""
Character {char_id} is breaking character. Suggestions:
1. Strengthen character consistency checks
2. Review system_fixed.txt for clarity
3. Add character-breaking detection in validator

Sample feedback:
{self._format_samples(samples)}
"""

        elif issue_type == "language_mix":
            suggestion_text = f"""
Character {char_id} is mixing languages. Suggestions:
1. Add explicit Japanese-only specification
2. Strengthen language purity validation
3. Add language-mixing detection filter

Sample feedback:
{self._format_samples(samples)}
"""

        else:
            suggestion_text = f"""
Character {char_id} has feedback that needs manual review:
{self._format_samples(samples)}
"""

        return {
            "character": char_id,
            "issue_type": issue_type,
            "suggestion": suggestion_text.strip(),
        }

    def _format_samples(self, samples: List[Dict]) -> str:
        """Format feedback samples for display"""
        lines = []
        for item in samples[:2]:
            lines.append(f"  - {item.get('description', 'No description')}")
            if item.get("suggested_fix"):
                lines.append(f"    (Fix: {item['suggested_fix']})")
        return "\n".join(lines)

    def apply_feedback_to_knowledge(
        self, char_id: str, issue_type: str, updates: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Apply feedback improvements to character knowledge base.

        Args:
            char_id: "A" or "B"
            issue_type: Type of issue being fixed
            updates: Dict of {topic: new_content}

        Returns:
            Dict of updated file paths
        """
        print(f"\n【Applying Feedback to Knowledge Base】")
        print(f"  Character: {char_id}")
        print(f"  Issue Type: {issue_type}")

        km = self.km_a if char_id == "A" else self.km_b
        results = {}

        for topic, content in updates.items():
            if km.get_knowledge(topic):
                # Update existing
                path = km.update_knowledge(topic, content)
                print(f"  ✓ Updated: {topic}")
            else:
                # Add new
                path = km.add_knowledge(
                    topic, content, doc_type="feedback_improvement", source="HITL"
                )
                print(f"  ✓ Added: {topic}")

            results[topic] = path

        return results

    def generate_hitl_report(self) -> str:
        """Generate comprehensive HITL feedback report"""
        lines = [
            "=" * 70,
            "📋 HITL FEEDBACK LOOP REPORT",
            "=" * 70,
            "",
        ]

        # 1. Feedback Analysis
        trends = self.feedback_analyzer.analyze_trends()
        by_char = self.feedback_analyzer.analyze_by_character()

        if trends:
            lines.append("【Feedback Summary】")
            total = sum(trends.values())
            lines.append(f"Total feedback items: {total}")
            lines.append("")

            lines.append("Issue Distribution:")
            for issue_type, count in sorted(
                trends.items(), key=lambda x: x[1], reverse=True
            ):
                bar_length = int(count / total * 20) if total > 0 else 0
                bar = "█" * bar_length
                lines.append(f"  {issue_type:20} {bar:20} {count}")
        else:
            lines.append("【Feedback Summary】")
            lines.append("No feedback recorded yet.")

        lines.append("")

        # 2. Character-specific insights
        lines.append("【Character-Specific Insights】")
        for char_id in ["A", "B"]:
            char_name = "澄ヶ瀬やな (姉)" if char_id == "A" else "澄ヶ瀬あゆ (妹)"
            lines.append(f"\n{char_id}: {char_name}")

            if char_id in by_char:
                issues = by_char[char_id]
                for issue, count in sorted(issues.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"  - {issue}: {count}")
            else:
                lines.append("  (No feedback yet)")

        lines.append("")

        # 3. Recommendations
        lines.append("【Recommendations】")
        if trends:
            top_issue = list(trends.keys())[0]
            if trends[top_issue] > 0:
                lines.append(f"\n1. Primary focus: {top_issue}")
                lines.append(f"   Occurrences: {trends[top_issue]}")
                lines.append("   Action: Review suggestions above for specific fixes")

        lines.append("")

        # 4. Next steps
        lines.append("【Next Steps】")
        lines.append("1. Review the suggestions generated for each issue type")
        lines.append("2. Manually apply fixes to character persona files")
        lines.append("3. Test improvements with new narration runs")
        lines.append("4. Collect feedback on improvements")
        lines.append("5. Iterate until issue frequency decreases")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)

    def export_improvement_plan(self, output_file: Path = None) -> str:
        """
        Export a structured improvement plan based on feedback.

        Returns:
            JSON string of improvement plan
        """
        if output_file is None:
            output_file = config.log_dir / "hitl_improvement_plan.json"

        analysis = self.analyze_feedback_patterns()
        suggestions = self.suggest_improvements()

        plan = {
            "analysis": analysis,
            "suggestions": suggestions,
            "export_date": str(Path(config.log_dir).stat().st_mtime),
            "next_steps": [
                "Review suggestions and decide on improvements",
                "Update character knowledge bases with fixes",
                "Run new narration tests",
                "Collect feedback on improvements",
            ],
        }

        # Write to file
        output_file.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n✓ Improvement plan exported: {output_file}")

        return json.dumps(plan, ensure_ascii=False, indent=2)

    def run_full_loop(self):
        """Run the complete HITL feedback loop"""
        print("\n" + "=" * 70)
        print("🔄 RUNNING FULL HITL FEEDBACK LOOP")
        print("=" * 70)

        # 1. Analyze feedback
        analysis = self.analyze_feedback_patterns()

        # 2. Generate suggestions
        suggestions = self.suggest_improvements()

        if suggestions:
            print("\n" + "=" * 70)
            for suggestion in suggestions:
                print(f"\n【Suggestion for Character {suggestion['character']}】")
                print(f"Issue: {suggestion['issue_type']}")
                print(suggestion["suggestion"])

        # 3. Generate report
        report = self.generate_hitl_report()
        print("\n" + report)

        # 4. Export plan
        self.export_improvement_plan()

        print("\n✅ HITL Feedback Loop Complete")
        print("=" * 70)


if __name__ == "__main__":
    loop = HITLFeedbackLoop()
    loop.run_full_loop()
