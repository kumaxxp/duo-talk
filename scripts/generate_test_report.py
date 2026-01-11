import os
import sys
import json
from datetime import datetime
from typing import Set, Dict, Any, List, Optional
from dataclasses import dataclass

# Ensure we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.director import Director
from src.types import DirectorStatus

def generate_report():
    """Generate Markdown report for current tests."""
    director = Director(enable_fact_check=False)
    
    # Define test cases for the report
    cases = [
        {
            "name": "やなの通常発言 (PASS)",
            "speaker": "A",
            "text": "わ！ このお守り、すっごい可愛いじゃん！",
            "description": "口調マーカー、語彙、文体すべてを満たす完璧なパターン"
        },
        {
            "name": "やなの警告発言 (WARN)",
            "speaker": "A",
            "text": "そっか、それは楽しみだね。",
            "description": "「そっか」のみで語尾マーカー不足、口調スコア1のパターン"
        },
        {
            "name": "やなの最悪発言 (RETRY)",
            "speaker": "A",
            "text": "金閣寺は美しいと思います。",
            "description": "全くマーカーがなく、ですます口調になっているパターン"
        },
        {
            "name": "あゆの通常発言 (PASS)",
            "speaker": "B",
            "text": "つまり、これは江戸時代の建築様式ですね。非常に興味深いです。",
            "description": "論理的語彙と丁寧語2回以上を満たすパターン"
        },
        {
            "name": "あゆの褒め言葉警告 (WARN)",
            "speaker": "B",
            "text": "すごいですね。",
            "description": "評価語のみで使用"
        },
        {
            "name": "あゆの褒め言葉拒否 (RETRY)",
            "speaker": "B",
            "text": "あなたの考えは素晴らしいですね。",
            "description": "評価語 + 相手への肯定"
        },
        {
            "name": "散漫な応答 (WARN/RETRY)",
            "speaker": "B",
            "text": "Aについてです。Bの話をしましょう。Cも気になりますね。Dもいいですね。Eも検討しましょう。",
            "description": "多すぎる話題と文数"
        }
    ]

    report = "# ディレクター評価ロジック テスト成績表 (v4)\n\n"
    report += f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    report += "## 1. 判定基準サマリー\n\n"
    report += "| 判定 | スコア/条件 | アクション |\n"
    report += "| :--- | :--- | :--- |\n"
    report += "| **PASS** | スコア 2以上 | そのまま採用 |\n"
    report += "| **WARN** | スコア 1 または 軽微な違反 | 採用 + 次回介入で修正 |\n"
    report += "| **RETRY** | スコア 0 または 重大な違反 | 破棄 + 再生成 |\n\n"
    
    report += "## 2. 実行テスト結果\n\n"
    
    for case in cases:
        # Check hard rules logic
        tone = director._check_tone_markers(case["speaker"], case["text"])
        praise = director._check_praise_words(case["text"], case["speaker"])
        scatter = director._is_scattered_response(case["text"])
        
        # Determine overall from hard rules
        status = DirectorStatus.PASS
        
        if tone["status"] == DirectorStatus.RETRY: status = DirectorStatus.RETRY
        elif tone["status"] == DirectorStatus.WARN and status == DirectorStatus.PASS: status = DirectorStatus.WARN
        
        if praise["status"] == DirectorStatus.RETRY: status = DirectorStatus.RETRY
        elif praise["status"] == DirectorStatus.WARN and status == DirectorStatus.PASS: status = DirectorStatus.WARN
        
        if scatter["status"] == DirectorStatus.RETRY: status = DirectorStatus.RETRY
        elif scatter["status"] == DirectorStatus.WARN and status == DirectorStatus.PASS: status = DirectorStatus.WARN

        report += f"### {case['name']}\n\n"
        report += f"- **対象テキスト**: `{case['text']}`\n"
        report += f"- **意図**: {case['description']}\n"
        report += f"- **最終判定**: `{status.value if hasattr(status, 'value') else status}`\n\n"
        report += "#### 内訳（静的チェック）:\n"
        report += f"| チェック項目 | スコア/状態 | 詳細 |\n"
        report += f"| :--- | :--- | :--- |\n"
        report += f"| 口調 (Tone) | {tone.get('score', 0)} | {tone.get('issue') or 'OK'} |\n"
        report += f"| 褒め言葉 (Praise) | {praise.get('status', 'OK')} | {praise.get('issue') or 'OK'} |\n"
        report += f"| 散漫度 (Scatter) | {scatter.get('status', 'OK')} | {', '.join(scatter.get('issues', [])) if scatter.get('issues') else 'OK'} |\n\n"
        report += "---\n\n"

    report_path = "/home/owner/work/duo-talk/docs/テスト成績表_v4.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ Report generated: {report_path}")

if __name__ == "__main__":
    generate_report()
