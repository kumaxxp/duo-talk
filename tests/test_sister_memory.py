"""
SisterMemory unit tests
"""
import pytest
import tempfile
import shutil
from pathlib import Path

from src.sister_memory import (
    SisterMemory, MemoryEntry, MemoryValidator,
    reset_sister_memory
)


class TestMemoryValidator:
    def test_valid_memory(self):
        """正常な記憶が通過することを確認"""
        validator = MemoryValidator()
        entry = MemoryEntry(
            event_id="test-1",
            timestamp="2024-01-01T00:00:00",
            event_summary="カーブを上手く曲がれた",
            yana_perspective="やった！上手くいった！",
            ayu_perspective="計算通りの結果でした",
            emotional_tag="success_shared",
            context_tags=["curve", "success"]
        )
        is_valid, reason = validator.validate(entry)
        assert is_valid is True
        assert reason is None

    def test_yana_character_violation(self):
        """やなのキャラ崩壊パターンが検出されることを確認"""
        validator = MemoryValidator()
        entry = MemoryEntry(
            event_id="test-2",
            timestamp="2024-01-01T00:00:00",
            event_summary="テスト",
            yana_perspective="データを重視して判断した",  # 違反
            ayu_perspective="正常",
            emotional_tag="routine",
            context_tags=[]
        )
        is_valid, reason = validator.validate(entry)
        assert is_valid is False
        assert reason == "yana_character_violation"

    def test_ayu_character_violation(self):
        """あゆのキャラ崩壊パターンが検出されることを確認"""
        validator = MemoryValidator()
        entry = MemoryEntry(
            event_id="test-3",
            timestamp="2024-01-01T00:00:00",
            event_summary="テスト",
            yana_perspective="正常",
            ayu_perspective="直感でやってみた",  # 違反
            emotional_tag="routine",
            context_tags=[]
        )
        is_valid, reason = validator.validate(entry)
        assert is_valid is False
        assert reason == "ayu_character_violation"

    def test_relationship_violation(self):
        """関係性破壊パターンが検出されることを確認"""
        validator = MemoryValidator()
        entry = MemoryEntry(
            event_id="test-4",
            timestamp="2024-01-01T00:00:00",
            event_summary="テスト",
            yana_perspective="姉様を馬鹿にしていた",  # 違反
            ayu_perspective="正常",
            emotional_tag="routine",
            context_tags=[]
        )
        is_valid, reason = validator.validate(entry)
        assert is_valid is False
        assert reason == "relationship_violation"


class TestSisterMemory:
    @pytest.fixture
    def temp_db(self):
        """一時的なDBディレクトリを作成"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_buffer_and_flush(self, temp_db):
        """バッファリングとフラッシュの動作確認"""
        memory = SisterMemory(db_path=temp_db)

        # バッファに追加
        event_id = memory.buffer_event(
            event_summary="テスト走行で成功",
            yana_perspective="上手くいった！",
            ayu_perspective="予定通りです",
            emotional_tag="success_shared",
            context_tags=["test", "success"]
        )

        assert memory.get_buffer_size() == 1
        assert event_id is not None

        # フラッシュ
        result = memory.flush_buffer()

        assert result.total == 1
        assert result.written == 1
        assert result.skipped == 0
        assert memory.get_buffer_size() == 0

    def test_search(self, temp_db):
        """検索機能の動作確認"""
        memory = SisterMemory(db_path=temp_db)

        # データ追加
        memory.buffer_event(
            event_summary="右カーブで速度超過",
            yana_perspective="ちょっと攻めすぎたかな",
            ayu_perspective="推奨速度を15%超過していました",
            emotional_tag="failure_learning",
            context_tags=["curve", "speed"]
        )
        memory.flush_buffer()

        # 検索
        results = memory.search("カーブ 速度", "yana", n_results=1)

        assert len(results) == 1
        assert "攻めすぎた" in results[0].perspective

    def test_search_ayu_perspective(self, temp_db):
        """あゆ視点の検索"""
        memory = SisterMemory(db_path=temp_db)

        memory.buffer_event(
            event_summary="右カーブで速度超過",
            yana_perspective="ちょっと攻めすぎたかな",
            ayu_perspective="推奨速度を15%超過していました",
            emotional_tag="failure_learning",
            context_tags=["curve", "speed"]
        )
        memory.flush_buffer()

        results = memory.search("カーブ 速度", "ayu", n_results=1)

        assert len(results) == 1
        assert "15%" in results[0].perspective

    def test_validation_on_flush(self, temp_db):
        """フラッシュ時のバリデーション確認"""
        memory = SisterMemory(db_path=temp_db)

        # 違反データを追加
        memory.buffer_event(
            event_summary="テスト",
            yana_perspective="データを重視して判断した",  # 違反
            ayu_perspective="正常",
            emotional_tag="routine",
            context_tags=[]
        )

        result = memory.flush_buffer(validate=True)

        assert result.total == 1
        assert result.written == 0
        assert result.skipped == 1
        assert "yana_character_violation" in result.skipped_reasons

    def test_validation_disabled(self, temp_db):
        """バリデーション無効時の動作確認"""
        memory = SisterMemory(db_path=temp_db)

        # 違反データを追加
        memory.buffer_event(
            event_summary="テスト",
            yana_perspective="データを重視して判断した",  # 違反
            ayu_perspective="正常",
            emotional_tag="routine",
            context_tags=[]
        )

        # バリデーション無効
        result = memory.flush_buffer(validate=False)

        assert result.total == 1
        assert result.written == 1
        assert result.skipped == 0

    def test_clear_buffer(self, temp_db):
        """バッファクリアの動作確認"""
        memory = SisterMemory(db_path=temp_db)

        memory.buffer_event(
            event_summary="テスト",
            yana_perspective="テスト",
            ayu_perspective="テスト",
            emotional_tag="routine",
            context_tags=[]
        )

        assert memory.get_buffer_size() == 1
        memory.clear_buffer()
        assert memory.get_buffer_size() == 0

    def test_get_stats(self, temp_db):
        """統計情報取得の確認"""
        memory = SisterMemory(db_path=temp_db)

        # データ追加
        memory.buffer_event(
            event_summary="成功テスト",
            yana_perspective="やった！",
            ayu_perspective="成功です",
            emotional_tag="success_shared",
            context_tags=[]
        )
        memory.buffer_event(
            event_summary="失敗テスト",
            yana_perspective="あー",
            ayu_perspective="失敗しました",
            emotional_tag="failure_learning",
            context_tags=[]
        )
        memory.flush_buffer()

        stats = memory.get_stats()

        assert stats.total_memories == 2
        assert stats.buffer_size == 0
        assert "success_shared" in stats.emotional_tag_distribution
        assert "failure_learning" in stats.emotional_tag_distribution

    def test_empty_search(self, temp_db):
        """空のDBに対する検索"""
        memory = SisterMemory(db_path=temp_db)
        results = memory.search("なんでも", "yana")
        assert len(results) == 0

    def test_to_prompt_text(self, temp_db):
        """プロンプトテキスト変換の確認"""
        memory = SisterMemory(db_path=temp_db)

        memory.buffer_event(
            event_summary="カーブ成功",
            yana_perspective="うまくいった！",
            ayu_perspective="成功です",
            emotional_tag="success_shared",
            context_tags=[]
        )
        memory.flush_buffer()

        results = memory.search("カーブ", "yana")
        assert len(results) == 1

        prompt_text = results[0].to_prompt_text()
        assert "過去の記憶" in prompt_text
        assert "カーブ成功" in prompt_text
