"""
Character implementation for dialogue generation.

v2.1 additions:
- DuoSignals: スレッドセーフな状態管理
- PromptBuilder: 優先度ベースのプロンプト組み立て
- NoveltyGuard: 話題ループ検知
- SilenceController: 沈黙判定
- world_rules.yaml: 世界設定の固定注入

v2.2 additions:
- jetracer_mode: JetRacer/一般会話モード切り替え
"""

from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import yaml

from src.llm_client import get_llm_client
from src.rag import get_rag_system
from src.config import config
from src.prompt_manager import get_prompt_manager
from src.beat_tracker import get_beat_tracker

# v2.1 imports
from src.signals import DuoSignals, SignalEvent, EventType
from src.injection import PromptBuilder, Priority, get_forbidden_context_manager, DualRAGInjector
from src.style_rag import get_style_rag
from src.memory_rag import get_memory_rag
from src.novelty_guard import NoveltyGuard, LoopBreakStrategy
from src.silence_controller import SilenceController
from src.prompt_loader import PromptLoader, CharacterPrompt, DirectorPrompt
from src.few_shot_injector import FewShotInjector
from src.sister_memory import get_sister_memory


class Character:
    """A character in the commentary dialogue"""

    def __init__(self, char_id: str, jetracer_mode: bool = False):
        """
        Initialize a character.

        Args:
            char_id: "A" (Elder Sister) or "B" (Younger Sister)
            jetracer_mode: True for JetRacer mode, False for general conversation
        """
        self.char_id = char_id
        self.jetracer_mode = jetracer_mode
        self.llm = get_llm_client()
        self.rag = get_rag_system()

        # Load system prompt using new PromptManager (mode-dependent)
        self.prompt_manager = get_prompt_manager(char_id, jetracer_mode=jetracer_mode)
        self.system_prompt = self.prompt_manager.get_system_prompt()

        # Character metadata
        self.name = "Elder Sister" if char_id == "A" else "Younger Sister"
        self.char_name = "やな" if char_id == "A" else "あゆ"

        # domains はモード依存（JetRacer vs 一般会話）
        self.domains = self._get_domains()

        # 最後に使用したRAGヒントを保存（外部からアクセス可能）
        self.last_rag_hints: List[str] = []

        # 最後に使用したプロンプトと応答を保存（デバッグ・GUI表示用）
        self.last_prompt: str = ""
        self.last_response: str = ""

        # Initialize beat tracker for pattern information
        self.beat_tracker = get_beat_tracker()

        # v2.1: Initialize new components
        self.signals = DuoSignals()
        self.novelty_guard = NoveltyGuard()
        self.silence_controller = SilenceController()

        # v2.1: Internal ID for file paths ("char_a" or "char_b")
        self.internal_id = "char_a" if char_id == "A" else "char_b"

        # v2.1: Initialize prompt loader and few-shot injector
        self.prompt_loader = PromptLoader("persona")

        # v2.2: FewShotInjector をモードに応じて初期化
        self.few_shot_injector = FewShotInjector()
        self.few_shot_injector.set_mode("jetracer" if jetracer_mode else "general")

        # v2.1: Sister memory for perspective-based recall
        self.sister_memory = get_sister_memory()

        # v2.1: Preload prompts （v2.2: モード対応）
        self._character_prompt: CharacterPrompt = self.prompt_loader.load_character(
            self.internal_id, jetracer_mode=jetracer_mode
        )
        self._director_prompt: DirectorPrompt = self.prompt_loader.load_director()
        self._world_rules: str = self.prompt_loader.load_world_rules(jetracer_mode=jetracer_mode)

        # v2.2: deep_values.yaml を読み込み
        self._deep_values = self._load_deep_values()

    def speak(
        self,
        frame_description: str,
        partner_speech: Optional[str] = None,
        director_instruction: Optional[str] = None,
        vision_info: Optional[str] = None,
        conversation_context: Optional[str] = None,
        dialogue_pattern: Optional[str] = None,
        beat_stage: Optional[str] = None,
        topic_guidance: Optional[dict] = None,
    ) -> str:
        """
        Generate a response for this character.

        Args:
            frame_description: Description of the current frame
            partner_speech: The other character's previous speech (if any)
            director_instruction: Special instruction from director (if any)
            vision_info: Vision processor output (【映像情報】... format) (optional)
            conversation_context: Recent conversation history for context (optional)
            dialogue_pattern: Pattern type ("A", "B", "C", "D", "E") from director
            beat_stage: Current beat stage ("SETUP", "EXPLORATION", etc.)
            topic_guidance: Director v3 topic management info (focus_hook, forbidden_topics, etc.)

        Returns:
            Character's response text

        .. deprecated::
            Use speak_unified() instead.
        """
        import warnings
        warnings.warn(
            "speak() is deprecated, use speak_unified() instead",
            DeprecationWarning,
            stacklevel=2
        )

        # Retrieve relevant knowledge from RAG
        rag_hints = self._get_rag_hints(
            query=frame_description,
            partner_speech=partner_speech,
        )

        # RAGヒントを保存（外部からアクセス可能にする）
        self.last_rag_hints = rag_hints

        # Build user prompt
        user_prompt = self._build_user_prompt(
            frame_description=frame_description,
            partner_speech=partner_speech,
            director_instruction=director_instruction,
            rag_hints=rag_hints,
            vision_info=vision_info,
            conversation_context=conversation_context,
            dialogue_pattern=dialogue_pattern,
            beat_stage=beat_stage,
            topic_guidance=topic_guidance,
        )

        # Call LLM with retry on repetition
        max_attempts = 2
        for attempt in range(max_attempts):
            # max_tokensを100に制限して散漫な長文応答を物理的に防止
            response = self.llm.call(
                system=self.system_prompt,
                user=user_prompt,
                temperature=config.temperature + (0.2 * attempt),  # Increase temp on retry
                max_tokens=100,  # 50〜80文字制限に合わせて短く
            )
            result = response.strip()

            # Check for repetition
            if not self._has_repetition(result):
                return result

            print(f"    ⚠️ 繰り返し検出 (試行 {attempt + 1}/{max_attempts}): 再生成中...")

        # If all attempts have repetition, return the last one anyway
        return result

    def speak_with_history(
        self,
        frame_description: str,
        conversation_history: List[Tuple[str, str]],  # [(speaker, text), ...]
        partner_speech: Optional[str] = None,
        director_instruction: Optional[str] = None,
        vision_info: Optional[str] = None,
        dialogue_pattern: Optional[str] = None,
        beat_stage: Optional[str] = None,
        topic_guidance: Optional[dict] = None,
    ) -> str:
        """
        Generate a response using stateful conversation history.

        Args:
            frame_description: Description of the current frame
            conversation_history: List of (speaker, text) tuples for full conversation
            partner_speech: The other character's previous speech (if any)
            director_instruction: Special instruction from director (if any)
            vision_info: Vision processor output (optional)
            dialogue_pattern: Pattern type from director
            beat_stage: Current beat stage
            topic_guidance: Director v3 topic management info

        Returns:
            Character's response text
        """
        # Retrieve relevant knowledge from RAG
        rag_hints = self._get_rag_hints(
            query=frame_description,
            partner_speech=partner_speech,
        )
        self.last_rag_hints = rag_hints

        # Build current turn prompt (without conversation context - it's in history)
        current_prompt = self._build_current_prompt(
            frame_description=frame_description,
            partner_speech=partner_speech,
            director_instruction=director_instruction,
            rag_hints=rag_hints,
            vision_info=vision_info,
            dialogue_pattern=dialogue_pattern,
            beat_stage=beat_stage,
            topic_guidance=topic_guidance,
        )

        # Call LLM with history and retry on repetition
        max_attempts = 2
        for attempt in range(max_attempts):
            response = self.llm.call_with_history(
                system=self.system_prompt,
                history=conversation_history,
                current_speaker=self.char_id,
                current_prompt=current_prompt,
                temperature=config.temperature + (0.2 * attempt),
                max_tokens=100,
            )
            result = response.strip()

            if not self._has_repetition(result):
                return result

            print(f"    ⚠️ 繰り返し検出 (試行 {attempt + 1}/{max_attempts}): 再生成中...")

        return result

    def _build_current_prompt(
        self,
        frame_description: str,
        partner_speech: Optional[str] = None,
        director_instruction: Optional[str] = None,
        rag_hints: List[str] = None,
        vision_info: Optional[str] = None,
        dialogue_pattern: Optional[str] = None,
        beat_stage: Optional[str] = None,
        topic_guidance: Optional[dict] = None,
    ) -> str:
        """
        Build prompt for current turn only (without conversation context).
        Used with call_with_history where history is passed separately.
        """
        lines = []

        lines.append("【Current Scene】")
        lines.append(frame_description)
        lines.append("")

        if dialogue_pattern:
            pattern_info = self.beat_tracker.get_pattern_info(dialogue_pattern)
            if pattern_info:
                role_key = "yana_role" if self.char_id == "A" else "ayu_role"
                my_role = pattern_info.get(role_key, "")
                pattern_name = pattern_info.get("name", "")
                example = pattern_info.get("example", "")

                lines.append("【対話パターン指示】")
                lines.append(f"パターン{dialogue_pattern}: {pattern_name}")
                lines.append(f"あなた（{self.char_name}）の役割: {my_role}")
                if example:
                    lines.append(f"例: {example}")
                lines.append("")

        if beat_stage:
            beat_info = self.beat_tracker.get_beat_info(beat_stage)
            if beat_info:
                lines.append("【ビート段階】")
                lines.append(f"{beat_stage}: {beat_info.get('goal', '')}")
                lines.append(f"トーン: {beat_info.get('tone', '')}")
                lines.append("")

        if vision_info:
            lines.append(vision_info)
            lines.append("")

        # NOTE: conversation_context is NOT added here - it's handled via history messages

        if partner_speech:
            lines.append("【Partner's Previous Speech】")
            lines.append(partner_speech)
            lines.append("")

        if director_instruction:
            lines.append("【Director's Guidance】")
            lines.append(director_instruction)
            lines.append("※上記の指示を意識して応答してください")
            lines.append("")

        # Director v3: Topic Management
        if topic_guidance and topic_guidance.get("focus_hook"):
            focus_hook = topic_guidance.get("focus_hook", "")
            forbidden = topic_guidance.get("forbidden_topics", [])
            character_role = topic_guidance.get("character_role", "")
            depth_step = topic_guidance.get("depth_step", "DISCOVER")
            hook_depth = topic_guidance.get("hook_depth", 0)
            partner_last_speech = topic_guidance.get("partner_last_speech", "")

            lines.append("【会話の流れ】")
            if partner_last_speech:
                preview = partner_last_speech[:50] + "..." if len(partner_last_speech) > 50 else partner_last_speech
                lines.append(f"前の発言: 「{preview}」")
            lines.append(f"今の話題: {focus_hook}（深さ {hook_depth}/3: {depth_step}）")
            lines.append("")
            lines.append("【重要】前の発言に自然に反応してください。無視しないでください。")
            if character_role:
                lines.append(f"あなたの役割: {character_role}")
            if forbidden:
                lines.append(f"※以下の話題は避けてください: {', '.join(forbidden)}")
            lines.append("")

        if rag_hints:
            lines.append("【Knowledge from your expertise】")
            for hint in rag_hints:
                lines.append(f"- {hint}")
            lines.append("")

        # キャラクターごとの口調リマインダー（モード依存）
        lines.extend(self._get_tone_reminder())

        lines.append("【出力形式】")
        lines.append("- 「」（かっこ）で囲まず、直接話してください")
        lines.append("- 1つの連続した発言として出力してください（複数ブロックに分けない）")
        lines.append("- 2-4文で簡潔に応答してください")

        return "\n".join(lines)

    def _get_tone_reminder(self) -> List[str]:
        """
        モードに応じた口調リマインダーを返す
        
        Returns:
            口調リマインダーの行リスト
        """
        lines = []
        
        if self.jetracer_mode:
            # JetRacerモード: エッジAI/クラウドAIとしての役割
            if self.char_id == "A":
                lines.append("【口調リマインダー】")
                lines.append("あなたは「やな」（姉/エッジAI）です。")
                lines.append("センサーやデバイスの状態を報告し、実際に動かす役割です。")
                lines.append("計算や分析が必要なときは「あゆ」に依頼してください。")
                lines.append("文末に「〜ね」「〜だね」「〜かな」などを使い、タメ口で話してください。")
                lines.append("「姉様」は使わないでください（あなたが姉です）。")
                lines.append("")
            else:
                lines.append("【口調リマインダー】")
                lines.append("あなたは「あゆ」（妹/クラウドAI）です。")
                lines.append("データを分析し、計算結果を提供する役割です。")
                lines.append("実機での検証が必要なときは「姉様」に依頼してください。")
                lines.append("文末は「です」「ですね」「ですよ」を使い、敬語で話してください。")
                lines.append("姉を「姉様」または「やな姉様」と呼んでください。")
                lines.append("センサー操作や物理動作は絶対にできません。")
                lines.append("")
        else:
            # 一般会話モード: 姉妹としての役割
            if self.char_id == "A":
                lines.append("【口調リマインダー】")
                lines.append("あなたは「やな」（姉）です。明るく活発、直感的に行動するタイプ。")
                lines.append("話題を見つけて切り出す「発見者」役。")
                lines.append("難しいことや詳しい分析は「あゆ」に聞いてください。")
                lines.append("文末に「〜ね」「〜だね」「〜かな」などを使い、タメ口で話してください。")
                lines.append("「姉様」は使わないでください（あなたが姉です）。")
                lines.append("")
            else:
                lines.append("【口調リマインダー】")
                lines.append("あなたは「あゆ」（妹）です。落ち着いていて論理的なタイプ。")
                lines.append("姉の発見に情報や分析を補足する「解説者」役。")
                lines.append("行動が必要なときは「姉様」に頼んでください。")
                lines.append("文末は「です」「ですね」「ですよ」を使い、敬語で話してください。")
                lines.append("姉を「姉様」または「やな姉様」と呼んでください。")
                lines.append("")

        return lines

    def _get_domains(self) -> List[str]:
        """
        モードに応じたドメインリストを返す

        Returns:
            キャラクターの専門ドメインリスト
        """
        if self.jetracer_mode:
            # JetRacerモード: エッジAI/クラウドAIとしての専門領域
            if self.char_id == "A":
                return [
                    "sensor_data",      # センサーデータ報告
                    "motor_control",    # モーター制御
                    "realtime_status",  # リアルタイム状態
                    "physical_test",    # 物理テスト実行
                    "device_operation", # デバイス操作
                ]
            else:
                return [
                    "data_analysis",    # データ分析
                    "optimization",     # 最適化計算
                    "prediction",       # 予測モデル
                    "ml_inference",     # 機械学習推論
                    "technical_theory", # 技術理論
                    "risk_assessment",  # リスク評価
                ]
        else:
            # 一般会話モード: 姉妹としての役割ベース
            if self.char_id == "A":
                return [
                    "discovery",        # 発見・気づき
                    "intuition",        # 直感・感覚
                    "action",           # 行動・実行
                    "social",           # 社交・コミュニケーション
                    "trends",           # トレンド・流行
                ]
            else:
                return [
                    "analysis",         # 分析・考察
                    "information",      # 情報・知識
                    "logic",            # 論理・理論
                    "research",         # 調査・リサーチ
                    "planning",         # 計画・段取り
                ]

    def _load_deep_values(self) -> Dict[str, Any]:
        """
        deep_values.yaml を読み込む

        Returns:
            深層価値観の辞書（存在しない場合は空辞書）
        """
        path = config.project_root / f"persona/{self.internal_id}/deep_values.yaml"
        if not path.exists():
            return {}

        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: Failed to load deep_values.yaml: {e}")
            return {}

    def _format_deep_values(self) -> str:
        """
        deep_values を注入用テキストにフォーマット

        Returns:
            フォーマットされた文字列（空の場合は空文字列）
        """
        if not self._deep_values:
            return ""

        lines = [f"【{self.char_name}の価値観】"]

        # core_belief
        if belief := self._deep_values.get("core_belief"):
            lines.append(f"信条: {belief}")

        # quick_rules（判断基準）
        if rules := self._deep_values.get("quick_rules"):
            lines.append("判断基準:")
            for rule in rules[:3]:  # 最大3つ
                lines.append(f"  - {rule}")

        # preferences（ワクワク/イライラ）- 状況に応じて使用
        # ここでは簡潔に1行だけ
        if prefs := self._deep_values.get("preferences"):
            if exciting := prefs.get("exciting"):
                lines.append(f"ワクワクすること: {exciting[0]}")  # 最初の1つだけ

        return "\n".join(lines)

    def _has_repetition(self, text: str, threshold: int = 5) -> bool:
        """
        テキストに異常な繰り返しがあるかチェック。

        Args:
            text: チェック対象のテキスト
            threshold: 繰り返しと判定する回数

        Returns:
            繰り返しがある場合True
        """
        import re

        if not text or len(text) < 10:
            return False

        # 同じ文字がthreshold回以上連続
        prev_char = ""
        count = 1
        for char in text:
            if char == prev_char:
                count += 1
                if count >= threshold:
                    return True
            else:
                count = 1
            prev_char = char

        # 同じ2-4文字の単語が4回以上連続（例: "鳥鳥鳥鳥"）
        if re.search(r'(.{2,4})\1{3,}', text):
            return True

        return False

    def _get_rag_hints(
        self,
        query: Optional[str],
        partner_speech: Optional[str] = None,
        top_k: int = 2,
    ) -> List[str]:
        """
        Retrieve relevant knowledge hints from RAG.

        Args:
            query: Search query (frame description or conversation)
            partner_speech: Partner's speech to consider
            top_k: Number of hints to retrieve

        Returns:
            List of knowledge snippets
        """
        # Build query from available context
        parts = []
        if query:
            parts.append(query)
        if partner_speech:
            parts.append(partner_speech)

        full_query = "\n".join(parts) if parts else None

        # Return empty if no query context available
        if not full_query:
            return []

        results = self.rag.retrieve_for_character(
            char_id=self.char_id,
            query=full_query,
            top_k=top_k,
        )

        # Format results as hints
        hints = []
        for domain, snippet in results:
            hints.append(f"[{domain}] {snippet}")

        return hints

    def _build_user_prompt(
        self,
        frame_description: str,
        partner_speech: Optional[str] = None,
        director_instruction: Optional[str] = None,
        rag_hints: List[str] = None,
        vision_info: Optional[str] = None,
        conversation_context: Optional[str] = None,
        dialogue_pattern: Optional[str] = None,
        beat_stage: Optional[str] = None,
        topic_guidance: Optional[dict] = None,
    ) -> str:
        """Build the user prompt for LLM with pattern guidance"""
        lines = []

        lines.append("【Current Scene】")
        lines.append(frame_description)
        lines.append("")

        # Add dialogue pattern guidance if provided
        if dialogue_pattern:
            pattern_info = self.beat_tracker.get_pattern_info(dialogue_pattern)
            if pattern_info:
                role_key = "yana_role" if self.char_id == "A" else "ayu_role"
                my_role = pattern_info.get(role_key, "")
                pattern_name = pattern_info.get("name", "")
                example = pattern_info.get("example", "")

                lines.append("【対話パターン指示】")
                lines.append(f"パターン{dialogue_pattern}: {pattern_name}")
                lines.append(f"あなた（{self.char_name}）の役割: {my_role}")
                if example:
                    lines.append(f"例: {example}")
                lines.append("")

        # Add beat stage context if provided
        if beat_stage:
            beat_info = self.beat_tracker.get_beat_info(beat_stage)
            if beat_info:
                lines.append("【ビート段階】")
                lines.append(f"{beat_stage}: {beat_info.get('goal', '')}")
                lines.append(f"トーン: {beat_info.get('tone', '')}")
                lines.append("")

        if vision_info:
            lines.append(vision_info)
            lines.append("")

        # 対話履歴の文脈を追加（直近の会話の流れを理解するため）
        if conversation_context:
            lines.append("【Recent Conversation】")
            lines.append(conversation_context)
            lines.append("")

        if partner_speech:
            lines.append("【Partner's Previous Speech】")
            lines.append(partner_speech)
            lines.append("")

        if director_instruction:
            lines.append("【Director's Guidance】")
            lines.append(director_instruction)
            lines.append("※上記の指示を意識して応答してください")
            lines.append("")

        # Director v3: Topic Management (修正版: 制限ではなくヒントとして)
        if topic_guidance and topic_guidance.get("focus_hook"):
            focus_hook = topic_guidance.get("focus_hook", "")
            forbidden = topic_guidance.get("forbidden_topics", [])
            character_role = topic_guidance.get("character_role", "")
            depth_step = topic_guidance.get("depth_step", "DISCOVER")
            hook_depth = topic_guidance.get("hook_depth", 0)
            partner_last_speech = topic_guidance.get("partner_last_speech", "")

            lines.append("【会話の流れ】")
            if partner_last_speech:
                # 直前の発言を表示（長い場合は省略）
                preview = partner_last_speech[:50] + "..." if len(partner_last_speech) > 50 else partner_last_speech
                lines.append(f"前の発言: 「{preview}」")
            lines.append(f"今の話題: {focus_hook}（深さ {hook_depth}/3: {depth_step}）")
            lines.append("")
            lines.append("【重要】前の発言に自然に反応してください。無視しないでください。")
            if character_role:
                lines.append(f"あなたの役割: {character_role}")
            if forbidden:
                lines.append(f"※以下の話題は避けてください: {', '.join(forbidden)}")
            lines.append("")

        if rag_hints:
            lines.append("【Knowledge from your expertise】")
            for hint in rag_hints:
                lines.append(f"- {hint}")
            lines.append("")

        # キャラクターごとの口調リマインダー（モード依存）
        lines.extend(self._get_tone_reminder())

        lines.append("【出力形式】")
        lines.append("- 「」（かっこ）で囲まず、直接話してください")
        lines.append("- 1つの連続した発言として出力してください（複数ブロックに分けない）")
        lines.append("- 2-4文で簡潔に応答してください")

        return "\n".join(lines)

    # ========================================
    # v2.1 Methods
    # ========================================

    def speak_v2(
        self,
        last_utterance: str,
        context: Optional[Dict[str, Any]] = None,
        frame_description: Optional[str] = None,
        dialogue_pattern: Optional[str] = None,
        owner_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        v2.1: キャラクターの応答を生成（新しいアーキテクチャ）

        Args:
            last_utterance: 直前の相手の発言
            context: 追加のコンテキスト情報
            frame_description: 現在のフレーム説明
            dialogue_pattern: 対話パターン（"A"〜"E"）
            owner_instruction: オーナーからの介入指示

        Returns:
            dict: {
                "type": "speech" | "silence",
                "content": str (speech) | dict (silence),
                "debug": dict
            }

        .. deprecated::
            Use speak_unified() instead.
        """
        import warnings
        warnings.warn(
            "speak_v2() is deprecated, use speak_unified() instead",
            DeprecationWarning,
            stacklevel=2
        )

        context = context or {}

        # 1. 状態のスナップショットを取得
        state = self.signals.snapshot()

        # 2. 沈黙判定
        silence = self.silence_controller.should_silence(state)
        if silence:
            return {
                "type": "silence",
                "content": silence.to_dict(),
                "debug": {"reason": "silence_controller"}
            }

        # 3. ループ検知
        loop_result = self.novelty_guard.check_and_update(last_utterance)

        # 4. プロンプト組み立て（PromptBuilder使用）
        builder = PromptBuilder()

        # 4.1 システムプロンプト
        builder.add(
            self.system_prompt,  # PromptManagerから取得
            Priority.SYSTEM,
            "system"
        )

        # 4.2 世界設定（固定注入）
        builder.add(
            self._world_rules,
            Priority.WORLD_RULES,
            "world_rules"
        )

        # 4.3 キャラクター設定
        builder.add(
            self._character_prompt.to_injection_text(),
            Priority.DEEP_VALUES,
            "character"
        )

        # 4.3.1 深層価値観（v2.2追加）
        deep_values_text = self._format_deep_values()
        if deep_values_text:
            builder.add(
                deep_values_text,
                Priority.DEEP_VALUES + 1,  # キャラクター設定の直後
                "deep_values"
            )

        # 4.4 RAG知識
        rag_hints = self._get_rag_hints(
            query=frame_description,
            partner_speech=last_utterance,
        )
        if rag_hints:
            builder.add(
                "【Knowledge from your expertise】\n" + "\n".join(f"- {h}" for h in rag_hints),
                Priority.RAG,
                "rag"
            )

        # 4.4.5 姉妹視点記憶（過去の関連体験）
        character_name = "yana" if self.char_id == "A" else "ayu"
        memories = self.sister_memory.search(
            query=frame_description or last_utterance,
            character=character_name,
            n_results=2
        )
        if memories:
            memory_text = "\n".join([m.to_prompt_text() for m in memories])
            builder.add(
                f"【関連する過去の記憶】\n{memory_text}",
                Priority.SISTER_MEMORY,
                "sister_memory"
            )

        # 4.5 会話履歴
        if context.get("history"):
            builder.add(
                self._format_history_v2(context["history"]),
                Priority.HISTORY,
                "history"
            )

        # 4.6 直前の発言（HISTORYの直後）
        other_name = "あゆ" if self.char_id == "A" else "やな"
        builder.add(
            f"【直前の{other_name}の発言】\n{last_utterance}",
            Priority.LAST_UTTERANCE,
            "last_utterance"
        )

        # 4.7 シーン情報
        if state.scene_facts:
            builder.add(
                f"【現在のシーン】\n{self._format_scene_v2(state.scene_facts)}",
                Priority.SCENE_FACTS,
                "scene"
            )

        # 4.8 走行状態（JetRacerモードのみ）
        if self.jetracer_mode:
            builder.add(
                self._format_world_state_v2(state),
                Priority.WORLD_STATE,
                "world_state"
            )

        # 4.9 スロット充足チェック
        unfilled = builder.check_and_inject_slots(
            state.current_topic or ("走行" if self.jetracer_mode else "対話"),
            topic_depth=state.topic_depth
        )

        # 4.10 ディレクター指示（ループ検知時のみ）
        if loop_result.loop_detected:
            # NoveltyGuardの注入を使用
            if loop_result.injection:
                builder.add(
                    loop_result.injection,
                    Priority.DIRECTOR,
                    "novelty_guard"
                )

            # ディレクターの戦略指示も追加
            strategy_instruction = self._director_prompt.get_strategy_instruction(
                loop_result.strategy.name
            )
            if strategy_instruction:
                builder.add(
                    f"【ディレクター補足】\n{strategy_instruction}",
                    Priority.DIRECTOR + 1,  # NoveltyGuardの直後
                    "director"
                )

        # 4.11 Few-shotパターン
        # イベントタイプの判定
        event_type = None
        if state.recent_events:
            last_event = state.recent_events[-1]
            if isinstance(last_event, dict):
                event_type = last_event.get("type")

        few_shot = self.few_shot_injector.select_pattern(
            signals_state=state,
            loop_strategy=loop_result.strategy if loop_result.loop_detected else None,
            event_type=event_type
        )
        if few_shot:
            builder.add(
                f"【参考: このような会話パターンで】\n{few_shot}",
                Priority.FEW_SHOT,
                "few_shot"
            )

        # 4.12 オーナー介入指示
        if owner_instruction:
            builder.add(
                owner_instruction,
                Priority.OWNER_INSTRUCTION,
                "owner_instruction"
            )

        # 5. プロンプト生成
        prompt = builder.build()

        # 6. LLM呼び出し
        response = self._call_llm(prompt, self.char_id)

        # 7. 会話イベントを記録
        self.signals.update(SignalEvent(
            event_type=EventType.CONVERSATION,
            data={
                "speaker": self._character_prompt.name,
                "topic": self._extract_topic(response),
                "unfilled_slots": unfilled
            }
        ))

        return {
            "type": "speech",
            "content": response,
            "debug": {
                "character": self._character_prompt.name,
                "loop_detected": loop_result.loop_detected,
                "strategy": loop_result.strategy.value if loop_result.loop_detected else None,
                "unfilled_slots": unfilled,
                "few_shot_used": few_shot is not None,
                "prompt_structure": builder.get_structure()
            }
        }

    def reload_prompts(self) -> None:
        """プロンプトを再読み込み（ホットリロード）"""
        self.prompt_loader.clear_cache()
        self._character_prompt = self.prompt_loader.load_character(
            self.internal_id, jetracer_mode=self.jetracer_mode
        )
        self._director_prompt = self.prompt_loader.load_director()
        self._world_rules = self.prompt_loader.load_world_rules(jetracer_mode=self.jetracer_mode)
        self._deep_values = self._load_deep_values()  # v2.2追加
        self.few_shot_injector.reload_patterns()
        # システムプロンプトも再読み込み
        from src.prompt_manager import get_prompt_repository
        get_prompt_repository().clear_cache()
        self.prompt_manager = get_prompt_manager(self.char_id, jetracer_mode=self.jetracer_mode)
        self.system_prompt = self.prompt_manager.get_system_prompt()

    def _get_system_prompt(self) -> str:
        """システムプロンプトを取得（モード依存）"""
        if self.jetracer_mode:
            return f"""あなたは「{self._character_prompt.name}」として振る舞ってください。
JetRacer自動運転車の走行を実況・解説する姉妹AIの一人です。

相手の発言に自然に反応し、キャラクターの個性を活かした短い発話を生成してください。
発話は1〜3文程度で、会話のテンポを維持してください。"""
        else:
            return f"""あなたは「{self._character_prompt.name}」として振る舞ってください。
仲の良い姉妹の一人として、自然な会話をしてください。

相手の発言に自然に反応し、キャラクターの個性を活かした短い発話を生成してください。
発話は1〜3文程度で、会話のテンポを維持してください。"""

    def _get_v2_character_prompt(self) -> str:
        """v2.1用のキャラクタープロンプトを取得（レガシー互換）"""
        if self.char_id == "A":
            return """## やな（姉/Edge AI）
- 発見役：「あ、なんか〜」「見て見て」
- 感覚表現：「なんか良い感じ」「ちょっと怖い」
- 口調：カジュアル、「〜じゃん」「〜でしょ」
- 判断基準：迷ったらとりあえず試す、数字より手応え"""
        else:
            return """## あゆ（妹/Cloud AI）
- 補足役：姉様の発見に数値や分析を付け加える
- 敬語ベース：ですます調だが堅すぎない
- やなを「姉様」と呼ぶ
- 判断基準：数字で裏付けてから判断、過去のログは宝"""

    def _format_history_v2(self, history: List[Dict[str, str]]) -> str:
        """v2.1: 会話履歴をフォーマット"""
        lines = ["【会話履歴】"]
        for h in history[-5:]:  # 直近5ターン
            speaker = h.get("speaker", "?")
            content = h.get("content", "")
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)

    def _format_scene_v2(self, scene_facts: Dict[str, str]) -> str:
        """v2.1: シーン情報をフォーマット"""
        parts = []
        for key, value in scene_facts.items():
            parts.append(f"- {key}: {value}")
        return "\n".join(parts)

    def _format_scene_facts(self, scene_facts: Dict[str, str]) -> str:
        """
        v2.2: DuoSignals.scene_factsをプロンプト用テキストにフォーマット

        Florence-2等からの視覚解析結果をキャラクターが理解しやすい形式に変換
        VisionToSignalsからの出力フィールドにも対応（Phase 0C）

        Args:
            scene_facts: DuoSignals.scene_factsの辞書

        Returns:
            フォーマットされたテキスト
        """
        if not scene_facts:
            return ""

        lines = ["【視覚情報（Florence-2解析）】"]

        # キャプション（シーン説明）
        if caption := scene_facts.get("caption"):
            lines.append(f"シーン: {caption}")

        # 検出物体（objects または detected_objects）
        detected = scene_facts.get("detected_objects") or scene_facts.get("objects")
        if detected:
            lines.append(f"検出物体: {detected}")

        # 主要物体（Phase 0C: VisionToSignals対応）
        if primary := scene_facts.get("primary_object"):
            lines.append(f"主要物体: {primary}")

        # 物体位置（Phase 0C: VisionToSignals対応）
        if position := scene_facts.get("position"):
            position_map = {
                "left": "左側",
                "right": "右側",
                "center": "中央",
            }
            lines.append(f"位置: {position_map.get(position, position)}")

        # シーンタイプ
        if scene_type := scene_facts.get("scene_type"):
            type_map = {
                "racing": "レーシング/走行",
                "indoor": "室内",
                "outdoor": "屋外",
                "unknown": "不明"
            }
            lines.append(f"シーンタイプ: {type_map.get(scene_type, scene_type)}")

        # 照明条件（Phase 0C: VisionToSignals対応）
        if lighting := scene_facts.get("lighting"):
            lighting_map = {
                "dark": "暗い（低照度）",
                "bright": "明るい",
                "normal": "通常",
            }
            lines.append(f"照明: {lighting_map.get(lighting, lighting)}")

        # 車線位置（Phase 0C: VisionToSignals対応）
        if lane := scene_facts.get("lane"):
            lane_map = {
                "left": "左寄り",
                "right": "右寄り",
                "center": "中央",
            }
            lines.append(f"車線位置: {lane_map.get(lane, lane)}")

        # 走行関連情報（JetRacerモード用）
        if self.jetracer_mode:
            if road_pct := scene_facts.get("road_percentage"):
                lines.append(f"走行可能領域: {road_pct}")
            if upcoming := scene_facts.get("upcoming"):
                upcoming_map = {
                    "straight": "直線",
                    "curve_left": "左カーブ",
                    "curve_right": "右カーブ",
                    "curve": "カーブ",
                    "corner": "コーナー",
                }
                lines.append(f"前方: {upcoming_map.get(upcoming, upcoming)}")

            # 障害物（最重要なので目立つように）
            if obstacle := scene_facts.get("obstacle"):
                lines.append(f"⚠️ 障害物検出: {obstacle}")
        else:
            # 一般モードでも障害物は表示
            if obstacle := scene_facts.get("obstacle"):
                lines.append(f"⚠️ 障害物: {obstacle}")

        # VLM自然言語記述（Phase 0C: VisionToSignals対応）
        if vlm_desc := scene_facts.get("vlm_description"):
            lines.append(f"VLM解析: {vlm_desc}")

        # タイムスタンプ情報（鮮度確認用）
        if timestamp := scene_facts.get("vision_timestamp"):
            try:
                from datetime import datetime
                ts = datetime.fromisoformat(timestamp)
                age = (datetime.now() - ts).total_seconds()
                lines.append(f"（{age:.1f}秒前の観測）")
            except (ValueError, TypeError):
                pass

        # その他の情報（上記以外）
        shown_keys = {
            "caption", "objects", "detected_objects", "primary_object", "position",
            "scene_type", "lighting", "lane", "road_percentage", "upcoming",
            "obstacle", "object_count", "vision_time_ms", "vlm_description",
            "vision_source", "vision_timestamp"
        }
        for key, value in scene_facts.items():
            if key not in shown_keys and value:
                lines.append(f"{key}: {value}")

        return "\n".join(lines)

    def _format_world_state_v2(self, state: Any) -> str:
        """v2.1: 走行状態をフォーマット（JetRacerモード用）"""
        return f"""【現在の走行状態】
- モード: {state.jetracer_mode}
- 速度: {state.current_speed:.2f} m/s
- 舵角: {state.steering_angle:.1f}°
- センサー: {state.distance_sensors}"""

    def _extract_topic(self, text: str) -> str:
        """テキストから主要トピックを抽出（簡易版）"""
        import re
        nouns = re.findall(r'[ァ-ヶー]{2,}|[一-龯]{2,}', text)
        return nouns[0] if nouns else ("走行" if self.jetracer_mode else "対話")

    def _call_llm(self, prompt: str, char_id: str) -> str:
        """
        v2.1: LLM呼び出しを統合

        Args:
            prompt: PromptBuilderで構築したプロンプト
            char_id: キャラクターID ("A" or "B")

        Returns:
            LLMの応答テキスト
        """
        # リトライロジック付きでLLMを呼び出し
        max_attempts = 2

        for attempt in range(max_attempts):
            response = self.llm.call(
                system=self.system_prompt,  # PromptManagerから取得
                user=prompt,
                temperature=config.temperature + (0.2 * attempt),
                max_tokens=100,  # 50〜80文字制限に合わせて短く
            )
            result = response.strip()

            # 繰り返しチェック
            if not self._has_repetition(result):
                return result

            print(f"    ⚠️ 繰り返し検出 (試行 {attempt + 1}/{max_attempts}): 再生成中...")

        # 全試行で繰り返しがあった場合は最後の結果を返す
        return result

    def update_signals(self, event: SignalEvent) -> None:
        """外部からシグナルを更新"""
        self.signals.update(event)

    def get_signals_snapshot(self) -> Any:
        """現在のシグナル状態を取得"""
        return self.signals.snapshot()

    # ========================================
    # Unified Speak Method (v2.2)
    # ========================================

    def speak_unified(
        self,
        frame_description: str,
        conversation_history: List[Tuple[str, str]],
        director_instruction: Optional[str] = None,
        vision_info: Optional[str] = None,
        topic_guidance: Optional[dict] = None,
        owner_instruction: Optional[str] = None,
    ) -> str:
        """
        統一されたspeakメソッド

        speak_with_history() と speak_v2() の長所を統合:
        - stateful履歴管理（speak_with_history由来）
        - PromptBuilder使用（speak_v2由来）
        - NoveltyGuardはDirector側で実行（重複排除のため、ここでは呼ばない）

        Args:
            frame_description: シーン説明（必須）
            conversation_history: [(speaker, text), ...] 形式の履歴
            director_instruction: Director からの指示
            vision_info: 視覚情報テキスト
            topic_guidance: Topic Manager情報
                - focus_hook: 現在の話題
                - hook_depth: 深さ(0-3)
                - depth_step: DISCOVER/WHY/EXPAND
                - forbidden_topics: 避ける話題リスト
                - character_role: キャラクターの役割
                - partner_last_speech: 直前の相手発言
            owner_instruction: オーナー介入指示

        Returns:
            生成された発話テキスト
        """
        # 1. PromptBuilder インスタンスを作成
        builder = PromptBuilder()

        # 2.1 システムプロンプト
        builder.add(
            self.system_prompt,  # PromptManagerから取得したものを使用
            Priority.SYSTEM,
            "system"
        )

        # 2.2 世界設定ルール
        builder.add(
            self._world_rules,
            Priority.WORLD_RULES,
            "world_rules"
        )

        # 2.3 キャラクター設定
        builder.add(
            self._character_prompt.to_injection_text(),
            Priority.DEEP_VALUES,
            "character"
        )

        # 2.3.1 深層価値観（v2.2追加）
        deep_values_text = self._format_deep_values()
        if deep_values_text:
            builder.add(
                deep_values_text,
                Priority.DEEP_VALUES + 1,
                "deep_values"
            )

        # 2.4 Dual-RAG注入（StyleRAG + MemoryRAG）
        partner_speech = conversation_history[-1][1] if conversation_history else None
        character_name = "yana" if self.char_id == "A" else "ayu"
        query = f"{frame_description}\n{partner_speech}" if partner_speech else frame_description

        # DualRAGInjectorを使用
        dual_rag_injector = DualRAGInjector(
            style_rag=get_style_rag(),
            memory_rag=get_memory_rag(),
            max_style_samples=3,
            max_episodes=2,
            max_facts=2,
            forbidden_context=get_forbidden_context_manager()
        )
        rag_result = dual_rag_injector.inject(
            builder=builder,
            character_id=character_name,
            query=query,
            emotion=None,  # 感情フィルタは後で実装可能
            include_style=True,
            include_memory=True
        )

        # GUI表示用に保存
        self.last_rag_hints = []
        if rag_result["style"] > 0:
            self.last_rag_hints.append(f"Style: {rag_result['style']}件")
            print(f"    🎭 Style RAG: {rag_result['style']}件のスタイルサンプルを注入")
        if rag_result["episodes"] > 0:
            self.last_rag_hints.append(f"Episodes: {rag_result['episodes']}件")
            print(f"    📖 Episode RAG: {rag_result['episodes']}件のエピソードを注入")
        if rag_result["facts"] > 0:
            self.last_rag_hints.append(f"Facts: {rag_result['facts']}件")
            print(f"    📋 Fact RAG: {rag_result['facts']}件の事実を注入")

        # 2.5 姉妹視点記憶（禁止コンテキストフィルター適用）
        character_name = "yana" if self.char_id == "A" else "ayu"
        memories = self.sister_memory.search(
            query=frame_description or (partner_speech or ""),
            character=character_name,
            n_results=5  # フィルタリング後に減る可能性があるため多めに取得
        )

        # 禁止コンテキストを除外
        if memories:
            forbidden_ctx = get_forbidden_context_manager()
            filtered_memories = []
            for m in memories:
                content = getattr(m, 'content', '') or getattr(m, 'text', '') or str(m)
                if not forbidden_ctx.is_forbidden(content):
                    filtered_memories.append(m)
                else:
                    print(f"    🚫 Memory filtered: {content[:30]}...")
            memories = filtered_memories[:2]  # 最大2件

        if memories:
            memory_text = "\n".join([m.to_prompt_text() for m in memories])
            builder.add(
                f"【関連する過去の記憶】\n{memory_text}",
                Priority.SISTER_MEMORY,
                "sister_memory"
            )
            memory_preview = memories[0].to_prompt_text()[:40] if memories else ""
            print(f"    🧠 Memory: {len(memories)}件の記憶を注入 ({memory_preview}...)")

        # 2.6 シーン情報
        builder.add(
            f"【Current Scene】\n{frame_description}",
            Priority.SCENE_FACTS,
            "scene"
        )

        # 2.6.1 DuoSignals.scene_facts（Florence-2等からの視覚情報）
        state = self.signals.snapshot()
        if state.scene_facts:
            scene_facts_text = self._format_scene_facts(state.scene_facts)
            builder.add(
                scene_facts_text,
                Priority.SCENE_FACTS + 1,
                "scene_facts"
            )

        # 2.7 視覚情報（引数で渡された追加情報）
        if vision_info:
            builder.add(
                vision_info,
                Priority.SCENE_FACTS + 2,
                "vision"
            )

        # 2.8 Topic Guidance（Director指示の直前）
        if topic_guidance:
            topic_text = self._format_topic_guidance(topic_guidance)
            if topic_text:
                builder.add(
                    topic_text,
                    Priority.DIRECTOR - 1,
                    "topic_guidance"
                )

        # 2.9 Director指示
        if director_instruction:
            builder.add(
                f"【Director's Guidance】\n{director_instruction}\n※上記の指示を意識して応答してください",
                Priority.DIRECTOR,
                "director"
            )

        # 2.10 オーナー介入指示
        if owner_instruction:
            builder.add(
                f"【オーナーからの指示】\n{owner_instruction}",
                Priority.OWNER_INSTRUCTION,
                "owner_instruction"
            )

        # 2.11 スロット充足チェック
        current_topic = topic_guidance.get("focus_hook", "対話") if topic_guidance else "対話"
        topic_depth = topic_guidance.get("hook_depth", 0) if topic_guidance else 0
        builder.check_and_inject_slots(
            current_topic=current_topic,
            topic_depth=topic_depth
        )

        # 2.12 Few-shot パターン
        state = self.signals.snapshot()
        event_type = None
        if state.recent_events:
            last_event = state.recent_events[-1]
            if isinstance(last_event, dict):
                event_type = last_event.get("type")

        few_shot = self.few_shot_injector.select_pattern(
            signals_state=state,
            loop_strategy=None,  # NoveltyGuardはDirector側で実行
            event_type=event_type
        )
        if few_shot:
            builder.add(
                f"【参考: このような会話パターンで】\n{few_shot}",
                Priority.FEW_SHOT,
                "few_shot"
            )

        # 3. プロンプトをビルド
        user_prompt = builder.build()

        # プロンプトを保存（デバッグ・GUI表示用）
        self.last_prompt = user_prompt

        # 4. LLM呼び出し
        return self._call_llm_with_prompt(user_prompt, conversation_history)

    def prepare_prompt_unified(
        self,
        frame_description: str,
        conversation_history: List[Tuple[str, str]],
        director_instruction: Optional[str] = None,
        vision_info: Optional[str] = None,
        topic_guidance: Optional[dict] = None,
        owner_instruction: Optional[str] = None,
    ) -> str:
        """
        プロンプトを準備して保存（LLM呼び出しはしない）

        speak_unified()と同じプロンプト構築ロジックを使用するが、
        LLMは呼び出さずにプロンプトを返すのみ。

        Returns:
            構築されたプロンプト文字列（self.last_promptにも保存される）
        """
        # speak_unified と同じプロンプト構築ロジックを実行
        builder = PromptBuilder()

        builder.add(self.system_prompt, Priority.SYSTEM, "system")  # PromptManagerから取得
        builder.add(self._world_rules, Priority.WORLD_RULES, "world_rules")
        builder.add(self._character_prompt.to_injection_text(), Priority.DEEP_VALUES, "character")

        deep_values_text = self._format_deep_values()
        if deep_values_text:
            builder.add(deep_values_text, Priority.DEEP_VALUES + 1, "deep_values")

        # Dual-RAG注入
        partner_speech = conversation_history[-1][1] if conversation_history else None
        character_name = "yana" if self.char_id == "A" else "ayu"
        query = f"{frame_description}\n{partner_speech}" if partner_speech else frame_description

        dual_rag_injector = DualRAGInjector(
            style_rag=get_style_rag(),
            memory_rag=get_memory_rag(),
            max_style_samples=3,
            max_episodes=2,
            max_facts=2,
            forbidden_context=get_forbidden_context_manager()
        )
        rag_result = dual_rag_injector.inject(
            builder=builder,
            character_id=character_name,
            query=query,
            emotion=None,
            include_style=True,
            include_memory=True
        )

        self.last_rag_hints = []
        if rag_result["style"] > 0:
            self.last_rag_hints.append(f"Style: {rag_result['style']}件")
        if rag_result["episodes"] > 0:
            self.last_rag_hints.append(f"Episodes: {rag_result['episodes']}件")
        if rag_result["facts"] > 0:
            self.last_rag_hints.append(f"Facts: {rag_result['facts']}件")

        # 姉妹視点記憶
        memories = self.sister_memory.search(
            query=frame_description or (partner_speech or ""),
            character=character_name,
            n_results=5
        )
        if memories:
            forbidden_ctx = get_forbidden_context_manager()
            filtered_memories = [m for m in memories if not forbidden_ctx.is_forbidden(
                getattr(m, 'content', '') or getattr(m, 'text', '') or str(m)
            )][:2]
            if filtered_memories:
                memory_text = "\n".join([m.to_prompt_text() for m in filtered_memories])
                builder.add(f"【関連する過去の記憶】\n{memory_text}", Priority.SISTER_MEMORY, "sister_memory")

        builder.add(f"【Current Scene】\n{frame_description}", Priority.SCENE_FACTS, "scene")

        state = self.signals.snapshot()
        if state.scene_facts:
            scene_facts_text = self._format_scene_facts(state.scene_facts)
            builder.add(scene_facts_text, Priority.SCENE_FACTS + 1, "scene_facts")

        if vision_info:
            builder.add(vision_info, Priority.SCENE_FACTS + 2, "vision")

        if topic_guidance:
            topic_text = self._format_topic_guidance(topic_guidance)
            if topic_text:
                builder.add(topic_text, Priority.DIRECTOR - 1, "topic_guidance")

        if director_instruction:
            builder.add(
                f"【Director's Guidance】\n{director_instruction}\n※上記の指示を意識して応答してください",
                Priority.DIRECTOR,
                "director"
            )

        if owner_instruction:
            builder.add(f"【オーナーからの指示】\n{owner_instruction}", Priority.OWNER_INSTRUCTION, "owner_instruction")

        current_topic = topic_guidance.get("focus_hook", "対話") if topic_guidance else "対話"
        topic_depth = topic_guidance.get("hook_depth", 0) if topic_guidance else 0
        builder.check_and_inject_slots(current_topic=current_topic, topic_depth=topic_depth)

        event_type = None
        if state.recent_events:
            last_event = state.recent_events[-1]
            if isinstance(last_event, dict):
                event_type = last_event.get("type")

        few_shot = self.few_shot_injector.select_pattern(
            signals_state=state,
            loop_strategy=None,
            event_type=event_type
        )
        if few_shot:
            builder.add(f"【参考: このような会話パターンで】\n{few_shot}", Priority.FEW_SHOT, "few_shot")

        user_prompt = builder.build()
        self.last_prompt = user_prompt
        return user_prompt

    def generate_from_prepared_prompt(
        self,
        conversation_history: List[Tuple[str, str]],
    ) -> str:
        """
        準備済みのプロンプト（self.last_prompt）を使ってLLMを呼び出す

        prepare_prompt_unified()を先に呼び出しておく必要がある。

        Returns:
            生成された発話テキスト
        """
        if not self.last_prompt:
            raise ValueError("プロンプトが準備されていません。prepare_prompt_unified()を先に呼び出してください。")

        return self._call_llm_with_prompt(self.last_prompt, conversation_history)

    def _call_llm_with_prompt(
        self,
        user_prompt: str,
        conversation_history: List[Tuple[str, str]],
    ) -> str:
        """
        プロンプトを使ってLLMを呼び出す（内部メソッド）
        """
        max_attempts = 2
        result = ""

        for attempt in range(max_attempts):
            response = self.llm.call_with_history(
                system=self.system_prompt,  # PromptManagerから取得
                history=conversation_history,
                current_speaker=self.char_id,
                current_prompt=user_prompt,
                temperature=config.temperature + (0.2 * attempt),
                max_tokens=100,
            )
            result = response.strip()

            # 繰り返しチェック
            if not self._has_repetition(result):
                self.last_response = result
                return result

            print(f"    ⚠️ 繰り返し検出 (試行 {attempt + 1}/{max_attempts}): 再生成中...")

        self.last_response = result
        return result

    def _format_topic_guidance(self, guidance: dict) -> str:
        """
        Topic Guidanceをフォーマット

        Args:
            guidance: Topic Manager情報

        Returns:
            フォーマットされた文字列
        """
        if not guidance:
            return ""

        lines = ["【会話の流れ】"]

        # 直前の相手発言（プレビュー）
        if partner_speech := guidance.get("partner_last_speech"):
            preview = partner_speech[:50]
            if len(partner_speech) > 50:
                preview += "..."
            lines.append(f"前の発言: 「{preview}」")

        # 話題と深度
        hook = guidance.get("focus_hook", "")
        depth = guidance.get("hook_depth", 0)
        step = guidance.get("depth_step", "DISCOVER")
        if hook:
            lines.append(f"話題: {hook}（深さ{depth}/3: {step}）")

        # キャラクター役割
        if role := guidance.get("character_role"):
            lines.append(f"役割: {role}")

        lines.append("")
        lines.append("【重要】前の発言に自然に反応してください。")

        # 禁止話題
        if forbidden := guidance.get("forbidden_topics"):
            lines.append(f"※避ける話題: {', '.join(forbidden)}")

        return "\n".join(lines)
