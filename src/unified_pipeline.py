"""
duo-talk v2.2 - Unified Pipeline
Console/RUNS/LIVE の3つの実行パスを統一するパイプライン

設計方針：
- InputBundle を受け取り、対話を生成し、DialogueResult を返す
- Character と Director を内部で管理
- 割り込み入力とイベント通知をサポート
- Graceful Degradation: エラー時も可能な限り結果を返す
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any, Callable, TYPE_CHECKING

from src.input_source import InputBundle, InputSource, SourceType
from src.input_collector import InputCollector, FrameContext
from src.character import Character
from src.director import Director
from src.types import DirectorEvaluation, DirectorStatus
from src.logger import Logger

if TYPE_CHECKING:
    from src.jetracer_client import JetRacerClient


@dataclass
class DialogueTurn:
    """対話ターン"""
    turn_number: int
    speaker: str  # "A" or "B"
    speaker_name: str  # "やな" or "あゆ"
    text: str
    evaluation: Optional[DirectorEvaluation] = None
    rag_hints: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "turn_number": self.turn_number,
            "speaker": self.speaker,
            "speaker_name": self.speaker_name,
            "text": self.text,
            "evaluation_status": self.evaluation.status.name if self.evaluation else None,
            "evaluation_action": self.evaluation.action if self.evaluation else None,
            "rag_hints": self.rag_hints,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class DialogueResult:
    """対話結果"""
    run_id: str
    dialogue: List[DialogueTurn]
    status: str  # "success", "paused", "error"
    frame_context: Optional[FrameContext] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "run_id": self.run_id,
            "dialogue": [t.to_dict() for t in self.dialogue],
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }

    def get_dialogue_text(self) -> str:
        """対話テキストを取得"""
        lines = []
        for turn in self.dialogue:
            lines.append(f"[{turn.speaker_name}] {turn.text}")
        return "\n".join(lines)


class UnifiedPipeline:
    """
    統一対話パイプライン

    Console/RUNS/LIVE を統一するエントリーポイント。
    InputBundle を受け取り、Character と Director を使って対話を生成する。

    Examples:
        pipeline = UnifiedPipeline()
        bundle = InputBundle(sources=[
            InputSource(source_type=SourceType.TEXT, content="お正月の準備について話して")
        ])
        result = pipeline.run(initial_input=bundle, max_turns=4)
        print(result.get_dialogue_text())
    """

    def __init__(
        self,
        jetracer_client: Optional['JetRacerClient'] = None,
        enable_fact_check: bool = True,
    ):
        """
        Args:
            jetracer_client: JetRacerクライアント（Noneなら接続なし）
            enable_fact_check: Director の事実チェックを有効にするか
        """
        self.input_collector = InputCollector(jetracer_client=jetracer_client)
        self.char_a = Character("A")
        self.char_b = Character("B")
        self.director = Director(enable_fact_check=enable_fact_check)
        self.logger = Logger()

    def run(
        self,
        initial_input: InputBundle,
        max_turns: int = 8,
        run_id: Optional[str] = None,
        interrupt_callback: Optional[Callable[[], Optional[InputBundle]]] = None,
        event_callback: Optional[Callable[[str, Dict], None]] = None,
    ) -> DialogueResult:
        """
        対話を実行

        Args:
            initial_input: 初期入力バンドル
            max_turns: 最大ターン数
            run_id: ランID（省略時は自動生成）
            interrupt_callback: 割り込み入力を取得するコールバック
                - 呼び出し時に InputBundle を返すと割り込み入力として処理
                - None を返すと割り込みなし
            event_callback: イベント通知コールバック（GUI用）
                - event_callback(event_type: str, data: dict)
                - event_type: "narration_start", "speak", "director", "interrupt", "narration_complete"

        Returns:
            DialogueResult
        """
        # 1. Run ID生成
        if run_id is None:
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        print(f"=== UnifiedPipeline.run() started: {run_id} ===")

        # 2. Director/NoveltyGuard リセット
        self.director.reset_for_new_session()

        # 3. 入力収集
        try:
            frame_context = self.input_collector.collect(initial_input)
            frame_description = frame_context.to_frame_description()
        except Exception as e:
            print(f"[UnifiedPipeline] Input collection error: {e}")
            return DialogueResult(
                run_id=run_id,
                dialogue=[],
                status="error",
                error=f"Input collection failed: {e}",
            )

        # 4. イベント通知: 開始
        topic = initial_input.get_text() or "(画像から生成)"
        self.logger.log_event({
            "event": "narration_start",
            "run_id": run_id,
            "topic": topic,
            "maxTurns": max_turns,
            "timestamp": datetime.now().isoformat(),
        })
        if event_callback:
            event_callback("narration_start", {
                "run_id": run_id,
                "frame_description": frame_description,
                "timestamp": datetime.now().isoformat(),
            })

        # 5. 対話ループ
        dialogue_turns: List[DialogueTurn] = []
        conversation_history: List[Tuple[str, str]] = []
        topic_guidance: Optional[Dict[str, Any]] = None
        current_speaker = "A"

        for turn in range(max_turns):
            print(f"\n--- Turn {turn + 1}/{max_turns} (Speaker: {current_speaker}) ---")

            # 5a. 割り込みチェック
            if interrupt_callback:
                try:
                    interrupt = interrupt_callback()
                    if interrupt:
                        new_context = self.input_collector.collect(interrupt)
                        frame_description = self._merge_context(
                            frame_description, new_context, interrupt
                        )
                        print(f"    📥 Interrupt received, context merged")
                        if event_callback:
                            event_callback("interrupt", {
                                "run_id": run_id,
                                "turn": turn,
                            })
                except Exception as e:
                    print(f"    ⚠️ Interrupt callback error: {e}")

            # 5b. キャラクター選択
            character = self.char_a if current_speaker == "A" else self.char_b
            speaker_name = "やな" if current_speaker == "A" else "あゆ"

            # 5c. 発話生成（リトライ付き）
            try:
                speech, evaluation = self._generate_with_retry(
                    character=character,
                    speaker=current_speaker,
                    frame_description=frame_description,
                    conversation_history=conversation_history,
                    topic_guidance=topic_guidance,
                    turn_number=turn,
                )
            except Exception as e:
                print(f"    ❌ Speech generation error: {e}")
                return DialogueResult(
                    run_id=run_id,
                    dialogue=dialogue_turns,
                    status="error",
                    frame_context=frame_context,
                    error=f"Speech generation failed at turn {turn}: {e}",
                )

            print(f"    [{speaker_name}] {speech[:60]}{'...' if len(speech) > 60 else ''}")

            # 5d. 記録
            dialogue_turn = DialogueTurn(
                turn_number=turn,
                speaker=current_speaker,
                speaker_name=speaker_name,
                text=speech,
                evaluation=evaluation,
                rag_hints=getattr(character, 'last_rag_hints', []) or [],
            )
            dialogue_turns.append(dialogue_turn)
            conversation_history.append((current_speaker, speech))

            # 5e. ログ記録 & イベント通知
            ts = datetime.now().isoformat()

            # speak イベント
            self.logger.log_event({
                "event": "speak",
                "run_id": run_id,
                "turn": turn,
                "speaker": current_speaker,
                "text": speech,
                "beat": evaluation.beat_stage if evaluation and hasattr(evaluation, 'beat_stage') else None,
                "ts": ts,
                "timestamp": ts,
            })

            # rag_select イベント（RAGヒントがあれば記録）
            rag_hints = getattr(character, 'last_rag_hints', []) or []
            self.logger.log_event({
                "event": "rag_select",
                "run_id": run_id,
                "turn": turn,
                "char_id": current_speaker,
                "canon": {"preview": rag_hints[0] if len(rag_hints) > 0 else ""},
                "lore": {"preview": rag_hints[1] if len(rag_hints) > 1 else ""},
                "pattern": {"preview": rag_hints[2] if len(rag_hints) > 2 else ""},
                "ts": ts,
                "timestamp": ts,
            })

            # director イベント（評価結果）
            if evaluation:
                self.logger.log_event({
                    "event": "director",
                    "run_id": run_id,
                    "turn": turn,
                    "beat": evaluation.beat_stage if hasattr(evaluation, 'beat_stage') else None,
                    "cut_cue": None,
                    "status": evaluation.status.name,
                    "reason": evaluation.reason,
                    "guidance": evaluation.suggestion,
                    "action": evaluation.action,
                    "hook": evaluation.hook if hasattr(evaluation, 'hook') else None,
                    "evidence": evaluation.evidence if hasattr(evaluation, 'evidence') else None,
                    "focus_hook": evaluation.focus_hook if hasattr(evaluation, 'focus_hook') else None,
                    "hook_depth": evaluation.hook_depth if hasattr(evaluation, 'hook_depth') else 0,
                    "depth_step": evaluation.depth_step if hasattr(evaluation, 'depth_step') else None,
                    "forbidden_topics": evaluation.forbidden_topics if hasattr(evaluation, 'forbidden_topics') else [],
                    "ts": ts,
                    "timestamp": ts,
                })

            if event_callback:
                event_callback("speak", {
                    "run_id": run_id,
                    "turn": turn,
                    "speaker": current_speaker,
                    "speaker_name": speaker_name,
                    "text": speech,
                    "evaluation_status": evaluation.status.name if evaluation else "UNKNOWN",
                    "evaluation_action": evaluation.action if evaluation else "NOOP",
                })

            # 5f. Topic Guidance更新
            if evaluation and evaluation.focus_hook:
                topic_guidance = {
                    "focus_hook": evaluation.focus_hook,
                    "hook_depth": evaluation.hook_depth,
                    "depth_step": evaluation.depth_step,
                    "forbidden_topics": evaluation.forbidden_topics,
                    "character_role": evaluation.character_role,
                    "partner_last_speech": speech,
                }

            # 5g. Fatal MODIFY チェック
            if evaluation and evaluation.status == DirectorStatus.MODIFY:
                if self.director.is_fatal_modify(evaluation.reason):
                    print(f"    ❌ Fatal MODIFY: {evaluation.reason}")
                    return DialogueResult(
                        run_id=run_id,
                        dialogue=dialogue_turns,
                        status="error",
                        frame_context=frame_context,
                        error=f"Fatal MODIFY: {evaluation.reason}",
                    )

            # 5h. 次のスピーカー
            current_speaker = "B" if current_speaker == "A" else "A"

        # 6. 完了イベント
        self.logger.log_event({
            "event": "narration_complete",
            "run_id": run_id,
            "topic": topic,
            "status": "success",
            "total_turns": len(dialogue_turns),
            "timestamp": datetime.now().isoformat(),
        })
        if event_callback:
            event_callback("narration_complete", {
                "run_id": run_id,
                "total_turns": len(dialogue_turns),
                "status": "success",
            })

        print(f"\n=== UnifiedPipeline.run() completed: {run_id} ===")

        # 7. 結果を返す
        return DialogueResult(
            run_id=run_id,
            dialogue=dialogue_turns,
            status="success",
            frame_context=frame_context,
            metadata={"max_turns": max_turns, "actual_turns": len(dialogue_turns)},
        )

    def _generate_with_retry(
        self,
        character: Character,
        speaker: str,
        frame_description: str,
        conversation_history: List[Tuple[str, str]],
        topic_guidance: Optional[Dict[str, Any]],
        turn_number: int,
        max_retry: int = 2,
    ) -> Tuple[str, Optional[DirectorEvaluation]]:
        """
        リトライ付き発話生成

        Args:
            character: キャラクターインスタンス
            speaker: "A" or "B"
            frame_description: フレーム説明
            conversation_history: 会話履歴
            topic_guidance: トピックガイダンス
            turn_number: ターン番号（0-indexed）
            max_retry: 最大リトライ回数

        Returns:
            (speech, evaluation)
        """
        director_instruction: Optional[str] = None
        evaluation: Optional[DirectorEvaluation] = None

        for attempt in range(max_retry + 1):
            # 発話生成
            speech = character.speak_unified(
                frame_description=frame_description,
                conversation_history=conversation_history,
                director_instruction=director_instruction,
                topic_guidance=topic_guidance,
            )

            # Director評価（NoveltyGuard内蔵）
            evaluation = self.director.evaluate_response(
                frame_description=frame_description,
                speaker=speaker,
                response=speech,
                partner_previous_speech=conversation_history[-1][1] if conversation_history else None,
                speaker_domains=getattr(character, 'domains', None),
                conversation_history=conversation_history,
                turn_number=turn_number + 1,  # 1-indexed for Director
                frame_num=1,  # 単一フレームの場合
            )

            # 評価結果に応じた処理
            if evaluation.status == DirectorStatus.PASS:
                # PASS でも INTERVENE アクションならリトライ
                if evaluation.action == "INTERVENE" and attempt < max_retry:
                    # next_instruction または suggestion を使用
                    director_instruction = (
                        getattr(evaluation, 'next_instruction', None)
                        or evaluation.suggestion
                    )
                    if director_instruction:
                        preview = director_instruction[:60] if len(director_instruction) > 60 else director_instruction
                        print(f"    🔁 INTERVENE リトライ ({attempt + 1}/{max_retry}): {preview}...")
                        continue
                return speech, evaluation

            elif evaluation.status == DirectorStatus.MODIFY:
                return speech, evaluation

            elif evaluation.status == DirectorStatus.RETRY:
                if attempt < max_retry:
                    director_instruction = evaluation.suggestion
                    preview = director_instruction[:60] if director_instruction else "N/A"
                    print(f"    🔄 RETRY ({attempt + 1}/{max_retry}): {preview}...")
                    continue

            # リトライ上限またはその他のステータス
            break

        return speech, evaluation

    def _merge_context(
        self,
        current_description: str,
        new_context: FrameContext,
        interrupt: InputBundle,
    ) -> str:
        """
        割り込み入力をコンテキストにマージ

        Args:
            current_description: 現在のフレーム説明
            new_context: 新しいコンテキスト
            interrupt: 割り込み入力バンドル

        Returns:
            マージされた説明文
        """
        parts = [current_description]

        if interrupt.is_interrupt:
            parts.append("\n【割り込み入力】")

        new_desc = new_context.to_frame_description()
        if new_desc and new_desc != "状況不明":
            parts.append(new_desc)

        return "\n".join(parts)

    def reset(self) -> None:
        """パイプライン状態をリセット"""
        self.director.reset_for_new_session()
        print("[UnifiedPipeline] State reset")
