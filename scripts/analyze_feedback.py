#!/usr/bin/env python3
"""
Analyze feedback trends and generate insights.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feedback_analyzer import FeedbackAnalyzer


def main():
    """Main analysis"""
    print("\n" + "=" * 60)
    print("📊 Feedback Analysis Tool")
    print("=" * 60)

    # Generate and print report
    report = FeedbackAnalyzer.generate_report()
    print(report)

    # Export data for improvement
    print("\n【Detailed Feedback Samples】\n")

    trends = FeedbackAnalyzer.analyze_trends()
    if trends:
        top_issue = list(trends.keys())[0]
        samples = FeedbackAnalyzer.get_sample_feedback(top_issue, limit=3)

        if samples:
            print(f"Top issue: {top_issue}")
            print(f"Sample feedback ({len(samples)} items):\n")

            for i, feedback in enumerate(samples, 1):
                print(f"  [{i}] Speaker: {feedback.get('speaker')}")
                print(f"      Issue: {feedback.get('issue_type')}")
                print(f"      Description: {feedback.get('description')}")
                if feedback.get('suggested_fix'):
                    print(f"      Suggestion: {feedback.get('suggested_fix')}")
                print()

    # Interactive options
    print("=" * 60)
    print("Options:")
    print("  'export' - Export all feedback as JSON")
    print("  'clear'  - Clear feedback (cannot undo!)")
    print("  'quit'   - Exit")

    while True:
        choice = input("\nYour choice: ").strip().lower()

        if choice == "quit":
            break
        elif choice == "export":
            _export_feedback()
        elif choice == "clear":
            if _confirm_clear():
                _clear_feedback()

    return 0


def _export_feedback():
    """Export feedback to file"""
    from src.config import config
    import json

    feedback_file = config.log_dir / "feedback.jsonl"

    if not feedback_file.exists():
        print("⚠️  No feedback to export")
        return

    output_file = config.log_dir / "feedback_export.json"

    data = []
    with open(feedback_file, encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
                if event.get("event") == "feedback":
                    data.append(event)
            except json.JSONDecodeError:
                continue

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Exported {len(data)} feedback items to {output_file}")


def _confirm_clear():
    """Confirm feedback clearing"""
    confirm = input("⚠️  Clear all feedback? This cannot be undone. (yes/no): ").strip().lower()
    return confirm == "yes"


def _clear_feedback():
    """Clear all feedback"""
    from src.config import config

    feedback_file = config.log_dir / "feedback.jsonl"

    if feedback_file.exists():
        feedback_file.unlink()
        print("✅ Feedback cleared")
    else:
        print("⚠️  No feedback to clear")


if __name__ == "__main__":
    sys.exit(main())
