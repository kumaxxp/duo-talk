#!/usr/bin/env python3
"""
Commentary Script v3.0 - UnifiedPipeline統合版

UnifiedPipeline.run() を使用したバッチ対話生成。

v3.0 変更点:
- UnifiedPipeline.run() を使用
- Character.speak() の直接呼び出しを廃止
- 重複コンポーネント（Director評価等）をUnifiedPipelineに委譲

使用方法:
    python scripts/run_commentary.py "テーマ1" "テーマ2" ...
    python scripts/run_commentary.py --turns 8 "今日の天気について"
    python scripts/run_commentary.py --jetracer "コーナーに進入中"
"""

import sys
import argparse
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.unified_pipeline import UnifiedPipeline, DialogueResult
from src.input_source import InputBundle, InputSource, SourceType
from src.config import config


def run_commentary(
    topics: list,
    max_turns: int = 8,
    jetracer_mode: bool = False,
) -> list:
    """
    複数のトピックに対して対話を生成

    Args:
        topics: トピック（フレーム説明）のリスト
        max_turns: トピックあたりの最大ターン数
        jetracer_mode: JetRacerモードを強制するか

    Returns:
        DialogueResultのリスト
    """
    # UnifiedPipeline初期化
    pipeline = UnifiedPipeline(jetracer_mode=jetracer_mode)

    results = []

    print(f"\n🎬 Starting commentary (UnifiedPipeline v3.0)")
    print(f"📹 Topics: {len(topics)}")
    print(f"🔄 Max turns per topic: {max_turns}")
    print(f"🎮 Mode: {'JetRacer' if jetracer_mode else 'General Conversation'}\n")

    for i, topic in enumerate(topics, 1):
        print(f"\n{'='*60}")
        topic_preview = topic[:50] + "..." if len(topic) > 50 else topic
        print(f"Topic {i}/{len(topics)}: {topic_preview}")
        print(f"{'='*60}")

        # 入力バンドル作成
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content=topic)
        ])

        # 対話生成
        result = pipeline.run(
            initial_input=bundle,
            max_turns=max_turns,
        )

        results.append(result)

        # 結果表示
        print(f"\n💬 Dialogue ({len(result.dialogue)} turns):")
        for turn in result.dialogue:
            text = turn.text[:60] + "..." if len(turn.text) > 60 else turn.text
            status = ""
            if turn.evaluation and turn.evaluation.status.name != "PASS":
                status = f" [{turn.evaluation.status.name}]"
            print(f"   [{turn.speaker_name}] {text}{status}")

        if result.error:
            print(f"\n⚠️ Error: {result.error}")

    # サマリー
    print(f"\n{'='*60}")
    print(f"✅ Commentary completed")
    print(f"📊 Topics processed: {len(results)}")
    total_turns = sum(len(r.dialogue) for r in results)
    print(f"📊 Total turns: {total_turns}")

    # 成功/失敗カウント
    success_count = sum(1 for r in results if r.status == "success")
    error_count = sum(1 for r in results if r.status == "error")
    if error_count > 0:
        print(f"📊 Success: {success_count}, Errors: {error_count}")

    print(f"{'='*60}\n")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Commentary Script v3.0 (UnifiedPipeline)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 基本実行
    python scripts/run_commentary.py "今日の天気について話して"

    # 複数トピック
    python scripts/run_commentary.py "朝食の話" "昼食の話" "夕食の話"

    # ターン数指定
    python scripts/run_commentary.py --turns 4 "短い会話をして"

    # JetRacerモード
    python scripts/run_commentary.py --jetracer "コーナーに進入中"
        """
    )
    parser.add_argument(
        "topics",
        nargs="+",
        help="Topics or frame descriptions",
    )
    parser.add_argument(
        "--turns", "-t",
        type=int,
        default=8,
        help="Max turns per topic (default: 8)",
    )
    parser.add_argument(
        "--jetracer", "-j",
        action="store_true",
        help="Force JetRacer mode",
    )

    args = parser.parse_args()

    # 設定検証
    if not config.validate():
        print("⚠️  Warning: Some persona files are missing. Using defaults.")

    # 実行
    results = run_commentary(
        topics=args.topics,
        max_turns=args.turns,
        jetracer_mode=args.jetracer,
    )

    # エラーがあれば終了コード1
    has_error = any(r.status == "error" for r in results)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
