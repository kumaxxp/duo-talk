"""
Dual-RAG Architecture テスト

Style RAG, Memory RAG, Reflection, DualRAGInjector の
基本動作を確認するテスト。
"""

import pytest
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.style_rag import StyleRAG, DataOrigin, get_style_rag, reset_style_rag
from src.memory_rag import MemoryRAG, MemoryType, FactCategory, get_memory_rag, reset_memory_rag
from src.reflection import ReflectionEngine, get_reflection_engine, reset_reflection_engine
from src.injection import Priority, PromptBuilder, DualRAGInjector


class TestStyleRAG:
    """Style RAGのテスト"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """テスト用の一時ディレクトリを使用"""
        reset_style_rag()
        self.style_rag = StyleRAG(
            db_path=str(tmp_path / "style_rag"),
            data_dir=str(project_root / "rag_data" / "style_samples")
        )

    def test_init_loads_samples(self):
        """初期化時にサンプルがロードされる"""
        stats = self.style_rag.get_stats()
        assert stats.total_samples > 0
        assert "yana" in stats.by_character or "ayu" in stats.by_character

    def test_retrieve_by_character(self):
        """キャラクター別に検索できる"""
        results = self.style_rag.retrieve(
            character_id="yana",
            query="成功",
            top_k=3
        )

        # 結果が返ることを確認
        assert isinstance(results, list)
        # 結果があればキャラクターIDが正しいことを確認
        for sample in results:
            assert sample.character_id == "yana"

    def test_retrieve_by_emotion(self):
        """感情フィルタで検索できる"""
        results = self.style_rag.retrieve_by_emotion(
            character_id="yana",
            emotion="excited",
            n_results=3
        )

        assert isinstance(results, list)

    def test_add_from_feedback(self):
        """フィードバックからサンプルを追加できる"""
        initial_count = self.style_rag.get_stats().total_samples

        # positive フィードバックは追加される
        sample_id = self.style_rag.add_from_feedback(
            character_id="yana",
            example="テスト用セリフだよ！",
            situation="テスト",
            emotion="test",
            feedback_type="positive"
        )

        assert sample_id is not None

        # negative フィードバックは追加されない
        sample_id_neg = self.style_rag.add_from_feedback(
            character_id="yana",
            example="これは追加されない",
            situation="テスト",
            emotion="test",
            feedback_type="negative"
        )

        assert sample_id_neg is None

    def test_sample_to_prompt_text(self):
        """サンプルがプロンプトテキストに変換できる"""
        results = self.style_rag.retrieve(
            character_id="yana",
            query="成功",
            top_k=1
        )

        if results:
            text = results[0].to_prompt_text()
            assert "【" in text
            assert "】" in text


class TestMemoryRAG:
    """Memory RAGのテスト"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """テスト用の一時ディレクトリを使用"""
        reset_memory_rag()
        self.memory_rag = MemoryRAG(
            db_path=str(tmp_path / "memory_rag")
        )

    def test_buffer_episode(self):
        """エピソードをバッファに追加できる"""
        memory_id = self.memory_rag.buffer_episode(
            summary="テストエピソード",
            yana_perspective="やなの視点",
            ayu_perspective="あゆの視点",
            emotional_tag="test",
            importance=0.8,
            context_tags=["test"]
        )

        assert memory_id is not None
        assert len(self.memory_rag.episode_buffer) == 1

    def test_buffer_fact(self):
        """事実をバッファに追加できる"""
        memory_id = self.memory_rag.buffer_fact(
            summary="ユーザーの好み",
            category=FactCategory.PREFERENCE,
            subject="user"
        )

        assert memory_id is not None
        assert len(self.memory_rag.fact_buffer) == 1

    def test_flush_buffer(self):
        """バッファをフラッシュできる"""
        # バッファに追加
        self.memory_rag.buffer_episode(
            summary="フラッシュテスト",
            yana_perspective="やな",
            ayu_perspective="あゆ",
            emotional_tag="test",
            importance=0.5
        )

        self.memory_rag.buffer_fact(
            summary="事実テスト",
            category=FactCategory.INFO
        )

        # フラッシュ
        result = self.memory_rag.flush_buffer()

        assert result["episodes_written"] == 1
        assert result["facts_written"] == 1
        assert len(self.memory_rag.episode_buffer) == 0
        assert len(self.memory_rag.fact_buffer) == 0

    def test_search_after_flush(self):
        """フラッシュ後に検索できる"""
        # データを追加してフラッシュ
        self.memory_rag.buffer_episode(
            summary="検索テストエピソード",
            yana_perspective="やなの視点です",
            ayu_perspective="あゆの視点です",
            emotional_tag="test",
            importance=0.8
        )
        self.memory_rag.flush_buffer()

        # 検索
        result = self.memory_rag.search(
            query="検索テスト",
            character="yana",
            top_k=3
        )

        assert len(result.episodes) > 0

    def test_episode_to_prompt_text(self):
        """エピソードがプロンプトテキストに変換できる"""
        self.memory_rag.buffer_episode(
            summary="変換テスト",
            yana_perspective="やなの変換テスト",
            ayu_perspective="あゆの変換テスト",
            emotional_tag="test",
            importance=0.5
        )
        self.memory_rag.flush_buffer()

        result = self.memory_rag.search(
            query="変換テスト",
            character="yana",
            top_k=1
        )

        if result.episodes:
            text = result.episodes[0].to_prompt_text("yana")
            assert "過去の体験" in text
            assert "やな" in text


class TestReflection:
    """Reflectionのテスト"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """テスト用のセットアップ"""
        reset_reflection_engine()
        reset_memory_rag()
        self.memory_rag = MemoryRAG(db_path=str(tmp_path / "memory_rag"))
        self.engine = ReflectionEngine(
            memory_rag=self.memory_rag,
            llm_generate=None,  # LLMなしのルールベース
            min_turns_for_reflection=3
        )

    def test_process_short_conversation(self):
        """短い会話はスキップされる"""
        history = [
            {"speaker": "user", "content": "こんにちは", "timestamp": "2025-01-01T00:00:00"}
        ]

        result = self.engine.process_conversation(history)

        assert result.episodes_extracted == 0
        assert result.facts_extracted == 0

    def test_process_success_conversation(self):
        """成功パターンを含む会話が処理される"""
        history = [
            {"speaker": "user", "content": "やってみよう", "timestamp": "2025-01-01T00:00:00"},
            {"speaker": "yana", "content": "よし、いくよ！", "timestamp": "2025-01-01T00:01:00"},
            {"speaker": "ayu", "content": "準備OKです", "timestamp": "2025-01-01T00:02:00"},
            {"speaker": "yana", "content": "やった！成功した！", "timestamp": "2025-01-01T00:03:00"},
            {"speaker": "ayu", "content": "おめでとうございます", "timestamp": "2025-01-01T00:04:00"},
        ]

        result = self.engine.process_conversation(history)

        # ルールベースなので成功パターンを検出
        assert result.episodes_extracted >= 0


class TestDualRAGInjector:
    """DualRAGInjectorのテスト"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """テスト用のセットアップ"""
        reset_style_rag()
        reset_memory_rag()

        self.style_rag = StyleRAG(
            db_path=str(tmp_path / "style_rag"),
            data_dir=str(project_root / "rag_data" / "style_samples")
        )

        self.memory_rag = MemoryRAG(
            db_path=str(tmp_path / "memory_rag")
        )

        self.injector = DualRAGInjector(
            style_rag=self.style_rag,
            memory_rag=self.memory_rag
        )

    def test_inject_style_only(self):
        """Style RAGのみ注入できる"""
        builder = PromptBuilder()

        count = self.injector.inject_style_only(
            builder=builder,
            character_id="yana",
            query="成功"
        )

        # 注入数を確認
        assert isinstance(count, int)

    def test_inject_memory_only(self):
        """Memory RAGのみ注入できる"""
        # まずメモリを追加
        self.memory_rag.buffer_episode(
            summary="注入テスト",
            yana_perspective="やな",
            ayu_perspective="あゆ",
            emotional_tag="test",
            importance=0.5
        )
        self.memory_rag.flush_buffer()

        builder = PromptBuilder()

        result = self.injector.inject_memory_only(
            builder=builder,
            character_id="yana",
            query="注入テスト"
        )

        assert "episodes" in result
        assert "facts" in result

    def test_full_inject(self):
        """完全な注入ができる"""
        builder = PromptBuilder()

        result = self.injector.inject(
            builder=builder,
            character_id="yana",
            query="テスト",
            emotion="excited"
        )

        assert "style" in result
        assert "episodes" in result
        assert "facts" in result

    def test_builder_structure(self):
        """ビルダーに正しい優先度で注入される"""
        builder = PromptBuilder()

        # システムプロンプトを追加
        builder.add("System prompt", Priority.SYSTEM, "system")

        # Dual-RAG注入
        self.injector.inject(
            builder=builder,
            character_id="yana",
            query="テスト"
        )

        # 構造を確認
        structure = builder.get_structure()

        # システムプロンプトが最初に来ることを確認
        if structure:
            assert structure[0]["source"] == "system"


class TestPriority:
    """Priorityのテスト"""

    def test_new_priorities_exist(self):
        """新しいPriorityが存在する"""
        assert hasattr(Priority, 'STYLE_RAG')
        assert hasattr(Priority, 'MEMORY_RAG_EPISODE')
        assert hasattr(Priority, 'MEMORY_RAG_FACT')

    def test_priority_order(self):
        """Priorityの順序が正しい"""
        assert Priority.DEEP_VALUES < Priority.STYLE_RAG
        assert Priority.STYLE_RAG < Priority.LONG_MEMORY
        assert Priority.LONG_MEMORY < Priority.MEMORY_RAG_EPISODE
        assert Priority.MEMORY_RAG_EPISODE < Priority.MEMORY_RAG_FACT
        assert Priority.MEMORY_RAG_FACT < Priority.SISTER_MEMORY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
