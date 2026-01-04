"""
MemoryGenerator unit tests
"""
import pytest
from src.memory_generator import (
    MemoryGenerator, DialogueTurn, DetectedEvent,
    EVENT_PATTERNS, reset_memory_generator
)
from src.sister_memory import reset_sister_memory


@pytest.fixture
def generator():
    """テスト用のMemoryGeneratorを作成"""
    reset_memory_generator()
    reset_sister_memory()
    return MemoryGenerator(min_turns_for_memory=2, min_confidence=0.3)


@pytest.fixture
def sample_history():
    """サンプル対話履歴"""
    return [
        {"speaker": "yana", "content": "あ、なんか右側に障害物があるね", "timestamp": "2024-01-01T00:00:00"},
        {"speaker": "ayu", "content": "距離センサーで検出しました。約30cmです", "timestamp": "2024-01-01T00:00:01"},
        {"speaker": "yana", "content": "やった！うまく避けられた！", "timestamp": "2024-01-01T00:00:02"},
        {"speaker": "ayu", "content": "成功です。進入角度が最適でした", "timestamp": "2024-01-01T00:00:03"},
    ]


class TestEventDetection:
    def test_detect_success(self, generator):
        """成功イベントの検出"""
        chunk = [
            DialogueTurn("yana", "やった！完璧！", ""),
            DialogueTurn("ayu", "成功です", "")
        ]
        events = generator._detect_events(chunk)

        assert len(events) >= 1
        success_events = [e for e in events if e.event_type == "success"]
        assert len(success_events) >= 1

    def test_detect_failure(self, generator):
        """失敗イベントの検出"""
        chunk = [
            DialogueTurn("yana", "あー、失敗しちゃった", ""),
            DialogueTurn("ayu", "ミスの原因を分析します", "")
        ]
        events = generator._detect_events(chunk)

        failure_events = [e for e in events if e.event_type == "failure"]
        assert len(failure_events) >= 1

    def test_detect_discovery(self, generator):
        """発見イベントの検出"""
        chunk = [
            DialogueTurn("yana", "あ、見て見て！", ""),
            DialogueTurn("ayu", "何でしょう？", "")
        ]
        events = generator._detect_events(chunk)

        discovery_events = [e for e in events if e.event_type == "discovery"]
        assert len(discovery_events) >= 1

    def test_detect_disagreement(self, generator):
        """対立イベントの検出"""
        chunk = [
            DialogueTurn("yana", "もっと速度出せるよ", ""),
            DialogueTurn("ayu", "でも、データ的には危険です", "")
        ]
        events = generator._detect_events(chunk)

        disagreement_events = [e for e in events if e.event_type == "disagreement"]
        assert len(disagreement_events) >= 1


class TestPerspectiveGeneration:
    def test_generate_yana_perspective(self, generator):
        """やな視点の生成"""
        chunk = [DialogueTurn("yana", "やった！成功した！", "")]
        event = DetectedEvent("success", "やった", "yana", 1.0)

        perspective = generator._generate_perspective(chunk, event, "yana")

        assert "うまくいった" in perspective

    def test_generate_ayu_perspective(self, generator):
        """あゆ視点の生成"""
        chunk = [DialogueTurn("ayu", "計算通りの結果です", "")]
        event = DetectedEvent("success", "成功", "ayu", 1.0)

        perspective = generator._generate_perspective(chunk, event, "ayu")

        assert "成功です" in perspective


class TestProcessDialogue:
    def test_process_creates_memories(self, generator, sample_history):
        """対話処理で記憶が生成されることを確認"""
        event_ids = generator.process_dialogue(sample_history, run_id="test-run")

        assert len(event_ids) >= 1
        assert generator.get_buffer_size() >= 1

    def test_process_short_history(self, generator):
        """短い履歴では記憶が生成されないことを確認"""
        short_history = [
            {"speaker": "yana", "content": "こんにちは", "timestamp": ""}
        ]
        event_ids = generator.process_dialogue(short_history)

        assert len(event_ids) == 0

    def test_flush_memories(self, generator, sample_history):
        """記憶のフラッシュが動作することを確認"""
        generator.process_dialogue(sample_history, run_id="test-run")

        assert generator.get_buffer_size() >= 1

        result = generator.flush_memories(validate=True)

        assert result["total"] >= 1
        assert generator.get_buffer_size() == 0


class TestEmotionTag:
    def test_success_tag(self, generator):
        """成功時の感情タグ"""
        chunk = [
            DialogueTurn("yana", "やった！", ""),
            DialogueTurn("ayu", "成功です", "")
        ]
        event = DetectedEvent("success", "やった", "yana", 1.0)

        tag = generator._determine_emotion_tag(chunk, event)

        assert "success" in tag

    def test_failure_tag(self, generator):
        """失敗時の感情タグ"""
        chunk = [
            DialogueTurn("yana", "失敗した...", ""),
            DialogueTurn("ayu", "分析します", "")
        ]
        event = DetectedEvent("failure", "失敗", "yana", 1.0)

        tag = generator._determine_emotion_tag(chunk, event)

        assert tag == "failure_learning"
