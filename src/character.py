"""
Character implementation for dialogue generation.
"""

from pathlib import Path
from typing import List, Optional

from src.llm_client import get_llm_client
from src.rag import get_rag_system
from src.config import config


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

        # Load system prompt
        prompt_path = config.project_root / "persona" / f"char_{char_id}.prompt.txt"
        if prompt_path.exists():
            self.system_prompt = prompt_path.read_text(encoding="utf-8").strip()
        else:
            self.system_prompt = self._default_system_prompt()

        # Character metadata
        self.name = "Elder Sister" if char_id == "A" else "Younger Sister"
        self.domains = (
            ["tourism", "action", "phenomena"]
            if char_id == "A"
            else ["geography", "history", "architecture"]
        )

    def _default_system_prompt(self) -> str:
        """Default system prompt if file not found"""
        if self.char_id == "A":
            return """You are the Elder Sister in a tourism video commentary.
Your personality: Action-driven, quick-witted, direct, energetic.
Your role: React to what's happening, ask questions, express emotions naturally.
Speech style: Casual, use "〜ね", "〜だよ", "へ？", "わ" or similar markers.
Length: Keep responses concise (2-4 sentences max).
Never: Provide long explanations or summaries. Avoid being preachy.
Your expertise: Tourism activities, action sequences, phenomena and reactions."""
        else:
            return """You are the Younger Sister in a tourism video commentary.
Your personality: Cool, logical, analytical, thoughtful.
Your role: Provide context, explain things, offer perspective.
Speech style: Calm, use "〜な", "ちょっと待て", "なるほど" or similar markers.
Length: Keep responses concise (2-4 sentences max).
Never: Provide long explanations or summaries. Avoid being condescending.
Your expertise: Geography, history, architecture, natural phenomena."""

    def speak(
        self,
        frame_description: str,
        partner_speech: Optional[str] = None,
        director_instruction: Optional[str] = None,
    ) -> str:
        """
        Generate a response for this character.

        Args:
            frame_description: Description of the current frame
            partner_speech: The other character's previous speech (if any)
            director_instruction: Special instruction from director (if any)

        Returns:
            Character's response text
        """
        # Retrieve relevant knowledge from RAG
        rag_hints = self._get_rag_hints(
            query=frame_description,
            partner_speech=partner_speech,
        )

        # Build user prompt
        user_prompt = self._build_user_prompt(
            frame_description=frame_description,
            partner_speech=partner_speech,
            director_instruction=director_instruction,
            rag_hints=rag_hints,
        )

        # Call LLM
        response = self.llm.call(
            system=self.system_prompt,
            user=user_prompt,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        return response.strip()

    def _get_rag_hints(
        self,
        query: str,
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
        full_query = query
        if partner_speech:
            full_query = f"{query}\n{partner_speech}"

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
    ) -> str:
        """Build the user prompt for LLM"""
        lines = []

        lines.append("【Current Scene】")
        lines.append(frame_description)
        lines.append("")

        if partner_speech:
            lines.append("【Partner's Previous Speech】")
            lines.append(partner_speech)
            lines.append("")

        if director_instruction:
            lines.append("【Director's Guidance】")
            lines.append(director_instruction)
            lines.append("")

        if rag_hints:
            lines.append("【Knowledge from your expertise】")
            for hint in rag_hints:
                lines.append(f"- {hint}")
            lines.append("")

        lines.append("Respond naturally based on the above. Keep it brief (2-4 sentences).")

        return "\n".join(lines)
