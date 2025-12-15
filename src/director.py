"""
Director LLM that orchestrates character dialogue.
Monitors: 進行度 (progress), 参加度 (participation), 知識領域 (knowledge domain)
Now includes fact-checking capability via web search.
"""

from typing import Optional

from src.llm_client import get_llm_client
from src.config import config
from src.types import DirectorEvaluation, DirectorStatus
from src.prompt_manager import get_prompt_manager
from src.beat_tracker import get_beat_tracker
from src.fact_checker import get_fact_checker, FactCheckResult


class Director:
    """Director LLM that monitors and guides character responses"""

    def __init__(self, enable_fact_check: bool = True):
        self.llm = get_llm_client()
        # Load director system prompt using PromptManager
        self.prompt_manager = get_prompt_manager("director")
        self.system_prompt = self.prompt_manager.get_system_prompt()
        # Initialize beat tracker for pattern management
        self.beat_tracker = get_beat_tracker()
        # Track recent patterns to avoid repetition
        self.recent_patterns: list[str] = []
        # Fact checker for verifying common sense
        self.enable_fact_check = enable_fact_check
        self.fact_checker = get_fact_checker() if enable_fact_check else None
        # Store last fact check result for debugging/logging
        self.last_fact_check: Optional[FactCheckResult] = None

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
        turn_number: int = 1,
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
            turn_number: Current turn number for beat tracking

        Returns:
            DirectorEvaluation with status, reasoning, and next pattern/instruction
        """
        # Get current beat stage from turn number
        current_beat = self.beat_tracker.get_current_beat(turn_number)
        beat_info = self.beat_tracker.get_beat_info(current_beat)
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

        # 出力形式のチェック（かっこ付き、複数ブロック）
        format_check = self._check_format(response)
        if not format_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=f"出力形式の問題: {format_check['issue']}",
                suggestion=format_check["suggestion"],
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

        # 口調マーカーの詳細情報を取得（LLM評価用）
        tone_info = self._check_tone_markers(speaker, response)

        # ファクトチェック（やなの発言のみ、次のあゆの発言で訂正させるため）
        fact_check_result: Optional[FactCheckResult] = None
        if self.enable_fact_check and self.fact_checker and speaker == "A":
            print("    🔍 ファクトチェック実行中...")
            fact_check_result = self.fact_checker.check_statement(
                statement=response,
                context=frame_description,
            )
            self.last_fact_check = fact_check_result

            if fact_check_result.has_error:
                print(f"    ⚠️  誤り検出: {fact_check_result.claim}")
                print(f"    ✓  正しい情報: {fact_check_result.correct_info}")
                print(f"    📊 確信度: {fact_check_result.search_confidence}")

        user_prompt = self._build_evaluation_prompt(
            frame_description=frame_description,
            speaker=speaker,
            response=response,
            partner_speech=partner_previous_speech,
            domains=speaker_domains,
            conversation_history=conversation_history,
            tone_markers_found=tone_info["found"],
            turn_number=turn_number,
            current_beat=current_beat,
            beat_info=beat_info,
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
            import re

            # Remove markdown code block if present
            json_text = result_text.strip()
            if json_text.startswith("```"):
                # Extract content between ```json and ```
                match = re.search(r"```(?:json)?\s*([\s\S]*?)```", json_text)
                if match:
                    json_text = match.group(1).strip()

            try:
                result = json.loads(json_text)
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

            # Extract new orchestration fields
            next_pattern = result.get("next_pattern")
            next_instruction = result.get("next_instruction")
            beat_stage = result.get("beat_stage", current_beat)

            # ファクトチェックで誤りが見つかった場合、訂正パターンに切り替え
            if fact_check_result and fact_check_result.has_error:
                # パターンC（誤解→訂正）を強制
                next_pattern = "C"
                # 訂正指示を追加
                correction_instruction = fact_check_result.correction_prompt
                if next_instruction:
                    next_instruction = f"{correction_instruction}\n\n（追加指示）{next_instruction}"
                else:
                    next_instruction = correction_instruction
                print(f"    🎬 パターンを訂正モード(C)に変更")

            # Validate and track pattern
            if next_pattern and next_pattern in ["A", "B", "C", "D", "E"]:
                # Check if pattern is allowed
                if not self.beat_tracker.is_pattern_allowed(next_pattern, self.recent_patterns):
                    # Suggest alternative pattern
                    next_pattern = self.beat_tracker.suggest_pattern(turn_number, self.recent_patterns)
                self.recent_patterns.append(next_pattern)
                # Keep only last 5 patterns
                if len(self.recent_patterns) > 5:
                    self.recent_patterns = self.recent_patterns[-5:]
            else:
                # Fallback: use beat tracker to suggest pattern
                next_pattern = self.beat_tracker.suggest_pattern(turn_number, self.recent_patterns)
                self.recent_patterns.append(next_pattern)

            return DirectorEvaluation(
                status=status,
                reason=reason_with_issues,
                suggestion=result.get("suggestion"),
                next_pattern=next_pattern,
                next_instruction=next_instruction,
                beat_stage=beat_stage,
            )

        except Exception as e:
            # Fallback evaluation with beat tracking
            fallback_pattern = self.beat_tracker.suggest_pattern(turn_number, self.recent_patterns)
            self.recent_patterns.append(fallback_pattern)
            return DirectorEvaluation(
                status=DirectorStatus.PASS,
                reason=f"Director evaluation error: {str(e)}",
                next_pattern=fallback_pattern,
                beat_stage=current_beat,
            )

    def _build_evaluation_prompt(
        self,
        frame_description: str,
        speaker: str,
        response: str,
        partner_speech: Optional[str] = None,
        domains: list = None,
        conversation_history: list = None,
        tone_markers_found: list = None,
        turn_number: int = 1,
        current_beat: str = "SETUP",
        beat_info: dict = None,
    ) -> str:
        """Build comprehensive evaluation prompt checking all 5 criteria with beat orchestration"""
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

        # Get beat-specific information
        if beat_info is None:
            beat_info = {}
        beat_goal = beat_info.get("goal", "シーンの進行")
        beat_tone = beat_info.get("tone", "自然")
        preferred_patterns = beat_info.get("preferred_patterns", ["A", "B"])
        preferred_patterns_str = ", ".join(preferred_patterns)

        # Pattern descriptions for LLM guidance
        pattern_guide = """
対話パターン説明:
  A: 発見→補足（やな:発見・驚き → あゆ:情報補足）
  B: 疑問→解説（やな:質問 → あゆ:回答）
  C: 誤解→訂正（やな:勘違い → あゆ:訂正）
  D: 脱線→修正（やな:話題脱線 → あゆ:軌道修正）
  E: 共感→発展（やな:感想 → あゆ:発展情報）"""

        prompt = f"""
【Current Frame】
{frame_description}

【Character】
{speaker} ({char_desc})

【Turn Info】
ターン {turn_number} / ビート段階: {current_beat}
ビート目標: {beat_goal}
推奨パターン: {preferred_patterns_str}
{pattern_guide}

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

        # 口調マーカーの検証状況を追加
        tone_status = ""
        if tone_markers_found:
            markers_str = ", ".join([f'「{m}」' for m in tone_markers_found[:3]])
            tone_status = f"\n【口調マーカー検証結果】✓ 検出済み: {markers_str} → 口調は問題なし"
        else:
            tone_status = "\n【口調マーカー検証結果】✗ 未検出 → 口調に注意が必要"

        prompt += f"""
{tone_status}

【4つの評価基準】（口調マーカーは事前検証済み）

1. **進行度 (Progress)**: 現フレーム/シーンに対応しているか
   - 現フレームの内容に自然に反応している
   - 前フレームのネタを引きずっていない

2. **参加度 (Participation)**: キャラクターが積極的か
   - 受け身ではなく能動的に発言
   - 相手の発言に自然に応答
   - 同じフレーズや言い回しを繰り返していない

3. **知識領域 (Knowledge Domain)**: 専門領域内か
   - {speaker}が話すべき領域：{domain_expectations}
   - 領域外の話題は避ける

4. **ナレーション品質 (Narration Quality)**: 面白く、簡潔か
   - 5文以内
   - 相手の発言を適切に拾い、発展させている

【判定ルール】
- PASS: 4項目すべてクリア、自然で流れのある対話（口調マーカーは事前検証済みなのでPASS推奨）
- RETRY: 同じフレーズの繰り返しや明らかな問題がある場合のみ
- MODIFY: 大きな問題がある

【応答フォーマット】
JSON ONLY:
{{
  "status": "PASS" | "RETRY" | "MODIFY",
  "reason": "簡潔な理由（日本語OK、30-50字）",
  "issues": ["項目1の問題", "項目2の問題"],
  "suggestion": "修正案（RETRY/MODIFYの場合、具体的な改善点）",
  "next_pattern": "A" | "B" | "C" | "D" | "E",
  "next_instruction": "次の発言者への具体的指示（1-2文、日本語）",
  "beat_stage": "{current_beat}"
}}

【振付指示について】
- next_pattern: 現在のビート段階に合った推奨パターン（{preferred_patterns_str}）から選択
- next_instruction: 次の発言者が何に注目・反応すべきか具体的に指示
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
            # あゆ（妹）の口調マーカー（「姉様」は毎回不要なので必須から除外）
            markers = ["です", "ですよ", "ですね", "ございます", "でしょう"]
            expected_desc = ["です", "ですね", "ですよ"]

        found = []
        for marker in markers:
            if marker in response:
                found.append(marker)

        # 最低1つのマーカーが必要
        passed = len(found) >= 1

        # 特別なケース: やなは「姉様」を使ってはいけない（あゆの呼び方）
        if speaker == "A":
            forbidden_words = ["姉様"]
            for forbidden in forbidden_words:
                if forbidden in response:
                    return {
                        "passed": False,
                        "expected": expected_desc,
                        "found": found,
                        "missing": f"禁止ワード「{forbidden}」を使用（やなは姉なので「姉様」は使えません）",
                    }

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

    def _check_format(self, response: str) -> dict:
        """
        出力形式をチェックする。

        Args:
            response: 評価対象の発言

        Returns:
            {
                "passed": bool,
                "issue": str,
                "suggestion": str
            }
        """
        # かっこで囲まれた発言のチェック
        # 「」で始まる発言は台本形式と判定
        stripped = response.strip()
        if stripped.startswith("「") or stripped.startswith("『"):
            return {
                "passed": False,
                "issue": "発言が「」で囲まれています（台本形式）",
                "suggestion": "「」を外して、直接話すように出力してください。例: わ！金閣寺だね！",
            }

        # 複数の「」ブロックがあるかチェック
        quote_count = response.count("「")
        if quote_count >= 2:
            return {
                "passed": False,
                "issue": f"複数の「」ブロックがあります（{quote_count}個）",
                "suggestion": "1つの連続した発言として出力してください。「」は使わず、直接話してください。",
            }

        # 改行で複数ブロックに分かれているかチェック
        lines = [line.strip() for line in response.split("\n") if line.strip()]
        if len(lines) > 2:
            return {
                "passed": False,
                "issue": f"発言が複数行に分かれています（{len(lines)}行）",
                "suggestion": "1つの連続した発言として、改行なしで出力してください。",
            }

        return {
            "passed": True,
            "issue": "",
            "suggestion": "",
        }
