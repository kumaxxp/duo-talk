"""
オーナー介入機能

対話が横道にそれた際に、オーナーがディレクターを通じて軌道修正できる機能。

設計原則:
- 自然な流れ: オーナー指示を「台本の指示」として自然に反映
- キャラ維持: 介入後もキャラクター性を保つ
- 双方向性: キャラクターからオーナーへの逆質問を許容
- 最小介入: 必要最小限の介入で効果を出す
"""

import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum


class InterventionState(Enum):
    """介入状態"""
    RUNNING = "running"           # 通常運転（対話継続中）
    PAUSED = "paused"             # 一時停止（入力待ち）
    PROCESSING = "processing"     # 指示解釈中
    QUERY_BACK = "query_back"     # キャラからの逆質問待ち
    RESUMING = "resuming"         # 再開準備中


class InstructionType(Enum):
    """指示タイプ"""
    TOPIC_CHANGE = "topic_change"        # 話題変更
    TOPIC_DEEPEN = "topic_deepen"        # 話題深掘り
    INFO_SUPPLEMENT = "info_supplement"  # 情報補足
    MOOD_CHANGE = "mood_change"          # 雰囲気変更
    CHARACTER_FOCUS = "character_focus"  # キャラ指名
    GENERAL = "general"                  # 一般的な指示


@dataclass
class OwnerMessage:
    """オーナーからのメッセージ"""
    message_id: str
    content: str
    timestamp: str
    message_type: str = "instruction"  # "instruction" | "answer" | "clarification"


@dataclass
class QueryBack:
    """キャラクターからの逆質問"""
    from_character: str  # "yana" | "ayu"
    question: str
    context: str
    options: Optional[List[str]] = None


@dataclass
class InterventionInterpretation:
    """ディレクターによる介入解釈"""
    target_character: Optional[str]  # "yana" | "ayu" | "both" | None
    instruction_type: str
    instruction_content: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    confidence: float = 1.0


@dataclass
class CharacterResponse:
    """キャラクターの応答"""
    character: str  # "yana" | "ayu"
    response: str
    timestamp: str


@dataclass
class InterventionSession:
    """介入セッション"""
    session_id: str
    run_id: str
    state: InterventionState
    created_at: str
    owner_messages: List[OwnerMessage] = field(default_factory=list)
    interpretation: Optional[InterventionInterpretation] = None
    character_responses: List[CharacterResponse] = field(default_factory=list)
    query_back: Optional[QueryBack] = None


@dataclass
class InterventionResult:
    """介入処理結果"""
    success: bool
    state: InterventionState
    needs_clarification: bool = False
    query_back: Optional[QueryBack] = None
    character_response: Optional[CharacterResponse] = None
    next_action: str = "wait_input"  # "wait_input" | "wait_answer" | "resume" | "continue"
    error: Optional[str] = None
    interpretation: Optional[InterventionInterpretation] = None


@dataclass
class InterventionLogEntry:
    """介入ログエントリ"""
    timestamp: str
    entry_type: str  # "owner" | "director" | "character" | "system"
    content: str
    character: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class InterventionManager:
    """オーナー介入マネージャー"""

    # 介入解釈用のシステムプロンプト
    INTERPRETATION_SYSTEM_PROMPT = """あなたは「やな」と「あゆ」の対話を監督するディレクターです。
オーナー（製作者）からの介入指示を解釈し、適切なキャラクターに伝えます。

【キャラクター特性】
- やな（姉/Edge AI）: 直感的、行動派、感覚重視
- あゆ（妹/Cloud AI）: 分析的、慎重派、データ重視

【解釈ルール】
1. 指示の意図を理解する
2. 適切なキャラクターを選ぶ（または両方）
3. キャラクターが理解できる言葉に変換する
4. 必要なら確認の質問を生成する"""

    # 逆質問生成用のシステムプロンプト
    QUERY_BACK_SYSTEM_PROMPT = """オーナーの指示が曖昧な場合、キャラクターの視点で確認の質問を生成します。
質問はキャラクターの口調で行います。

キャラクター口調:
- やな: カジュアル、「〜ね」「へ？」「わ！」
- あゆ: 丁寧、「です」「ですよ」「姉様」"""

    def __init__(
        self,
        director: Optional[Any] = None,
        char_a: Optional[Any] = None,
        char_b: Optional[Any] = None,
        llm_client: Optional[Any] = None
    ):
        """
        Args:
            director: Director インスタンス
            char_a: やな（姉）の Character インスタンス
            char_b: あゆ（妹）の Character インスタンス
            llm_client: LLMクライアント（指示解釈用）
        """
        self.director = director
        self.char_a = char_a
        self.char_b = char_b
        self.llm_client = llm_client

        self.current_session: Optional[InterventionSession] = None
        self.state = InterventionState.RUNNING

        # ログ
        self.log_entries: List[InterventionLogEntry] = []

        # 設定
        self.confidence_threshold = 0.7  # この確信度以下で逆質問

    # === 状態管理 ===

    def pause(self, run_id: str) -> InterventionSession:
        """
        対話を一時停止して介入セッションを開始

        Args:
            run_id: 関連するランID

        Returns:
            作成された介入セッション
        """
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        self.current_session = InterventionSession(
            session_id=session_id,
            run_id=run_id,
            state=InterventionState.PAUSED,
            created_at=now
        )
        self.state = InterventionState.PAUSED

        self._add_log("system", "対話を一時停止しました")

        return self.current_session

    def resume(self) -> bool:
        """
        対話を再開

        Returns:
            再開成功したか
        """
        if self.state == InterventionState.RUNNING:
            return True

        if self.state not in [InterventionState.PAUSED, InterventionState.RESUMING]:
            return False

        self.state = InterventionState.RUNNING
        if self.current_session:
            self.current_session.state = InterventionState.RUNNING

        self._add_log("system", "対話を再開しました")

        return True

    def get_state(self) -> InterventionState:
        """現在の状態を取得"""
        return self.state

    def get_status(self) -> Dict[str, Any]:
        """
        現在のステータスを辞書で取得

        Returns:
            ステータス情報
        """
        session_info = None
        if self.current_session:
            session_info = {
                "session_id": self.current_session.session_id,
                "run_id": self.current_session.run_id,
                "created_at": self.current_session.created_at,
                "message_count": len(self.current_session.owner_messages),
                "has_query_back": self.current_session.query_back is not None
            }

        return {
            "state": self.state.value,
            "session": session_info
        }

    # === 介入処理 ===

    def process_owner_message(
        self,
        message: str,
        message_type: str = "instruction"
    ) -> InterventionResult:
        """
        オーナーメッセージを処理

        Args:
            message: オーナーからのメッセージ
            message_type: メッセージタイプ（"instruction" | "answer" | "clarification"）

        Returns:
            InterventionResult: 処理結果
        """
        # 状態チェック
        if self.state == InterventionState.RUNNING:
            return InterventionResult(
                success=False,
                state=self.state,
                error="対話中です。先にpause()を呼んでください"
            )

        # セッションがなければ作成
        if self.current_session is None:
            self.pause("default")

        # メッセージを記録
        owner_msg = OwnerMessage(
            message_id=str(uuid.uuid4()),
            content=message,
            timestamp=datetime.now().isoformat(),
            message_type=message_type
        )
        self.current_session.owner_messages.append(owner_msg)
        self._add_log("owner", message)

        # 状態を処理中に
        self.state = InterventionState.PROCESSING
        self.current_session.state = InterventionState.PROCESSING

        # 指示を解釈
        interpretation = self._interpret_instruction(message, {})

        if interpretation is None:
            self.state = InterventionState.PAUSED
            return InterventionResult(
                success=False,
                state=self.state,
                error="指示の解釈に失敗しました"
            )

        self.current_session.interpretation = interpretation

        # 確認が必要な場合
        if interpretation.needs_clarification:
            query_back = self._generate_query_back(
                interpretation.clarification_question or "詳しく教えてください",
                interpretation.target_character or "yana"
            )
            self.current_session.query_back = query_back
            self.state = InterventionState.QUERY_BACK
            self.current_session.state = InterventionState.QUERY_BACK

            self._add_log(
                "character",
                query_back.question,
                character=query_back.from_character
            )

            return InterventionResult(
                success=True,
                state=self.state,
                needs_clarification=True,
                query_back=query_back,
                next_action="wait_answer",
                interpretation=interpretation
            )

        # 確認不要なら指示を適用
        self._add_log(
            "director",
            f"→ {interpretation.target_character or 'both'}に伝達: {interpretation.instruction_content}"
        )

        # 再開準備
        self.state = InterventionState.RESUMING
        self.current_session.state = InterventionState.RESUMING

        return InterventionResult(
            success=True,
            state=self.state,
            needs_clarification=False,
            next_action="resume",
            interpretation=interpretation
        )

    def answer_query_back(self, answer: str) -> InterventionResult:
        """
        逆質問に回答

        Args:
            answer: オーナーの回答

        Returns:
            処理結果
        """
        if self.state != InterventionState.QUERY_BACK:
            return InterventionResult(
                success=False,
                state=self.state,
                error="逆質問待ち状態ではありません"
            )

        if self.current_session is None:
            return InterventionResult(
                success=False,
                state=self.state,
                error="セッションがありません"
            )

        # 回答を記録
        answer_msg = OwnerMessage(
            message_id=str(uuid.uuid4()),
            content=answer,
            timestamp=datetime.now().isoformat(),
            message_type="answer"
        )
        self.current_session.owner_messages.append(answer_msg)
        self._add_log("owner", f"回答: {answer}")

        # 既存の解釈を回答で補完
        if self.current_session.interpretation:
            # 回答を指示内容に追加
            original = self.current_session.interpretation.instruction_content
            self.current_session.interpretation.instruction_content = (
                f"{original}\n（補足: {answer}）"
            )
            self.current_session.interpretation.needs_clarification = False

        # 逆質問をクリア
        self.current_session.query_back = None

        # 再開準備
        self.state = InterventionState.RESUMING
        self.current_session.state = InterventionState.RESUMING

        self._add_log("director", "回答を受け取りました。指示を適用します。")

        return InterventionResult(
            success=True,
            state=self.state,
            needs_clarification=False,
            next_action="resume",
            interpretation=self.current_session.interpretation
        )

    def get_pending_instruction(self) -> Optional[str]:
        """
        適用待ちの指示を取得（キャラクターのプロンプトに注入用）

        Returns:
            指示テキスト（なければNone）
        """
        if self.current_session is None:
            return None
        if self.current_session.interpretation is None:
            return None

        interp = self.current_session.interpretation
        return f"【オーナーからの指示】\n{interp.instruction_content}"

    def get_target_character(self) -> Optional[str]:
        """
        指示対象のキャラクターを取得

        Returns:
            "yana" | "ayu" | "both" | None
        """
        if self.current_session is None:
            return None
        if self.current_session.interpretation is None:
            return None

        return self.current_session.interpretation.target_character

    def clear_pending_instruction(self) -> None:
        """適用済みの指示をクリア"""
        if self.current_session:
            self.current_session.interpretation = None

    # === ディレクター連携 ===

    def _interpret_instruction(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Optional[InterventionInterpretation]:
        """
        ディレクターに指示を解釈させる

        Args:
            message: オーナーからのメッセージ
            context: 現在の対話コンテキスト

        Returns:
            解釈結果
        """
        # LLMが利用可能ならLLMで解釈
        if self.llm_client:
            return self._interpret_with_llm(message, context)

        # LLMなしの場合はルールベースで解釈
        return self._interpret_rule_based(message)

    def _interpret_with_llm(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Optional[InterventionInterpretation]:
        """LLMを使った指示解釈"""
        prompt = f"""【オーナーからの指示】
{message}

【判断してください】
1. この指示は誰に伝えるべきか？（yana / ayu / both）
2. どのような指示タイプか？（topic_change / topic_deepen / info_supplement / mood_change / character_focus / general）
3. キャラクターにどう伝えるか？
4. 確認が必要な点はあるか？

JSON形式で回答:
{{
  "target_character": "yana" | "ayu" | "both",
  "instruction_type": "...",
  "instruction_content": "キャラクターへの指示文",
  "needs_clarification": true | false,
  "clarification_question": "確認の質問（必要な場合）",
  "confidence": 0.0-1.0
}}"""

        try:
            import json
            result = self.llm_client.call(
                system=self.INTERPRETATION_SYSTEM_PROMPT,
                user=prompt,
                temperature=0.3,
                max_tokens=500
            )

            # JSONパース
            import re
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                data = json.loads(json_match.group())
                return InterventionInterpretation(
                    target_character=data.get("target_character", "both"),
                    instruction_type=data.get("instruction_type", "general"),
                    instruction_content=data.get("instruction_content", message),
                    needs_clarification=data.get("needs_clarification", False),
                    clarification_question=data.get("clarification_question"),
                    confidence=data.get("confidence", 0.8)
                )
        except Exception as e:
            print(f"LLM interpretation error: {e}")

        # フォールバック
        return self._interpret_rule_based(message)

    def _interpret_rule_based(self, message: str) -> InterventionInterpretation:
        """ルールベースの指示解釈"""
        msg_lower = message.lower()
        target = "both"
        instruction_type = InstructionType.GENERAL.value
        needs_clarification = False
        clarification_question = None

        # キャラクター指定の検出
        if "やな" in message or "姉" in message:
            target = "yana"
        elif "あゆ" in message or "妹" in message:
            target = "ayu"

        # 指示タイプの検出
        if any(w in msg_lower for w in ["戻", "変え", "切り替"]):
            instruction_type = InstructionType.TOPIC_CHANGE.value
        elif any(w in msg_lower for w in ["詳しく", "深掘り", "もっと"]):
            instruction_type = InstructionType.TOPIC_DEEPEN.value
        elif any(w in msg_lower for w in ["実は", "補足", "情報"]):
            instruction_type = InstructionType.INFO_SUPPLEMENT.value
        elif any(w in msg_lower for w in ["雰囲気", "トーン", "リラックス", "真面目"]):
            instruction_type = InstructionType.MOOD_CHANGE.value
        elif any(w in msg_lower for w in ["見解", "意見", "聞きたい"]):
            instruction_type = InstructionType.CHARACTER_FOCUS.value
            if target == "both":
                needs_clarification = True
                clarification_question = "どちらのキャラクターに話させますか？"

        # 曖昧な指示の検出
        if len(message) < 10 and "?" not in message:
            needs_clarification = True
            clarification_question = "もう少し具体的に教えていただけますか？"

        return InterventionInterpretation(
            target_character=target,
            instruction_type=instruction_type,
            instruction_content=message,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            confidence=0.9 if not needs_clarification else 0.5
        )

    def _generate_query_back(
        self,
        ambiguity: str,
        character: str
    ) -> QueryBack:
        """
        逆質問を生成

        Args:
            ambiguity: 曖昧な点
            character: 質問するキャラクター ("yana" | "ayu")

        Returns:
            QueryBack オブジェクト
        """
        if character == "yana":
            question = f"えっと、{ambiguity}"
        else:
            question = f"確認させてください。{ambiguity}"

        return QueryBack(
            from_character=character,
            question=question,
            context=ambiguity,
            options=None
        )

    # === ログ管理 ===

    def _add_log(
        self,
        entry_type: str,
        content: str,
        character: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """ログエントリを追加"""
        entry = InterventionLogEntry(
            timestamp=datetime.now().isoformat(),
            entry_type=entry_type,
            content=content,
            character=character,
            metadata=metadata
        )
        self.log_entries.append(entry)

    def get_log(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        介入ログを取得

        Args:
            run_id: 特定のランIDでフィルタ（未実装）

        Returns:
            ログエントリのリスト
        """
        return [
            {
                "timestamp": entry.timestamp,
                "type": entry.entry_type,
                "content": entry.content,
                "character": entry.character,
                "metadata": entry.metadata
            }
            for entry in self.log_entries
        ]

    def clear_log(self) -> None:
        """ログをクリア"""
        self.log_entries.clear()


# シングルトンインスタンス
_intervention_manager: Optional[InterventionManager] = None


def get_intervention_manager() -> InterventionManager:
    """シングルトンインスタンスを取得"""
    global _intervention_manager
    if _intervention_manager is None:
        _intervention_manager = InterventionManager()
    return _intervention_manager


def reset_intervention_manager() -> None:
    """シングルトンをリセット（テスト用）"""
    global _intervention_manager
    _intervention_manager = None
