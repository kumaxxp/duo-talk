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
from src.director_factory import get_director
from src.types import DirectorEvaluation, DirectorStatus
from src.logger import Logger
from src.signals import DuoSignals
from src.memory_rag import get_memory_rag

if TYPE_CHECKING:
    from src.jetracer_client import JetRacerClient
    from src.florence2_to_signals import Florence2ToSignals


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
        jetracer_mode: Optional[bool] = None,
        enable_florence2: bool = True,
    ):
        """
        Args:
            jetracer_client: JetRacerクライアント（Noneなら接続なし）
            enable_fact_check: Director の事実チェックを有効にするか
            jetracer_mode: JetRacerモード（None=自動判定、True=強制ON、False=強制OFF）
            enable_florence2: Florence-2画像解析を有効にするか
        """
        self.input_collector = InputCollector(jetracer_client=jetracer_client)
        self._jetracer_mode_override = jetracer_mode
        self._jetracer_client = jetracer_client
        self._enable_florence2 = enable_florence2
        # Characterは初回run()時にモード判定してから初期化
        self.char_a: Optional[Character] = None
        self.char_b: Optional[Character] = None
        # Director: 設定に応じてMinimalまたはFullモードを使用
        self.director = get_director()
        self.logger = Logger()
        self.signals = DuoSignals()
        
        # Florence-2ブリッジ（遅延初期化）
        self._florence2_bridge: Optional['Florence2ToSignals'] = None
        self._florence2_initialized = False

    @property
    def florence2_bridge(self) -> Optional['Florence2ToSignals']:
        """Florence-2ブリッジを取得（遅延初期化）"""
        if not self._enable_florence2:
            return None
        
        if not self._florence2_initialized:
            try:
                from src.florence2_to_signals import Florence2ToSignals
                self._florence2_bridge = Florence2ToSignals(
                    signals=self.signals,
                    auto_inject=True,
                )
                # サービス確認
                if self._florence2_bridge.is_service_ready():
                    print("[UnifiedPipeline] Florence-2 service ready")
                else:
                    print("[UnifiedPipeline] Florence-2 service not available")
                    self._florence2_bridge = None
            except Exception as e:
                print(f"[UnifiedPipeline] Florence-2 init failed: {e}")
                self._florence2_bridge = None
            self._florence2_initialized = True
        
        return self._florence2_bridge

    def _analyze_image_with_florence2(
        self,
        image_data: bytes,
    ) -> Optional[Dict[str, str]]:
        """
        Florence-2で画像を解析し、scene_factsを返す
        
        Args:
            image_data: 画像バイト列
        
        Returns:
            scene_facts辞書、失敗時はNone
        """
        bridge = self.florence2_bridge
        if not bridge:
            return None
        
        try:
            result = bridge.process_image(image_data, inject=True)
            if result.success:
                caption_preview = result.caption[:50] if result.caption else "(no caption)"
                print(f"    👁️ Florence-2: {caption_preview}... ({result.processing_time_ms:.0f}ms)")
                return result.to_scene_facts()
            else:
                print(f"    ⚠️ Florence-2 error: {result.error}")
                return None
        except Exception as e:
            print(f"    ⚠️ Florence-2 exception: {e}")
            return None

    def _run_florence2_analysis(self) -> None:
        """
        JetRacerから画像を取得してFlorence-2で解析
        
        結果はDuoSignals.scene_factsに自動注入される
        """
        if not self._jetracer_client:
            return
        
        try:
            # JetRacerから画像取得
            image_data = self._jetracer_client.get_camera_image(camera_id=0)
            if not image_data:
                print("    ⚠️ JetRacer: No image available")
                return
            
            # Florence-2で解析（結果はDuoSignalsに自動注入）
            self._analyze_image_with_florence2(image_data)
            
        except Exception as e:
            print(f"    ⚠️ Florence-2 analysis failed: {e}")

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

        # 2. JetRacerモード判定とCharacter初期化
        jetracer_mode = self._determine_jetracer_mode(initial_input)
        print(f"    Mode: {'JetRacer' if jetracer_mode else 'General Conversation'}")
        
        # Character初期化（モードが変わったら再初期化）
        if self.char_a is None or self.char_a.jetracer_mode != jetracer_mode:
            self.char_a = Character("A", jetracer_mode=jetracer_mode)
            self.char_b = Character("B", jetracer_mode=jetracer_mode)

        # 3. Director/NoveltyGuard リセット
        self.director.reset_for_new_session()
        # Memory RAGの使用済み記憶をリセット（ループ防止）
        get_memory_rag().reset_used_memories()

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

        # 3.5 Florence-2画像解析（JetRacerモード時）
        if jetracer_mode and self._jetracer_client and self._enable_florence2:
            self._run_florence2_analysis()

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
                    event_callback=event_callback,
                    run_id=run_id,
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

            # Director評価結果を表示
            if evaluation:
                status_emoji = {
                    DirectorStatus.PASS: "✅",
                    DirectorStatus.WARN: "⚠️",
                    DirectorStatus.RETRY: "🔄",
                    DirectorStatus.MODIFY: "❌",
                }.get(evaluation.status, "❓")
                reason_preview = evaluation.reason[:50] if evaluation.reason else ""
                print(f"    {status_emoji} Director: {evaluation.status.name} - {reason_preview}")

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
        event_callback: Optional[Callable[[str, Dict], None]] = None,
        run_id: Optional[str] = None,
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
            event_callback: イベント通知用コールバック
            run_id: 実行ID

        Returns:
            (speech, evaluation)
        """
        director_instruction: Optional[str] = None
        evaluation: Optional[DirectorEvaluation] = None

        speaker_name = "やな" if speaker == "A" else "あゆ"

        for attempt in range(max_retry + 1):
            # 1. プロンプトを先に準備
            prompt = character.prepare_prompt_unified(
                frame_description=frame_description,
                conversation_history=conversation_history,
                director_instruction=director_instruction,
                topic_guidance=topic_guidance,
            )

            # 2. イベント: 生成開始（プロンプト付き）
            thought_data = {
                "event": "thought",
                "run_id": run_id,
                "status": "generating",
                "speaker": speaker,
                "speaker_name": speaker_name,
                "attempt": attempt + 1,
                "max_retry": max_retry,
                "turn": turn_number,
                "timestamp": datetime.now().isoformat(),
                "prompt": prompt,  # LLMに送信するプロンプト
            }
            if run_id:
                self.logger.log_event(thought_data)

            if event_callback:
                event_callback("thought", thought_data)

            # 3. 準備済みプロンプトを使ってLLM呼び出し
            speech = character.generate_from_prepared_prompt(
                conversation_history=conversation_history,
            )

            # イベント: 評価開始
            # ※MinimalモードではLLM評価なし、FullモードではLLM評価あり
            review_data = {
                "event": "thought",
                "run_id": run_id,
                "status": "reviewing",
                "speaker": speaker,
                "speaker_name": speaker_name,
                "attempt": attempt + 1,
                "turn": turn_number,
                "timestamp": datetime.now().isoformat(),
                "text": speech,  # 生成された応答
                # プロンプトは評価後にDirectorから取得（LLM使用時のみ）
            }
            if run_id:
                self.logger.log_event(review_data)

            if event_callback:
                event_callback("thought", review_data)

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
            
            # イベント: 評価完了（結果通知、Director評価プロンプト付き - Fullモードのみ）
            reviewed_data = {
                "event": "thought",
                "run_id": run_id,
                "status": "reviewed",
                "speaker": speaker,
                "result": evaluation.status.name,
                "reason": evaluation.reason,
                "text": speech,
                "attempt": attempt + 1,
                "turn": turn_number,
                "timestamp": datetime.now().isoformat(),
            }
            # Director評価プロンプトがあれば含める（FullモードでLLM評価を行った場合のみ）
            if self.director.last_evaluation_prompt:
                reviewed_data["prompt"] = self.director.last_evaluation_prompt

            if run_id:
                self.logger.log_event(reviewed_data)

            if event_callback:
                event_callback("thought", reviewed_data)

            # 評価結果に応じた処理
            if evaluation.status in {DirectorStatus.PASS, DirectorStatus.WARN}:
                # PASS でも INTERVENE アクションならリトライ
                if evaluation.status == DirectorStatus.PASS and evaluation.action == "INTERVENE" and attempt < max_retry:
                    # next_instruction または suggestion を使用
                    director_instruction = (
                        getattr(evaluation, 'next_instruction', None)
                        or evaluation.suggestion
                    )
                    if director_instruction:
                        preview = director_instruction[:60] if len(director_instruction) > 60 else director_instruction
                        print(f"    🔁 INTERVENE リトライ ({attempt + 1}/{max_retry}): {preview}...")
                        
                        retry_data = {
                            "event": "thought",
                            "run_id": run_id,
                            "status": "retrying",
                            "speaker": speaker,
                            "reason": f"介入: {evaluation.reason}",
                            "suggestion": director_instruction,
                            "text": speech,
                            "prompt": prompt,  # 生成に使用したプロンプト
                            "attempt": attempt + 1,
                            "turn": turn_number,
                            "timestamp": datetime.now().isoformat(),
                        }
                        if run_id:
                            self.logger.log_event(retry_data)

                        if event_callback:
                            event_callback("thought", retry_data)
                        continue
                
                # PASS/WARN でリトライしない場合、状態を確定
                self.director.commit_evaluation(speech, evaluation)
                return speech, evaluation

            elif evaluation.status == DirectorStatus.MODIFY:
                self.director.commit_evaluation(speech, evaluation)
                return speech, evaluation

            elif evaluation.status == DirectorStatus.RETRY:
                if attempt < max_retry:
                    director_instruction = evaluation.suggestion
                    preview = director_instruction[:60] if director_instruction else "N/A"
                    print(f"    🔄 RETRY ({attempt + 1}/{max_retry}): {preview}...")
                    
                    retry_data = {
                        "event": "thought",
                        "run_id": run_id,
                        "status": "retrying",
                        "speaker": speaker,
                        "reason": evaluation.reason,
                        "suggestion": director_instruction,
                        "text": speech,
                        "prompt": prompt,  # 生成に使用したプロンプト
                        "attempt": attempt + 1,
                        "turn": turn_number,
                        "timestamp": datetime.now().isoformat(),
                    }
                    if run_id:
                        self.logger.log_event(retry_data)

                    if event_callback:
                        event_callback("thought", retry_data)
                    continue

            # リトライ上限またはその他のステータス
            break

        # 最終的な結果を確定
        if evaluation:
            self.director.commit_evaluation(speech, evaluation)
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

    def _determine_jetracer_mode(self, bundle: InputBundle) -> bool:
        """
        InputBundleからJetRacerモードを判定
        
        判定基準:
        1. オーバーライドが指定されている場合はそれに従う
        2. JetRacerクライアントが接続されている場合はJetRacerモード
        3. InputBundleにJetRacer関連のソースがあればJetRacerモード
        4. それ以外は一般会話モード
        
        Args:
            bundle: 入力バンドル
            
        Returns:
            True: JetRacerモード、False: 一般会話モード
        """
        # 1. オーバーライドが指定されている場合
        if self._jetracer_mode_override is not None:
            return self._jetracer_mode_override
        
        # 2. JetRacerクライアントが接続されている場合
        if self._jetracer_client is not None:
            return True
        
        # 3. InputBundleにJetRacer関連のソースがあるかチェック
        # InputSource.is_jetracer プロパティを使用
        for source in bundle.sources:
            if source.is_jetracer:
                return True
        
        # 4. それ以外は一般会話モード
        return False

    def run_continuous(
        self,
        input_generator: Callable[[], Optional[InputBundle]],
        max_frames: Optional[int] = None,
        frame_interval: float = 3.0,
        turns_per_frame: int = 4,
        run_id: Optional[str] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        stop_callback: Optional[Callable[[], bool]] = None,
    ) -> DialogueResult:
        """
        連続実行モード（LIVE用）

        Args:
            input_generator: 入力を生成するコールバック
                - 呼び出し毎にInputBundleを返す
                - Noneを返すと終了
            max_frames: 最大フレーム数（None=無制限）
            frame_interval: フレーム間隔（秒）
            turns_per_frame: 1フレームあたりのターン数
            run_id: ランID
            event_callback: イベント通知コールバック
            stop_callback: 停止判定コールバック（Trueで停止）

        Returns:
            DialogueResult（全フレームの対話を含む）
        """
        import time

        if run_id is None:
            run_id = f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        print(f"=== UnifiedPipeline.run_continuous() started: {run_id} ===")

        all_turns: List[DialogueTurn] = []
        frame_count = 0
        last_frame_context: Optional[FrameContext] = None

        # イベント: セッション開始
        if event_callback:
            event_callback("session_start", {
                "run_id": run_id,
                "mode": "continuous",
                "frame_interval": frame_interval,
                "turns_per_frame": turns_per_frame,
            })

        try:
            while True:
                # 停止チェック
                if stop_callback and stop_callback():
                    print(f"    ⏹️ Stop requested")
                    break

                # フレーム数チェック
                if max_frames and frame_count >= max_frames:
                    print(f"    ✅ Max frames reached: {max_frames}")
                    break

                # 入力取得
                bundle = input_generator()
                if bundle is None:
                    print(f"    ⏹️ Input generator returned None")
                    break

                print(f"\n--- Frame {frame_count + 1} ---")

                # 1フレーム分の対話生成
                result = self.run(
                    initial_input=bundle,
                    max_turns=turns_per_frame,
                    run_id=f"{run_id}_f{frame_count}",
                    event_callback=event_callback,
                )

                # 結果を蓄積
                all_turns.extend(result.dialogue)
                last_frame_context = result.frame_context
                frame_count += 1

                # フレーム完了イベント
                if event_callback:
                    event_callback("frame_complete", {
                        "run_id": run_id,
                        "frame": frame_count,
                        "turns": len(result.dialogue),
                        "status": result.status,
                    })

                # エラー時は中断
                if result.status == "error":
                    print(f"    ❌ Frame error: {result.error}")
                    break

                # 次のフレームまで待機
                time.sleep(frame_interval)

        except KeyboardInterrupt:
            print(f"\n    ⏹️ Interrupted by user")

        # セッション終了イベント
        if event_callback:
            event_callback("session_end", {
                "run_id": run_id,
                "total_frames": frame_count,
                "total_turns": len(all_turns),
            })

        print(f"=== UnifiedPipeline.run_continuous() completed: {run_id} ===")
        print(f"    Frames: {frame_count}, Turns: {len(all_turns)}")

        return DialogueResult(
            run_id=run_id,
            dialogue=all_turns,
            status="success",
            frame_context=last_frame_context,
            metadata={
                "mode": "continuous",
                "total_frames": frame_count,
                "total_turns": len(all_turns),
            },
        )

    def reset(self) -> None:
        """パイプライン状態をリセット"""
        self.director.reset_for_new_session()
        self.char_a = None
        self.char_b = None
        # Memory RAGの使用済み記憶をリセット（ループ防止機構）
        memory_rag = get_memory_rag()
        used_counts = memory_rag.reset_used_memories()
        print(f"[UnifiedPipeline] State reset (freed {used_counts['episodes']} episodes, {used_counts['facts']} facts)")
