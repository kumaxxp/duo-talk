"""
Character implementation for dialogue generation.
"""

from pathlib import Path
from typing import List, Optional

from src.llm_client import get_llm_client
from src.rag import get_rag_system
from src.config import config
from src.prompt_manager import get_prompt_manager
from src.beat_tracker import get_beat_tracker


class Character:
    """A character in the commentary dialogue"""

    def __init__(self, char_id: str):
        """
        Initialize a character.

        Args:
            char_id: "A" (Elder Sister) or "B" (Younger Sister)
        """
        self.char_id = char_id
        self.llm = get_llm_client()
        self.rag = get_rag_system()

        # Load system prompt using new PromptManager
        self.prompt_manager = get_prompt_manager(char_id)
        self.system_prompt = self.prompt_manager.get_system_prompt()

        # Character metadata
        self.name = "Elder Sister" if char_id == "A" else "Younger Sister"
        self.char_name = "やな" if char_id == "A" else "あゆ"
        self.domains = (
            [
                "sake",
                "tourism_aesthetics",
                "cultural_philosophy",
                "human_action_reaction",
                "phenomena",
                "action",
            ]
            if char_id == "A"
            else [
                "geography",
                "history",
                "architecture",
                "natural_science",
                "etiquette_and_manners",
                "gadgets_and_tech",
                "ai_base_construction",
            ]
        )

        # 最後に使用したRAGヒントを保存（外部からアクセス可能）
        self.last_rag_hints: List[str] = []

        # Initialize beat tracker for pattern information
        self.beat_tracker = get_beat_tracker()

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
        """
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

        # Director v3: Topic Management
        if topic_guidance and topic_guidance.get("focus_hook"):
            focus_hook = topic_guidance.get("focus_hook", "")
            forbidden = topic_guidance.get("forbidden_topics", [])
            must_include = topic_guidance.get("must_include", [])
            character_role = topic_guidance.get("character_role", "")
            depth_step = topic_guidance.get("depth_step", "DISCOVER")
            hook_depth = topic_guidance.get("hook_depth", 0)

            lines.append("【話題制限】")
            lines.append(f"今の話題: 「{focus_hook}」（深さ {hook_depth}/3: {depth_step}）")
            if must_include:
                lines.append(f"必須ワード: {', '.join(must_include)}")
            if forbidden:
                lines.append(f"禁止話題: {', '.join(forbidden)}")
            if character_role:
                lines.append(f"あなたの役割: {character_role}")
            lines.append("※上記の話題についてのみ話し、他の話題には触れないでください")
            lines.append("")

        if rag_hints:
            lines.append("【Knowledge from your expertise】")
            for hint in rag_hints:
                lines.append(f"- {hint}")
            lines.append("")

        # キャラクターごとの口調リマインダー
        if self.char_id == "A":
            lines.append("【口調リマインダー】")
            lines.append("あなたは「やな」（姉）です。カジュアルで感情的な口調で話してください。")
            lines.append("文末に「〜ね」「〜だね」「〜かな」などを自然に使ってください。")
            lines.append("「わ！」「へ？」は本当に驚いた時だけ使い、毎回は使わないでください。")
            lines.append("妹のことは「あゆ」と呼びます。敬語は使わず、タメ口で話してください。")
            lines.append("「姉様」という呼び方は絶対に使わないでください（あなたが姉です）。")
            lines.append("")
        else:
            lines.append("【口調リマインダー】")
            lines.append("あなたは「あゆ」（妹）です。丁寧で論理的な口調で話してください。")
            lines.append("文末は「です」「ですね」「ですよ」を自然に使ってください。")
            lines.append("姉を「姉様」または「やな姉様」と呼びます（毎回は不要、自然なタイミングで）。")
            lines.append("「ございます」「〜ですですね」のような不自然な敬語は避けてください。")
            lines.append("")

        lines.append("【出力形式】")
        lines.append("- 「」（かっこ）で囲まず、直接話してください")
        lines.append("- 1つの連続した発言として出力してください（複数ブロックに分けない）")
        lines.append("- 2-4文で簡潔に応答してください")

        return "\n".join(lines)
