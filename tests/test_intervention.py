"""
Owner Intervention unit tests
"""
import pytest

from src.owner_intervention import (
    InterventionManager,
    InterventionState,
    InstructionType,
    OwnerMessage,
    QueryBack,
    InterventionInterpretation,
    reset_intervention_manager
)


class TestInterventionState:
    def test_state_values(self):
        """状態の値が正しいことを確認"""
        assert InterventionState.RUNNING.value == "running"
        assert InterventionState.PAUSED.value == "paused"
        assert InterventionState.PROCESSING.value == "processing"
        assert InterventionState.QUERY_BACK.value == "query_back"
        assert InterventionState.RESUMING.value == "resuming"


class TestInstructionType:
    def test_instruction_type_values(self):
        """指示タイプの値が正しいことを確認"""
        assert InstructionType.TOPIC_CHANGE.value == "topic_change"
        assert InstructionType.TOPIC_DEEPEN.value == "topic_deepen"
        assert InstructionType.INFO_SUPPLEMENT.value == "info_supplement"
        assert InstructionType.MOOD_CHANGE.value == "mood_change"
        assert InstructionType.CHARACTER_FOCUS.value == "character_focus"
        assert InstructionType.GENERAL.value == "general"


class TestInterventionManager:
    @pytest.fixture
    def manager(self):
        """テスト用のInterventionManagerを作成"""
        reset_intervention_manager()
        return InterventionManager()

    def test_initial_state(self, manager):
        """初期状態がRUNNINGであることを確認"""
        assert manager.get_state() == InterventionState.RUNNING
        assert manager.current_session is None

    def test_pause_creates_session(self, manager):
        """pauseでセッションが作成されることを確認"""
        session = manager.pause("test-run-123")

        assert session is not None
        assert session.run_id == "test-run-123"
        assert session.state == InterventionState.PAUSED
        assert manager.get_state() == InterventionState.PAUSED
        assert manager.current_session == session

    def test_resume_from_paused(self, manager):
        """PAUSEDからresumeできることを確認"""
        manager.pause("test-run")
        assert manager.get_state() == InterventionState.PAUSED

        success = manager.resume()

        assert success is True
        assert manager.get_state() == InterventionState.RUNNING

    def test_resume_when_running(self, manager):
        """RUNNING時のresumeはTrueを返すことを確認"""
        assert manager.get_state() == InterventionState.RUNNING

        success = manager.resume()

        assert success is True
        assert manager.get_state() == InterventionState.RUNNING

    def test_get_status(self, manager):
        """ステータス取得の確認"""
        status = manager.get_status()

        assert status["state"] == "running"
        assert status["session"] is None

        manager.pause("test-run")
        status = manager.get_status()

        assert status["state"] == "paused"
        assert status["session"] is not None
        assert status["session"]["run_id"] == "test-run"

    def test_process_message_when_running(self, manager):
        """RUNNING時にメッセージ送信するとエラーになることを確認"""
        result = manager.process_owner_message("テスト指示")

        assert result.success is False
        assert "pause()" in result.error

    def test_process_simple_instruction(self, manager):
        """シンプルな指示が正しく処理されることを確認"""
        manager.pause("test-run")

        # 10文字以上のメッセージで曖昧判定を回避
        result = manager.process_owner_message("カーブの話題に戻してください")

        assert result.success is True
        assert result.state == InterventionState.RESUMING
        assert result.needs_clarification is False
        assert result.next_action == "resume"
        assert result.interpretation is not None

    def test_instruction_interpretation_topic_change(self, manager):
        """話題変更指示の解釈を確認"""
        manager.pause("test-run")

        result = manager.process_owner_message("カーブの話題に戻してください")

        assert result.interpretation is not None
        assert result.interpretation.instruction_type == "topic_change"

    def test_instruction_interpretation_character_focus(self, manager):
        """キャラ指名指示の解釈を確認"""
        manager.pause("test-run")

        result = manager.process_owner_message("やなの見解を聞きたいです")

        assert result.interpretation is not None
        assert result.interpretation.target_character == "yana"

    def test_instruction_interpretation_ayu_focus(self, manager):
        """あゆ指名の解釈を確認"""
        manager.pause("test-run")

        result = manager.process_owner_message("あゆの意見を聞かせてください")

        assert result.interpretation is not None
        assert result.interpretation.target_character == "ayu"

    def test_ambiguous_instruction_needs_clarification(self, manager):
        """曖昧な指示で確認が必要になることを確認"""
        manager.pause("test-run")

        # 短すぎる指示
        result = manager.process_owner_message("変えて")

        assert result.success is True
        assert result.needs_clarification is True
        assert result.query_back is not None
        assert result.state == InterventionState.QUERY_BACK

    def test_answer_query_back(self, manager):
        """逆質問への回答が処理されることを確認"""
        manager.pause("test-run")

        # 曖昧な指示を送信
        result = manager.process_owner_message("変えて")
        assert result.needs_clarification is True
        assert manager.get_state() == InterventionState.QUERY_BACK

        # 回答を送信
        answer_result = manager.answer_query_back("話題を変えてください")

        assert answer_result.success is True
        assert answer_result.state == InterventionState.RESUMING
        assert manager.current_session.query_back is None

    def test_answer_query_back_wrong_state(self, manager):
        """QUERY_BACK以外の状態で回答するとエラーになることを確認"""
        manager.pause("test-run")

        result = manager.answer_query_back("回答")

        assert result.success is False
        assert "逆質問待ち状態ではありません" in result.error

    def test_get_pending_instruction(self, manager):
        """適用待ちの指示を取得できることを確認"""
        manager.pause("test-run")
        manager.process_owner_message("カーブの話をもっと詳しくお願いします")

        instruction = manager.get_pending_instruction()

        assert instruction is not None
        assert "オーナーからの指示" in instruction

    def test_get_pending_instruction_none(self, manager):
        """指示がない場合はNoneを返すことを確認"""
        instruction = manager.get_pending_instruction()

        assert instruction is None

    def test_clear_pending_instruction(self, manager):
        """指示のクリアが動作することを確認"""
        manager.pause("test-run")
        manager.process_owner_message("テスト用の長い指示メッセージ")

        assert manager.get_pending_instruction() is not None

        manager.clear_pending_instruction()

        assert manager.get_pending_instruction() is None

    def test_get_target_character(self, manager):
        """対象キャラクターを取得できることを確認"""
        manager.pause("test-run")
        manager.process_owner_message("やなに話させてください")

        target = manager.get_target_character()

        assert target == "yana"

    def test_log_entries(self, manager):
        """ログが記録されることを確認"""
        manager.pause("test-run")
        manager.process_owner_message("テスト用の長い指示メッセージ")

        log = manager.get_log()

        assert len(log) > 0
        # システムログとオーナーメッセージがあるはず
        types = [entry["type"] for entry in log]
        assert "system" in types
        assert "owner" in types

    def test_clear_log(self, manager):
        """ログのクリアが動作することを確認"""
        manager.pause("test-run")
        manager.process_owner_message("テスト用の長い指示メッセージ")

        assert len(manager.get_log()) > 0

        manager.clear_log()

        assert len(manager.get_log()) == 0

    def test_owner_message_recording(self, manager):
        """オーナーメッセージが記録されることを確認"""
        manager.pause("test-run")
        manager.process_owner_message("最初の指示メッセージです")
        manager.resume()
        manager.pause("test-run-2")
        manager.process_owner_message("二番目の指示メッセージです")

        assert manager.current_session is not None
        # 新しいセッションなので1つのみ
        assert len(manager.current_session.owner_messages) == 1


class TestQueryBack:
    def test_query_back_creation(self):
        """QueryBackの作成を確認"""
        qb = QueryBack(
            from_character="yana",
            question="どのカーブのこと？",
            context="カーブについて曖昧",
            options=["右カーブ", "左カーブ", "全般"]
        )

        assert qb.from_character == "yana"
        assert qb.question == "どのカーブのこと？"
        assert qb.options is not None
        assert len(qb.options) == 3


class TestInterventionInterpretation:
    def test_interpretation_creation(self):
        """InterventionInterpretationの作成を確認"""
        interp = InterventionInterpretation(
            target_character="both",
            instruction_type="topic_change",
            instruction_content="話題を変更してください",
            needs_clarification=False,
            confidence=0.9
        )

        assert interp.target_character == "both"
        assert interp.instruction_type == "topic_change"
        assert interp.confidence == 0.9
