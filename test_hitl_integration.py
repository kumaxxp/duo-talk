#!/usr/bin/env python3
"""
Integration test for HITL feedback loop system
"""

from src.feedback_analyzer import FeedbackAnalyzer
from src.logger import get_logger
from src.config import config
from pathlib import Path

def test_hitl_integration():
    """Test complete HITL feedback loop"""
    print("=" * 70)
    print("HITL Integration Test")
    print("=" * 70)

    # Check config
    print(f"\n【Config Check】")
    print(f"Log directory: {config.log_dir}")
    print(f"Log directory exists: {config.log_dir.exists()}")

    # Record some feedback
    print(f"\n【Recording Feedback】")
    logger = get_logger()

    test_feedback = [
        {
            "run_id": "test_001",
            "turn_num": 1,
            "speaker": "A",
            "issue_type": "tone_drift",
            "description": "Test tone drift issue",
            "suggested_fix": "Add more emotion markers",
        },
        {
            "run_id": "test_001",
            "turn_num": 2,
            "speaker": "B",
            "issue_type": "knowledge_overstep",
            "description": "Test knowledge overstep",
            "suggested_fix": "Stay within domains",
        },
    ]

    for feedback in test_feedback:
        FeedbackAnalyzer.record_feedback(
            run_id=feedback["run_id"],
            turn_num=feedback["turn_num"],
            speaker=feedback["speaker"],
            issue_type=feedback["issue_type"],
            description=feedback["description"],
            suggested_fix=feedback["suggested_fix"],
        )
        print(f"  ✓ Recorded: {feedback['speaker']} - {feedback['issue_type']}")

    # Check feedback file
    feedback_file = config.log_dir / "feedback.jsonl"
    print(f"\n【Feedback File】")
    print(f"Feedback file path: {feedback_file}")
    print(f"Feedback file exists: {feedback_file.exists()}")

    if feedback_file.exists():
        with open(feedback_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            print(f"Number of feedback records: {len(lines)}")
            if lines:
                print(f"First record: {lines[0][:100]}...")

    # Analyze feedback
    print(f"\n【Analyzing Feedback】")
    trends = FeedbackAnalyzer.analyze_trends()
    by_char = FeedbackAnalyzer.analyze_by_character()

    print(f"Trends: {trends}")
    print(f"By character: {by_char}")

    # Generate report
    print(f"\n【Generating Report】")
    report = FeedbackAnalyzer.generate_report()
    print(report)

    print("\n✅ HITL Integration Test Complete")
    print("=" * 70)

if __name__ == "__main__":
    test_hitl_integration()
