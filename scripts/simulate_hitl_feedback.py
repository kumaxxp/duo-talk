#!/usr/bin/env python3
"""
Simulate feedback collection for HITL testing

This script simulates user feedback on narration outputs
to demonstrate the HITL feedback loop system.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feedback_analyzer import FeedbackAnalyzer
from src.logger import get_logger

def simulate_feedback():
    """Simulate realistic feedback scenarios"""
    print("=" * 70)
    print("🎬 SIMULATING HITL FEEDBACK COLLECTION")
    print("=" * 70)

    # Sample feedback scenarios
    feedback_samples = [
        {
            "run_id": "run_001",
            "turn_num": 2,
            "speaker": "A",
            "issue_type": "tone_drift",
            "description": "やなの感情マーカー「わ！」「へ？」が少なかった",
            "suggested_fix": "より感情的な反応を増やす",
        },
        {
            "run_id": "run_001",
            "turn_num": 4,
            "speaker": "B",
            "issue_type": "knowledge_overstep",
            "description": "あゆがガジェット・GPU について話し始めてしまった（バイト中）",
            "suggested_fix": "テック知識は観光ナレーション中は避ける",
        },
        {
            "run_id": "run_002",
            "turn_num": 1,
            "speaker": "A",
            "issue_type": "character_break",
            "description": "やなが敬語を使ってしまった（キャラ崩壊）",
            "suggested_fix": "カジュアルな日本語に統一する",
        },
        {
            "run_id": "run_002",
            "turn_num": 3,
            "speaker": "B",
            "issue_type": "tone_drift",
            "description": "あゆが「です」マーカーなしで話している",
            "suggested_fix": "敬語マーカーを常に含める",
        },
        {
            "run_id": "run_003",
            "turn_num": 2,
            "speaker": "A",
            "issue_type": "slow_progress",
            "description": "やなの応答が短すぎて観光地の説明が進まない",
            "suggested_fix": "もっと詳しく、複数の視点から説明する",
        },
        {
            "run_id": "run_003",
            "turn_num": 5,
            "speaker": "B",
            "issue_type": "tone_drift",
            "description": "あゆが「姉様」を使わずに名前で呼んでしまった",
            "suggested_fix": "必ず「姉様」で呼びかける",
        },
        {
            "run_id": "run_004",
            "turn_num": 1,
            "speaker": "A",
            "issue_type": "tone_drift",
            "description": "やなの声がカジュアル過ぎて子どもっぽい",
            "suggested_fix": "大人っぽいトーンを保つ",
        },
        {
            "run_id": "run_004",
            "turn_num": 3,
            "speaker": "B",
            "issue_type": "knowledge_overstep",
            "description": "あゆが建築知識を大きくはみ出して家具の話をしている",
            "suggested_fix": "建築・地理・歴史・科学の範囲内に留める",
        },
    ]

    logger = get_logger()

    print(f"\n📝 Recording {len(feedback_samples)} feedback samples...")
    for i, feedback in enumerate(feedback_samples, 1):
        FeedbackAnalyzer.record_feedback(
            run_id=feedback["run_id"],
            turn_num=feedback["turn_num"],
            speaker=feedback["speaker"],
            issue_type=feedback["issue_type"],
            description=feedback["description"],
            suggested_fix=feedback["suggested_fix"],
        )
        print(
            f"  [{i}] {feedback['run_id']} - Turn {feedback['turn_num']} "
            f"({feedback['speaker']}) - {feedback['issue_type']}"
        )

    print("\n✅ Feedback simulation complete")
    print("=" * 70)

    # Show summary
    print("\n【Feedback Summary】")
    trends = FeedbackAnalyzer.analyze_trends()
    by_char = FeedbackAnalyzer.analyze_by_character()

    if trends:
        print("\nIssue Distribution:")
        total = sum(trends.values())
        for issue_type, count in sorted(trends.items(), key=lambda x: x[1], reverse=True):
            percent = (count / total * 100) if total > 0 else 0
            print(f"  {issue_type:20} {count:3} ({percent:5.1f}%)")

    if by_char:
        print("\nBy Character:")
        for char_id in ["A", "B"]:
            if char_id in by_char:
                print(f"  Character {char_id}:")
                for issue, count in sorted(
                    by_char[char_id].items(), key=lambda x: x[1], reverse=True
                ):
                    print(f"    - {issue}: {count}")

if __name__ == "__main__":
    simulate_feedback()
