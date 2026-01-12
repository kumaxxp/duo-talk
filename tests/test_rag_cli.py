"""
RAG CLI テスト

テスト駆動開発でCLIを実装するためのテストスイート。
"""

import pytest
import sys
import json
from pathlib import Path
from io import StringIO
from unittest.mock import patch, MagicMock

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestRagCLIImport:
    """CLIモジュールのインポートテスト"""

    def test_cli_module_exists(self):
        """CLIモジュールがインポートできる"""
        from src.rag_cli import main, create_parser
        assert callable(main)
        assert callable(create_parser)


class TestRagCLIParser:
    """CLIパーサーのテスト"""

    @pytest.fixture
    def parser(self):
        from src.rag_cli import create_parser
        return create_parser()

    def test_parser_has_subcommands(self, parser):
        """サブコマンドが定義されている"""
        # style コマンド
        args = parser.parse_args(['style', 'stats'])
        assert args.command == 'style'
        assert args.style_command == 'stats'

        # memory コマンド
        args = parser.parse_args(['memory', 'stats'])
        assert args.command == 'memory'
        assert args.memory_command == 'stats'

    def test_style_search_command(self, parser):
        """style search コマンドのパース"""
        args = parser.parse_args([
            'style', 'search',
            '--character', 'yana',
            '--query', '成功',
            '--top-k', '5'
        ])
        assert args.command == 'style'
        assert args.style_command == 'search'
        assert args.character == 'yana'
        assert args.query == '成功'
        assert args.top_k == 5

    def test_style_add_command(self, parser):
        """style add コマンドのパース"""
        args = parser.parse_args([
            'style', 'add',
            '--character', 'yana',
            '--emotion', 'excited',
            '--situation', 'テスト',
            '--example', 'やったー！'
        ])
        assert args.command == 'style'
        assert args.style_command == 'add'
        assert args.character == 'yana'
        assert args.emotion == 'excited'
        assert args.situation == 'テスト'
        assert args.example == 'やったー！'

    def test_memory_search_command(self, parser):
        """memory search コマンドのパース"""
        args = parser.parse_args([
            'memory', 'search',
            '--query', 'テスト',
            '--character', 'yana',
            '--top-k', '3'
        ])
        assert args.command == 'memory'
        assert args.memory_command == 'search'
        assert args.query == 'テスト'
        assert args.character == 'yana'
        assert args.top_k == 3

    def test_memory_add_episode_command(self, parser):
        """memory add-episode コマンドのパース"""
        args = parser.parse_args([
            'memory', 'add-episode',
            '--summary', 'テストエピソード',
            '--yana-perspective', 'やなの視点',
            '--ayu-perspective', 'あゆの視点',
            '--emotional-tag', 'success',
            '--importance', '0.8'
        ])
        assert args.command == 'memory'
        assert args.memory_command == 'add-episode'
        assert args.summary == 'テストエピソード'
        assert args.yana_perspective == 'やなの視点'
        assert args.ayu_perspective == 'あゆの視点'
        assert args.emotional_tag == 'success'
        assert args.importance == 0.8

    def test_memory_add_fact_command(self, parser):
        """memory add-fact コマンドのパース"""
        args = parser.parse_args([
            'memory', 'add-fact',
            '--summary', 'ユーザーの好み',
            '--category', 'preference'
        ])
        assert args.command == 'memory'
        assert args.memory_command == 'add-fact'
        assert args.summary == 'ユーザーの好み'
        assert args.category == 'preference'


class TestStyleCommands:
    """Style コマンドの実行テスト"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """テスト用のセットアップ"""
        from src.style_rag import reset_style_rag, StyleRAG

        reset_style_rag()

        # テスト用のStyleRAGを作成
        self.style_rag = StyleRAG(
            db_path=str(tmp_path / "style_rag"),
            data_dir=str(project_root / "rag_data" / "style_samples")
        )

    def test_style_stats_output(self, tmp_path):
        """style stats コマンドが統計を出力する"""
        from src.rag_cli import run_style_stats

        output = StringIO()
        run_style_stats(
            style_rag=self.style_rag,
            output=output,
            format='text'
        )

        result = output.getvalue()
        assert 'total' in result.lower() or 'サンプル' in result

    def test_style_stats_json_output(self, tmp_path):
        """style stats --format json が有効なJSONを出力する"""
        from src.rag_cli import run_style_stats

        output = StringIO()
        run_style_stats(
            style_rag=self.style_rag,
            output=output,
            format='json'
        )

        result = output.getvalue()
        data = json.loads(result)
        assert 'total_samples' in data

    def test_style_search_returns_results(self, tmp_path):
        """style search が結果を返す"""
        from src.rag_cli import run_style_search

        output = StringIO()
        run_style_search(
            style_rag=self.style_rag,
            character='yana',
            query='成功',
            top_k=3,
            output=output,
            format='text'
        )

        result = output.getvalue()
        # 結果があるか、結果なしのメッセージがある
        assert len(result) > 0


class TestMemoryCommands:
    """Memory コマンドの実行テスト"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """テスト用のセットアップ"""
        from src.memory_rag import reset_memory_rag, MemoryRAG

        reset_memory_rag()

        # テスト用のMemoryRAGを作成
        self.memory_rag = MemoryRAG(
            db_path=str(tmp_path / "memory_rag")
        )

    def test_memory_stats_output(self, tmp_path):
        """memory stats コマンドが統計を出力する"""
        from src.rag_cli import run_memory_stats

        output = StringIO()
        run_memory_stats(
            memory_rag=self.memory_rag,
            output=output,
            format='text'
        )

        result = output.getvalue()
        assert 'episode' in result.lower() or 'エピソード' in result.lower() or 'total' in result.lower()

    def test_memory_add_episode(self, tmp_path):
        """memory add-episode がエピソードを追加する"""
        from src.rag_cli import run_memory_add_episode

        output = StringIO()
        result = run_memory_add_episode(
            memory_rag=self.memory_rag,
            summary='テストエピソード',
            yana_perspective='やな視点',
            ayu_perspective='あゆ視点',
            emotional_tag='test',
            importance=0.7,
            output=output
        )

        assert result is True
        stats = self.memory_rag.get_stats()
        assert stats.total_episodes == 1

    def test_memory_add_fact(self, tmp_path):
        """memory add-fact が事実を追加する"""
        from src.rag_cli import run_memory_add_fact
        from src.memory_rag import FactCategory

        output = StringIO()
        result = run_memory_add_fact(
            memory_rag=self.memory_rag,
            summary='ユーザーの好み',
            category='preference',
            output=output
        )

        assert result is True
        stats = self.memory_rag.get_stats()
        assert stats.total_facts == 1

    def test_memory_search_after_add(self, tmp_path):
        """memory search が追加したエピソードを検索できる"""
        from src.rag_cli import run_memory_add_episode, run_memory_search

        # エピソード追加
        run_memory_add_episode(
            memory_rag=self.memory_rag,
            summary='検索テストエピソード',
            yana_perspective='やな',
            ayu_perspective='あゆ',
            emotional_tag='test',
            importance=0.8,
            output=StringIO()
        )

        # 検索
        output = StringIO()
        run_memory_search(
            memory_rag=self.memory_rag,
            query='検索テスト',
            character='yana',
            top_k=3,
            output=output,
            format='text'
        )

        result = output.getvalue()
        assert '検索テストエピソード' in result or 'エピソード' in result.lower()


class TestCLIIntegration:
    """CLI統合テスト"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        """テスト用のセットアップ"""
        from src.style_rag import reset_style_rag
        from src.memory_rag import reset_memory_rag

        reset_style_rag()
        reset_memory_rag()

        # 一時ディレクトリを使用するように環境変数を設定
        monkeypatch.setenv('RAG_DB_PATH', str(tmp_path))

    def test_main_with_help(self):
        """--help オプションが動作する"""
        from src.rag_cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(['--help'])

        assert exc_info.value.code == 0

    def test_main_with_style_stats(self, tmp_path, monkeypatch):
        """main関数でstyle statsが実行できる"""
        from src.rag_cli import main

        # 標準出力をキャプチャ
        output = StringIO()
        monkeypatch.setattr('sys.stdout', output)

        # --db-path はサブコマンドの前に配置
        exit_code = main(['--db-path', str(tmp_path), 'style', 'stats'])

        assert exit_code == 0

    def test_main_with_memory_stats(self, tmp_path, monkeypatch):
        """main関数でmemory statsが実行できる"""
        from src.rag_cli import main

        output = StringIO()
        monkeypatch.setattr('sys.stdout', output)

        # --db-path はサブコマンドの前に配置
        exit_code = main(['--db-path', str(tmp_path), 'memory', 'stats'])

        assert exit_code == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
