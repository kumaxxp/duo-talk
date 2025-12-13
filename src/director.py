"""
Director LLM that orchestrates character dialogue.
Monitors: 進行度 (progress), 参加度 (participation), 知識領域 (knowledge domain)
"""

from typing import Optional

from src.llm_client import get_llm_client
from src.config import config
from src.types import DirectorEvaluation, DirectorStatus


class Director:
    """Director LLM that monitors and guides character responses"""

    def __init__(self):
        self.llm = get_llm_client()
        # Load director system prompt
        director_prompt_path = config.project_root / "persona" / "director.prompt.txt"
        if director_prompt_path.exists():
            self.system_prompt = director_prompt_path.read_text(encoding="utf-8").strip()
        else:
            self.system_prompt = self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        """Default director prompt if file not found"""
        return """You are a film director orchestrating a natural dialogue between two characters watching a tourism video.

Your role:
1. Check PROGRESS: Is the response addressing the current frame content naturally?
2. Check PARTICIPATION: Are both characters engaged equally?
3. Check KNOWLEDGE DOMAIN: Does the character stay within their area of expertise?
4. Monitor TONE: Is the character maintaining consistent speech patterns?

Respond ONLY with JSON:
{
  "status": "PASS" | "RETRY" | "MODIFY",
  "reason": "Brief explanation",
  "suggestion": "How to improve (only for MODIFY)"
}"""

    def evaluate_response(
        self,
        frame_description: str,
        speaker: str,  # "A" or "B"
        response: str,
        partner_previous_speech: Optional[str] = None,
        speaker_domains: list = None,
    ) -> DirectorEvaluation:
        """
        Evaluate a character's response.

        Args:
            frame_description: Description of current frame
            speaker: "A" or "B"
            response: The character's response to evaluate
            partner_previous_speech: The other character's previous speech
            speaker_domains: List of domains this character should know (e.g., ["geography", "history"])

        Returns:
            DirectorEvaluation with status and reasoning
        """
        if speaker_domains is None:
            speaker_domains = (
                ["tourism", "action", "phenomena"]
                if speaker == "A"
                else ["geography", "history", "architecture"]
            )

        user_prompt = self._build_evaluation_prompt(
            frame_description=frame_description,
            speaker=speaker,
            response=response,
            partner_speech=partner_previous_speech,
            domains=speaker_domains,
        )

        try:
            result_text = self.llm.call(
                system=self.system_prompt,
                user=user_prompt,
                temperature=0.3,  # Lower temperature for consistency
                max_tokens=200,
            )

            # Parse JSON response
            import json
            try:
                result = json.loads(result_text)
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                if "PASS" in result_text.upper():
                    return DirectorEvaluation(
                        status=DirectorStatus.PASS,
                        reason="Response appears valid",
                    )
                elif "RETRY" in result_text.upper():
                    return DirectorEvaluation(
                        status=DirectorStatus.RETRY,
                        reason="Suggested retry",
                    )
                else:
                    return DirectorEvaluation(
                        status=DirectorStatus.MODIFY,
                        reason="Response needs adjustment",
                    )

            status_str = result.get("status", "PASS").upper()
            status = (
                DirectorStatus.PASS
                if status_str == "PASS"
                else DirectorStatus.RETRY
                if status_str == "RETRY"
                else DirectorStatus.MODIFY
            )

            return DirectorEvaluation(
                status=status,
                reason=result.get("reason", ""),
                suggestion=result.get("suggestion"),
            )

        except Exception as e:
            # Fallback evaluation
            return DirectorEvaluation(
                status=DirectorStatus.PASS,
                reason=f"Director evaluation error: {str(e)}",
            )

    def _build_evaluation_prompt(
        self,
        frame_description: str,
        speaker: str,
        response: str,
        partner_speech: Optional[str] = None,
        domains: list = None,
    ) -> str:
        """Build the evaluation prompt for the LLM"""
        char_desc = "Elder Sister (action-driven, quick-witted)" if speaker == "A" else "Younger Sister (logical, reflective)"
        domains_str = ", ".join(domains or [])

        prompt = f"""
【Current Frame】
{frame_description}

【Character】
{speaker} ({char_desc})

【Knowledge Domains】
{domains_str}

【Character's Response to Evaluate】
{response}
"""

        if partner_speech:
            prompt += f"""
【Partner's Previous Speech】
{partner_speech}
"""

        prompt += """
【Evaluation Tasks】
1. PROGRESS: Does this response directly address or naturally react to the frame content?
2. PARTICIPATION: Is the character actively engaged (not passive)?
3. KNOWLEDGE: Does the response use knowledge from their domains naturally, or overstep?
4. TONE: Does it match the character's speech pattern?

Respond ONLY with JSON having "status" (PASS/RETRY/MODIFY), "reason", and optionally "suggestion".
"""
        return prompt.strip()

    def get_instruction_for_next_turn(
        self,
        frame_description: str,
        conversation_so_far: list,
        turn_number: int,
    ) -> str:
        """
        Generate guidance instruction for the next character.

        Args:
            frame_description: Current frame description
            conversation_so_far: List of (speaker, text) tuples
            turn_number: Current turn number

        Returns:
            Instruction string to inject into character prompt
        """
        user_prompt = f"""
【Frame】
{frame_description}

【Conversation so far】
{self._format_conversation(conversation_so_far)}

【Next speaker】
{'A' if turn_number % 2 == 1 else 'B'}

Provide a brief (1-2 sentence) instruction for the next speaker to keep dialogue natural and engaging.
Focus on: What angle should they take? Should they question, expand, or challenge?
"""

        try:
            instruction = self.llm.call(
                system="You are a dialogue director. Provide brief, natural instructions.",
                user=user_prompt,
                temperature=0.5,
                max_tokens=100,
            )
            return instruction
        except Exception:
            return ""  # Empty instruction on error

    @staticmethod
    def _format_conversation(conversation: list) -> str:
        """Format conversation history"""
        lines = []
        for speaker, text in conversation:
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines)
