"""
Director LLM that orchestrates character dialogue.
Monitors: 進行度 (progress), 参加度 (participation), 知識領域 (knowledge domain)
"""

from typing import Optional

from src.llm_client import get_llm_client
from src.config import config
from src.types import DirectorEvaluation, DirectorStatus
from src.prompt_manager import get_prompt_manager


class Director:
    """Director LLM that monitors and guides character responses"""

    def __init__(self):
        self.llm = get_llm_client()
        # Load director system prompt using PromptManager
        self.prompt_manager = get_prompt_manager("director")
        self.system_prompt = self.prompt_manager.get_system_prompt()

    def _default_system_prompt(self) -> str:
        """Default director prompt if file not found (deprecated)"""
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
        conversation_history: list = None,
    ) -> DirectorEvaluation:
        """
        Evaluate a character's response.

        Args:
            frame_description: Description of current frame
            speaker: "A" or "B"
            response: The character's response to evaluate
            partner_previous_speech: The other character's previous speech
            speaker_domains: List of domains this character should know (e.g., ["geography", "history"])
            conversation_history: List of (speaker, text) tuples for context

        Returns:
            DirectorEvaluation with status and reasoning
        """
        if speaker_domains is None:
            speaker_domains = (
                [
                    "sake",
                    "tourism_aesthetics",
                    "cultural_philosophy",
                    "human_action_reaction",
                    "phenomena",
                    "action",
                ]
                if speaker == "A"
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

        # 口調マーカーの事前チェック
        tone_check = self._check_tone_markers(speaker, response)
        if not tone_check["passed"]:
            # 口調マーカーが欠けている場合はRETRYを推奨
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=f"口調マーカー不足: {tone_check['missing']}",
                suggestion=f"以下のマーカーを含めてください: {', '.join(tone_check['expected'])}",
            )

        user_prompt = self._build_evaluation_prompt(
            frame_description=frame_description,
            speaker=speaker,
            response=response,
            partner_speech=partner_previous_speech,
            domains=speaker_domains,
            conversation_history=conversation_history,
        )

        try:
            result_text = self.llm.call(
                system=self.system_prompt,
                user=user_prompt,
                temperature=0.3,  # Lower temperature for consistency
                max_tokens=300,  # Increased for detailed evaluation
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

            # Build reason with issues if available
            reason = result.get("reason", "")
            issues = result.get("issues", [])
            if issues and isinstance(issues, list):
                reason_with_issues = f"{reason}\n- " + "\n- ".join(issues[:2])
            else:
                reason_with_issues = reason

            return DirectorEvaluation(
                status=status,
                reason=reason_with_issues,
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
        conversation_history: list = None,
    ) -> str:
        """Build comprehensive evaluation prompt checking all 5 criteria"""
        char_desc = "Elder Sister (やな) - action-driven, quick-witted" if speaker == "A" else "Younger Sister (あゆ) - logical, reflective, formal"
        domains_str = ", ".join(domains or [])

        # Character-specific tone markers
        tone_markers = (
            "「〜ね」「へ？」「わ！」「あ、そっか」などの感情マーカー"
            if speaker == "A"
            else "「です」「ですよ」「ですね」「姉様」などの敬語マーカー"
        )

        # Knowledge domain expectations
        domain_expectations = (
            "観光地の見どころ、人間の行動パターン、自然現象への反応、酒の知識"
            if speaker == "A"
            else "地理・歴史・建築・自然科学・作法・マナー、テック知識（但し長説は制止されるまで許容）"
        )

        prompt = f"""
【Current Frame】
{frame_description}

【Character】
{speaker} ({char_desc})

【Expected Knowledge Domains】
{domain_expectations}

【Actual Domains Listed】
{domains_str}

【Response to Evaluate】
{response}
"""

        # 対話履歴を追加（文脈の一貫性を評価するため）
        if conversation_history and len(conversation_history) > 1:
            recent_history = conversation_history[-4:]  # 直近4ターン
            history_text = "\n".join([f"{s}: {t}" for s, t in recent_history])
            prompt += f"""
【Recent Conversation History】
{history_text}
"""

        if partner_speech:
            prompt += f"""
【Partner's Previous Speech】
{partner_speech}
"""

        prompt += f"""
【5つの評価基準】

1. **進行度 (Progress)**: 現フレーム/シーンに対応しているか
   - 現フレームの内容に自然に反応している
   - 前フレームのネタを引きずっていない
   - 新しい話題に適切に対応している

2. **参加度 (Participation)**: キャラクターが積極的か
   - 受け身ではなく能動的に発言
   - 対話の流れを保ちながら参加
   - 相手の発言に自然に応答
   - 同じフレーズや言い回しを繰り返していない

3. **知識領域 (Knowledge Domain)**: 専門領域内か
   - {speaker}が話すべき領域：{domain_expectations}
   - 領域外の話題は避ける
   - 特例：あゆが新機材について話す場合、テック知識の「長説」は制止されるまで許容

4. **口調・一貫性 (Tone Consistency)**: 口調が一貫しているか
   - 必須マーカー：{tone_markers}
   - 話し方のスタイルが一貫
   - 適切な敬語・カジュアル度
   - 【重要】マーカーが1つも含まれていない場合はRETRY

5. **ナレーション品質 (Narration Quality)**: 面白く、簡潔か
   - 5文以内
   - 面白いコメント・視点がある
   - 観光ナレーション向きの内容
   - 相手の発言を適切に拾い、発展させている

【判定ルール】
- PASS: 5項目すべてクリア、自然で流れのある対話
- RETRY: 1-2つの小さな問題（特に口調マーカー不足）、同じ指示で改めてやらせる
- MODIFY: 大きな問題がある、修正指示を与えるか前に進める

【応答フォーマット】
JSON ONLY:
{{
  "status": "PASS" | "RETRY" | "MODIFY",
  "reason": "簡潔な理由（日本語OK、30-50字）",
  "issues": ["項目1の問題", "項目2の問題"],
  "suggestion": "修正案（RETRY/MODIFYの場合、具体的な改善点）"
}}
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
        next_speaker = 'A' if turn_number % 2 == 0 else 'B'
        next_char = "やな（姉）" if next_speaker == 'A' else "あゆ（妹）"
        char_style = (
            "カジュアルで感情的、「〜ね」「へ？」「わ！」を使う"
            if next_speaker == 'A'
            else "丁寧で論理的、「です」「ですよ」「姉様」を使う"
        )

        # 直近の会話を取得
        recent_conv = conversation_so_far[-3:] if len(conversation_so_far) > 3 else conversation_so_far
        conv_text = "\n".join([f"{'やな' if s == 'A' else 'あゆ'}: {t}" for s, t in recent_conv])

        user_prompt = f"""
【シーン】
{frame_description}

【直近の対話】
{conv_text}

【次の話者】
{next_char}（{char_style}）

【指示作成のポイント】
- 相手の発言をどう拾うべきか
- どんな角度で話を発展させるか
- 質問、同意、反論、追加情報のどれが自然か
- キャラクターの専門領域を活かせる点

上記を踏まえて、次の発言者への簡潔な指示（1-2文、日本語）を作成してください。
"""

        try:
            instruction = self.llm.call(
                system="あなたは対話の演出家です。キャラクター同士の対話を自然に進めるための簡潔な指示を出してください。",
                user=user_prompt,
                temperature=0.5,
                max_tokens=150,
            )
            return instruction.strip()
        except Exception:
            return ""  # Empty instruction on error

    @staticmethod
    def _format_conversation(conversation: list) -> str:
        """Format conversation history"""
        lines = []
        for speaker, text in conversation:
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    def _check_tone_markers(self, speaker: str, response: str) -> dict:
        """
        口調マーカーの存在をチェックする。

        Args:
            speaker: "A" or "B"
            response: 評価対象の発言

        Returns:
            {
                "passed": bool,
                "expected": list[str],
                "found": list[str],
                "missing": str
            }
        """
        if speaker == "A":
            # やな（姉）の口調マーカー
            markers = ["ね", "へ？", "わ！", "あ、", "そっか", "よね", "かな", "だね"]
            expected_desc = ["〜ね", "へ？", "わ！", "あ、そっか", "〜よね", "〜かな"]
        else:
            # あゆ（妹）の口調マーカー
            markers = ["です", "ですよ", "ですね", "姉様", "ございます", "でしょう"]
            expected_desc = ["です", "ですよ", "ですね", "姉様"]

        found = []
        for marker in markers:
            if marker in response:
                found.append(marker)

        # 最低1つのマーカーが必要
        passed = len(found) >= 1

        # 特別なケース: あゆは「です」系のいずれかが必須
        if speaker == "B":
            desu_variants = ["です", "ございます"]
            has_desu = any(m in response for m in desu_variants)
            passed = passed and has_desu

        return {
            "passed": passed,
            "expected": expected_desc,
            "found": found,
            "missing": "マーカーが見つかりません" if not found else "",
        }
