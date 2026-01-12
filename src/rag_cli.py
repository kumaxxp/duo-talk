"""
RAG CLI

Dual-RAG システムを操作するためのコマンドラインインターフェース。

使用例:
    # Style RAG
    python -m src.rag_cli style stats
    python -m src.rag_cli style search --character yana --query "成功"
    python -m src.rag_cli style add --character yana --emotion excited --situation "テスト" --example "やったー！"

    # Memory RAG
    python -m src.rag_cli memory stats
    python -m src.rag_cli memory search --query "テスト" --character yana
    python -m src.rag_cli memory add-episode --summary "テスト" --yana-perspective "やな" --ayu-perspective "あゆ" --emotional-tag success
    python -m src.rag_cli memory add-fact --summary "ユーザーの好み" --category preference
"""

import argparse
import json
import sys
import os
from pathlib import Path
from typing import List, Optional, TextIO

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.style_rag import StyleRAG, DataOrigin, get_style_rag, reset_style_rag
from src.memory_rag import MemoryRAG, FactCategory, get_memory_rag, reset_memory_rag


def create_parser() -> argparse.ArgumentParser:
    """CLIパーサーを作成"""
    parser = argparse.ArgumentParser(
        prog='rag-cli',
        description='Dual-RAG システム CLI'
    )

    parser.add_argument(
        '--db-path',
        type=str,
        default=None,
        help='データベースのベースパス'
    )

    subparsers = parser.add_subparsers(dest='command', help='コマンド')

    # === style コマンド ===
    style_parser = subparsers.add_parser('style', help='Style RAG操作')
    style_subparsers = style_parser.add_subparsers(dest='style_command', help='Style RAGサブコマンド')

    # style stats
    style_stats = style_subparsers.add_parser('stats', help='統計表示')
    style_stats.add_argument('--format', choices=['text', 'json'], default='text', help='出力形式')

    # style search
    style_search = style_subparsers.add_parser('search', help='スタイル検索')
    style_search.add_argument('--character', '-c', required=True, help='キャラクターID (yana/ayu)')
    style_search.add_argument('--query', '-q', required=True, help='検索クエリ')
    style_search.add_argument('--emotion', '-e', default=None, help='感情フィルタ')
    style_search.add_argument('--top-k', '-k', type=int, default=5, help='取得件数')
    style_search.add_argument('--format', choices=['text', 'json'], default='text', help='出力形式')

    # style add
    style_add = style_subparsers.add_parser('add', help='サンプル追加')
    style_add.add_argument('--character', '-c', required=True, help='キャラクターID')
    style_add.add_argument('--emotion', '-e', required=True, help='感情')
    style_add.add_argument('--situation', '-s', required=True, help='状況')
    style_add.add_argument('--example', '-x', required=True, help='セリフ例')

    # style export
    style_export = style_subparsers.add_parser('export', help='エクスポート')
    style_export.add_argument('--output', '-o', required=True, help='出力ディレクトリ')
    style_export.add_argument('--character', '-c', default=None, help='キャラクターID（省略時は全て）')

    # === memory コマンド ===
    memory_parser = subparsers.add_parser('memory', help='Memory RAG操作')
    memory_subparsers = memory_parser.add_subparsers(dest='memory_command', help='Memory RAGサブコマンド')

    # memory stats
    memory_stats = memory_subparsers.add_parser('stats', help='統計表示')
    memory_stats.add_argument('--format', choices=['text', 'json'], default='text', help='出力形式')

    # memory search
    memory_search = memory_subparsers.add_parser('search', help='記憶検索')
    memory_search.add_argument('--query', '-q', required=True, help='検索クエリ')
    memory_search.add_argument('--character', '-c', default='yana', help='視点キャラクター')
    memory_search.add_argument('--top-k', '-k', type=int, default=5, help='取得件数')
    memory_search.add_argument('--format', choices=['text', 'json'], default='text', help='出力形式')

    # memory add-episode
    memory_add_ep = memory_subparsers.add_parser('add-episode', help='エピソード追加')
    memory_add_ep.add_argument('--summary', '-s', required=True, help='エピソード要約')
    memory_add_ep.add_argument('--yana-perspective', required=True, help='やなの視点')
    memory_add_ep.add_argument('--ayu-perspective', required=True, help='あゆの視点')
    memory_add_ep.add_argument('--emotional-tag', '-t', default='routine', help='感情タグ')
    memory_add_ep.add_argument('--importance', '-i', type=float, default=0.5, help='重要度 (0.0-1.0)')

    # memory add-fact
    memory_add_fact = memory_subparsers.add_parser('add-fact', help='事実追加')
    memory_add_fact.add_argument('--summary', '-s', required=True, help='事実の要約')
    memory_add_fact.add_argument('--category', '-c', choices=['preference', 'experience', 'info'], default='info', help='カテゴリ')
    memory_add_fact.add_argument('--confidence', type=float, default=1.0, help='確信度 (0.0-1.0)')

    return parser


# === Style RAG コマンド実行関数 ===

def run_style_stats(
    style_rag: StyleRAG,
    output: TextIO = sys.stdout,
    format: str = 'text'
) -> None:
    """style stats コマンドを実行"""
    stats = style_rag.get_stats()

    if format == 'json':
        data = {
            'total_samples': stats.total_samples,
            'by_character': stats.by_character,
            'by_emotion': stats.by_emotion,
            'by_origin': stats.by_origin
        }
        output.write(json.dumps(data, ensure_ascii=False, indent=2))
        output.write('\n')
    else:
        output.write("=== Style RAG 統計 ===\n")
        output.write(f"総サンプル数: {stats.total_samples}\n")
        output.write("\nキャラクター別:\n")
        for char, count in stats.by_character.items():
            output.write(f"  {char}: {count}\n")
        output.write("\n感情別:\n")
        for emotion, count in stats.by_emotion.items():
            output.write(f"  {emotion}: {count}\n")
        output.write("\nデータソース別:\n")
        for origin, count in stats.by_origin.items():
            output.write(f"  {origin}: {count}\n")


def run_style_search(
    style_rag: StyleRAG,
    character: str,
    query: str,
    top_k: int = 5,
    emotion: Optional[str] = None,
    output: TextIO = sys.stdout,
    format: str = 'text'
) -> None:
    """style search コマンドを実行"""
    results = style_rag.retrieve(
        character_id=character,
        query=query,
        emotion=emotion,
        top_k=top_k
    )

    if format == 'json':
        data = [
            {
                'sample_id': r.sample_id,
                'character_id': r.character_id,
                'emotion': r.emotion,
                'situation': r.situation,
                'example': r.example,
                'data_origin': r.data_origin.value,
                'relevance_score': r.relevance_score
            }
            for r in results
        ]
        output.write(json.dumps(data, ensure_ascii=False, indent=2))
        output.write('\n')
    else:
        if not results:
            output.write("検索結果なし\n")
            return

        output.write(f"=== Style検索結果 ({len(results)}件) ===\n")
        for i, r in enumerate(results, 1):
            output.write(f"\n[{i}] {r.situation} / {r.emotion}\n")
            output.write(f"    例: {r.example}\n")
            output.write(f"    スコア: {r.relevance_score:.3f}\n")


def run_style_add(
    style_rag: StyleRAG,
    character: str,
    emotion: str,
    situation: str,
    example: str,
    output: TextIO = sys.stdout
) -> bool:
    """style add コマンドを実行"""
    sample_id = style_rag.add_from_feedback(
        character_id=character,
        example=example,
        situation=situation,
        emotion=emotion,
        feedback_type="positive"
    )

    if sample_id:
        output.write(f"サンプルを追加しました: {sample_id}\n")
        return True
    else:
        output.write("サンプルの追加に失敗しました（重複の可能性）\n")
        return False


def run_style_export(
    style_rag: StyleRAG,
    output_path: str,
    character: Optional[str] = None,
    output: TextIO = sys.stdout
) -> None:
    """style export コマンドを実行"""
    style_rag.export_samples(output_path, character_id=character)
    output.write(f"エクスポートしました: {output_path}\n")


# === Memory RAG コマンド実行関数 ===

def run_memory_stats(
    memory_rag: MemoryRAG,
    output: TextIO = sys.stdout,
    format: str = 'text'
) -> None:
    """memory stats コマンドを実行"""
    stats = memory_rag.get_stats()

    if format == 'json':
        data = {
            'total_episodes': stats.total_episodes,
            'total_facts': stats.total_facts,
            'episode_buffer_size': stats.episode_buffer_size,
            'fact_buffer_size': stats.fact_buffer_size,
            'by_emotional_tag': stats.by_emotional_tag,
            'by_fact_category': stats.by_fact_category
        }
        output.write(json.dumps(data, ensure_ascii=False, indent=2))
        output.write('\n')
    else:
        output.write("=== Memory RAG 統計 ===\n")
        output.write(f"エピソード数: {stats.total_episodes}\n")
        output.write(f"事実数: {stats.total_facts}\n")
        output.write(f"エピソードバッファ: {stats.episode_buffer_size}\n")
        output.write(f"事実バッファ: {stats.fact_buffer_size}\n")

        if stats.by_emotional_tag:
            output.write("\n感情タグ別:\n")
            for tag, count in stats.by_emotional_tag.items():
                output.write(f"  {tag}: {count}\n")

        if stats.by_fact_category:
            output.write("\nカテゴリ別:\n")
            for cat, count in stats.by_fact_category.items():
                output.write(f"  {cat}: {count}\n")


def run_memory_search(
    memory_rag: MemoryRAG,
    query: str,
    character: str = 'yana',
    top_k: int = 5,
    output: TextIO = sys.stdout,
    format: str = 'text'
) -> None:
    """memory search コマンドを実行"""
    result = memory_rag.search(
        query=query,
        character=character,
        top_k=top_k
    )

    if format == 'json':
        data = {
            'episodes': [
                {
                    'memory_id': ep.memory_id,
                    'summary': ep.summary,
                    'yana_perspective': ep.yana_perspective,
                    'ayu_perspective': ep.ayu_perspective,
                    'emotional_tag': ep.emotional_tag,
                    'importance': ep.importance,
                    'relevance_score': ep.relevance_score
                }
                for ep in result.episodes
            ],
            'facts': [
                {
                    'memory_id': f.memory_id,
                    'summary': f.summary,
                    'category': f.category.value,
                    'confidence': f.confidence,
                    'relevance_score': f.relevance_score
                }
                for f in result.facts
            ]
        }
        output.write(json.dumps(data, ensure_ascii=False, indent=2))
        output.write('\n')
    else:
        if not result.episodes and not result.facts:
            output.write("検索結果なし\n")
            return

        if result.episodes:
            output.write(f"=== エピソード ({len(result.episodes)}件) ===\n")
            for i, ep in enumerate(result.episodes, 1):
                output.write(f"\n[{i}] {ep.summary}\n")
                output.write(f"    {character}視点: {ep.yana_perspective if character == 'yana' else ep.ayu_perspective}\n")
                output.write(f"    タグ: {ep.emotional_tag}, 重要度: {ep.importance:.2f}\n")

        if result.facts:
            output.write(f"\n=== 事実 ({len(result.facts)}件) ===\n")
            for i, f in enumerate(result.facts, 1):
                output.write(f"\n[{i}] {f.summary}\n")
                output.write(f"    カテゴリ: {f.category.value}\n")


def run_memory_add_episode(
    memory_rag: MemoryRAG,
    summary: str,
    yana_perspective: str,
    ayu_perspective: str,
    emotional_tag: str = 'routine',
    importance: float = 0.5,
    output: TextIO = sys.stdout
) -> bool:
    """memory add-episode コマンドを実行"""
    memory_id = memory_rag.add_episode_direct(
        summary=summary,
        yana_perspective=yana_perspective,
        ayu_perspective=ayu_perspective,
        emotional_tag=emotional_tag,
        importance=importance
    )

    if memory_id:
        output.write(f"エピソードを追加しました: {memory_id}\n")
        return True
    else:
        output.write("エピソードの追加に失敗しました（重複の可能性）\n")
        return False


def run_memory_add_fact(
    memory_rag: MemoryRAG,
    summary: str,
    category: str = 'info',
    confidence: float = 1.0,
    output: TextIO = sys.stdout
) -> bool:
    """memory add-fact コマンドを実行"""
    memory_id = memory_rag.add_fact_direct(
        summary=summary,
        category=FactCategory(category),
        confidence=confidence
    )

    if memory_id:
        output.write(f"事実を追加しました: {memory_id}\n")
        return True
    else:
        output.write("事実の追加に失敗しました（重複の可能性）\n")
        return False


# === メイン関数 ===

def main(args: Optional[List[str]] = None) -> int:
    """CLI メインエントリポイント"""
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    # データベースパスの設定
    db_path = parsed_args.db_path or os.environ.get('RAG_DB_PATH', './memories')
    data_dir = str(project_root / "rag_data" / "style_samples")

    # コマンドの処理
    if parsed_args.command == 'style':
        # StyleRAG初期化
        style_rag = StyleRAG(
            db_path=str(Path(db_path) / "style_rag"),
            data_dir=data_dir
        )

        if parsed_args.style_command == 'stats':
            run_style_stats(style_rag, format=parsed_args.format)
        elif parsed_args.style_command == 'search':
            run_style_search(
                style_rag,
                character=parsed_args.character,
                query=parsed_args.query,
                top_k=parsed_args.top_k,
                emotion=getattr(parsed_args, 'emotion', None),
                format=parsed_args.format
            )
        elif parsed_args.style_command == 'add':
            run_style_add(
                style_rag,
                character=parsed_args.character,
                emotion=parsed_args.emotion,
                situation=parsed_args.situation,
                example=parsed_args.example
            )
        elif parsed_args.style_command == 'export':
            run_style_export(
                style_rag,
                output_path=parsed_args.output,
                character=getattr(parsed_args, 'character', None)
            )
        else:
            parser.print_help()
            return 1

    elif parsed_args.command == 'memory':
        # MemoryRAG初期化
        memory_rag = MemoryRAG(db_path=db_path)

        if parsed_args.memory_command == 'stats':
            run_memory_stats(memory_rag, format=parsed_args.format)
        elif parsed_args.memory_command == 'search':
            run_memory_search(
                memory_rag,
                query=parsed_args.query,
                character=parsed_args.character,
                top_k=parsed_args.top_k,
                format=parsed_args.format
            )
        elif parsed_args.memory_command == 'add-episode':
            run_memory_add_episode(
                memory_rag,
                summary=parsed_args.summary,
                yana_perspective=parsed_args.yana_perspective,
                ayu_perspective=parsed_args.ayu_perspective,
                emotional_tag=parsed_args.emotional_tag,
                importance=parsed_args.importance
            )
        elif parsed_args.memory_command == 'add-fact':
            run_memory_add_fact(
                memory_rag,
                summary=parsed_args.summary,
                category=parsed_args.category,
                confidence=getattr(parsed_args, 'confidence', 1.0)
            )
        else:
            parser.print_help()
            return 1

    else:
        parser.print_help()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
