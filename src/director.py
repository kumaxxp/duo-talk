"""
Director LLM that orchestrates character dialogue.
Monitors: 進行度 (progress), 参加度 (participation), 知識領域 (knowledge domain)
Now includes fact-checking capability via web search.
"""

import re
from typing import Optional

from src.llm_client import get_llm_client
from src.config import config
from src.types import DirectorEvaluation, DirectorStatus
from src.prompt_manager import get_prompt_manager
from src.beat_tracker import get_beat_tracker
from src.fact_checker import get_fact_checker, FactCheckResult


class Director:
    """Director LLM that monitors and guides character responses"""

    # 誤爆防止用の定数
    VAGUE_WORDS = ["雰囲気", "なんか", "ちょっと", "違う", "感じ", "空気感", "気配", "気がする"]

    # 具体名詞のヒント（これがあれば曖昧語と組み合わさっていてもOK）
    SPECIFIC_HINTS = [
        "屋根", "看板", "鳥居", "提灯", "川", "山", "橋", "門", "石", "木",
        "光", "色", "人", "音", "匂い", "店", "屋台", "酒", "料理", "池", "鯉",
        "金", "銀", "赤", "緑", "青", "白", "黒", "建物", "庭", "道", "寺", "神社"
    ]

    # 絶対禁止ワード（強制NOOP）
    HARD_BANNED_WORDS = [
        "焦燥感", "期待", "ドキドキ", "ワクワク", "口調で", "トーンで",
        "興奮", "悲しげ", "嬉しそうに", "寂しそうに"
    ]

    # 要注意ワード（根拠なしならNOOP）
    SOFT_BANNED_WORDS = ["興味を示", "注目して", "気にして"]

    # 設定破壊検出用: 姉妹が別居しているかのような表現（絶対禁止）
    SEPARATION_WORDS = [
        "姉様のお家", "姉様の家", "姉様の実家",
        "あゆのお家", "あゆの家", "あゆの実家",
        "やなのお家", "やなの家", "やなの実家",
        "姉の家", "妹の家", "姉の実家", "妹の実家",
        "また来てね", "また遊びに来て", "お邪魔しました",
        # 「実家」は別居を連想させるため禁止（「うち」を使う）
        "実家では", "実家に", "実家の", "うちの実家",
    ]

    # あゆ（B）専用の褒め言葉チェック（やなには適用しない）
    PRAISE_WORDS_FOR_AYU = [
        "いい観点", "いい質問", "さすが", "鋭い",
        "おっしゃる通り", "その通り", "素晴らしい", "お見事",
        "よく気づ", "正解です", "大正解",
    ]

    # 観光地名（トピック無関係チェック用）
    TOURIST_SPOTS = [
        "金閣寺", "銀閣寺", "清水寺", "東大寺", "伏見稲荷",
        "厳島神社", "姫路城", "富士山", "浅草寺", "鎌倉大仏",
    ]

    # 話題ループ検出用の定数
    LOOP_KEYWORDS = [
        "おせち", "お年玉", "親戚", "挨拶", "初詣", "福袋", "雑煮",
        "お餅", "餅つき", "年賀状", "箱根駅伝", "紅白",
    ]
    LOOP_THRESHOLD = 3

    # 話題転換用の新トピック候補
    NEW_TOPIC_SUGGESTIONS = {
        "おせち": ["雑煮の具", "お屠蘇", "福袋", "初詣"],
        "お年玉": ["初詣", "おみくじ", "書き初め", "福袋"],
        "親戚": ["年賀状", "箱根駅伝", "福袋", "初売り"],
        "挨拶": ["初詣", "おみくじ", "初売り", "書き初め"],
        "初詣": ["おみくじ", "破魔矢", "甘酒", "おせち"],
        "福袋": ["初売り", "お年玉", "おみくじ", "書き初め"],
        "雑煮": ["お餅の形", "地域差", "おせち", "お屠蘇"],
        "お餅": ["餅つき", "雑煮", "きな粉餅", "磯辺焼き"],
        "餅つき": ["杵と臼", "お餅の形", "つきたて", "雑煮"],
        "default": ["初詣", "おみくじ", "雑煮の具", "福袋", "書き初め", "箱根駅伝"],
    }

    # Fatal判定用キーワード（MODIFYで即停止すべき重大な問題）
    FATAL_KEYWORDS = [
        "安全", "暴力", "差別", "性的", "個人情報",
        "意味不明", "破綻", "崩壊", "無限ループ",
    ]

    # Soft Fail降格用キーワード（MODIFYをRETRYに降格）
    SOFT_FAIL_KEYWORDS = [
        "浅い", "弱い", "テンプレ", "面白くない", "単調",
        "発展", "繰り返し", "オウム返し", "進行",
    ]

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

        # 設定整合性のチェック（姉妹が別居しているかのような表現）
        setting_check = self._check_setting_consistency(response)
        if not setting_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=setting_check["issue"],
                suggestion=setting_check["suggestion"],
            )

        # 褒め言葉チェック（あゆの発言のみ適用）
        praise_check = self._check_praise_words(response, speaker)
        if not praise_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=praise_check["issue"],
                suggestion=praise_check["suggestion"],
            )

        # 話題ループ検出（LLM評価の前に実行）
        loop_check = self._detect_topic_loop(conversation_history, response)
        if loop_check["detected"]:
            print(f"    🔄 話題ループ検出: 「{loop_check['keyword']}」が{loop_check['count']}回繰り返し")

            # 新しい話題の提案
            new_topic = self._get_new_topic_suggestion(loop_check["keyword"])

            return DirectorEvaluation(
                status=DirectorStatus.PASS,
                reason=f"話題ループ: 「{loop_check['keyword']}」が{loop_check['count']}回出現",
                action="INTERVENE",
                next_instruction=f"「{loop_check['keyword']}」の話題が続いています。「{new_topic}」など別の話題に展開してください。",
                next_pattern="D",  # 脱線→修正パターン
                beat_stage=current_beat,
                hook=loop_check["keyword"],
                evidence={"dialogue": f"「{loop_check['keyword']}」が{loop_check['count']}回出現", "frame": None},
            )

        # 動的ループ検出（静的検出で見つからない場合のフォールバック）
        dynamic_loop = self._detect_topic_loop_dynamic(conversation_history, response)
        if dynamic_loop["detected"]:
            print(f"    🔄 動的ループ検出: 「{dynamic_loop['keyword']}」が繰り返し出現")
            new_topic = self._get_new_topic_suggestion(dynamic_loop["keyword"])
            return DirectorEvaluation(
                status=DirectorStatus.PASS,
                reason=f"動的ループ: 「{dynamic_loop['keyword']}」が繰り返し",
                action="INTERVENE",
                next_instruction=f"「{dynamic_loop['keyword']}」の話題が続いています。別の視点や話題に展開してください。",
                next_pattern="D",
                beat_stage=current_beat,
                hook=dynamic_loop["keyword"],
                evidence={"dialogue": f"「{dynamic_loop['keyword']}」が繰り返し", "frame": None},
            )

        # 散漫検出（複数話題への全レス）
        scatter_check = self._is_scattered_response(response)
        if scatter_check["detected"]:
            issues_str = "、".join(scatter_check["issues"])
            print(f"    ⚠️ 散漫検出: {issues_str}")
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=f"応答が散漫: {issues_str}",
                suggestion="話題を1つに絞って深掘りしてください。「〜も」「あと」「それと」の連続は避けてください。",
            )

        # 論理的矛盾のチェック（二重否定など）
        logic_check = self._check_logical_consistency(response)
        if not logic_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=logic_check["issue"],
                suggestion=logic_check["suggestion"],
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
                data = json.loads(json_text)
            except json.JSONDecodeError:
                # パース失敗時は安全側に倒してPASS/NOOP
                return DirectorEvaluation(
                    status=DirectorStatus.PASS,
                    reason="JSON Parse Error - Safe Fallback",
                    next_instruction=None,
                    next_pattern=None,
                    beat_stage=current_beat,
                )

            # ★ コードによる「最後の殺し」実行
            validated_data = self._validate_director_output(data, turn_number, frame_description)

            # 判定結果の抽出
            status_str = validated_data.get("status", "PASS").upper()
            status = (
                DirectorStatus.PASS
                if status_str == "PASS"
                else DirectorStatus.RETRY
                if status_str == "RETRY"
                else DirectorStatus.MODIFY
            )

            # Build reason with issues if available
            reason = validated_data.get("reason", "")
            issues = validated_data.get("issues", [])
            if issues and isinstance(issues, list):
                reason_with_issues = f"{reason}\n- " + "\n- ".join(issues[:2])
            else:
                reason_with_issues = reason

            beat_stage = validated_data.get("beat_stage", current_beat)

            # action判定
            action = validated_data.get("action", "NOOP")
            if action == "NOOP":
                next_pattern = None
                next_instruction = None
            else:
                next_pattern = validated_data.get("next_pattern")
                next_instruction = validated_data.get("next_instruction")

                # パターンの整合性チェック
                if next_pattern and next_pattern not in ["A", "B", "C", "D", "E"]:
                    next_pattern = None

                # ビートトラッカーによるパターン許可チェック（既存ロジック維持）
                if next_pattern and not self.beat_tracker.is_pattern_allowed(next_pattern, self.recent_patterns):
                    next_pattern = self.beat_tracker.suggest_pattern(turn_number, self.recent_patterns)

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

            # 履歴更新（NOOPでない場合のみ）
            if next_pattern:
                self.recent_patterns.append(next_pattern)
                if len(self.recent_patterns) > 5:
                    self.recent_patterns = self.recent_patterns[-5:]

            return DirectorEvaluation(
                status=status,
                reason=reason_with_issues,
                suggestion=validated_data.get("suggestion"),
                next_pattern=next_pattern,
                next_instruction=next_instruction,
                beat_stage=beat_stage,
                action=validated_data.get("action", "NOOP"),
                hook=validated_data.get("hook"),
                evidence=validated_data.get("evidence"),
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

        # スピーカー混同防止用の強調ブロック
        speaker_name = "やな（姉）" if speaker == "A" else "あゆ（妹）"
        praise_note = "" if speaker == "A" else "\n║ ※褒め言葉禁止はこのあゆの発言に適用されます"

        prompt = f"""
╔════════════════════════════════════════════════════════════╗
║ 【評価対象の発言者】 {speaker}（{speaker_name}）
║ ※この発言者の発言のみを評価してください{praise_note}
║ ※やな(A)の感情表現（「楽しみだね」等）は自然なので問題なし
╚════════════════════════════════════════════════════════════╝

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

【評価の前提】
- status(PASS/RETRY/MODIFY) は「今の発言の品質」評価
- action(NOOP/INTERVENE) は「次ターンに介入する価値があるか」
- 基本は NOOP 推奨だが、**会話がループしている場合は積極的に介入せよ**

【評価基準】
1. Progress（進行度）← 最重要・厳格化
   - ❌ NG: 前のターンと同じ単語（おせち/親戚/お年玉）を繰り返すだけ
   - ❌ NG: 「楽しみだね」「そうだね」という同意のみで新情報なし
   - ❌ NG: オウム返し（相手の言葉をそのまま繰り返す）
   - ✓ OK: 新しいトピック（初詣/福袋/雑煮の具）が出ている
   - ✓ OK: 具体的なエピソードや理由が追加されている

2. Participation: 自然な掛け合いか（オウム返しは減点）

3. Knowledge Domain: 専門領域内か
   - {speaker}が話すべき領域：{domain_expectations}

4. Narration Quality: 新規性があり、会話が前進しているか
   - 抽象語の意味確認（例:「何が違うの？」）は原則減点
   - 感情/口調の演技指導は絶対に出さない

【介入ゲート（action判定）】
- 次の条件なら action=INTERVENE に切り替える
  (a) **話題ループ**: 同じ名詞（おせち/お年玉/親戚）が3回以上繰り返されている
  (b) **抽象的な同意のみ**: 「楽しみ」「大事」「いいね」の連鎖で新情報がない
  → 指示例: 「話題を変えて。『初詣』『福袋』『雑煮の具』など別の要素へ」

- 次の条件なら action=NOOP
  (c) 新しい情報やトピックが出続けている
  (d) 導入(ターン1-2)で大きな逸脱がない
  (e) hookが抽象語のみ、または根拠(evidence)がない

【応答フォーマット】
JSON ONLY:
{{
  "status": "PASS" | "RETRY" | "MODIFY",
  "reason": "評価理由（30字以内）",
  "issues": ["問題点があれば記述"],
  "suggestion": "修正案（RETRY/MODIFY時のみ）",
  "beat_stage": "{current_beat}",
  "action": "NOOP" | "INTERVENE",
  "hook": "具体名詞を含む短い句 or null",
  "evidence": {{ "dialogue": "抜粋 or null", "frame": "抜粋 or null" }},
  "next_pattern": "A" | "B" | "C" | "D" | "E" | null,
  "next_instruction": "INTERVENEの場合のみ。NOOPならnull"
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
                temperature=0.7,  # Increased to reduce repetition
                max_tokens=100,   # Reduced to prevent long repetitive output
            )
            result = instruction.strip()

            # 繰り返し検出: 同じ文字が連続で5回以上出現する場合は無効
            if self._has_repetition(result):
                print("    ⚠️ 繰り返し検出: 指示を破棄")
                return ""

            return result
        except Exception:
            return ""  # Empty instruction on error

    def _has_repetition(self, text: str, threshold: int = 5) -> bool:
        """
        テキストに異常な繰り返しがあるかチェック。

        Args:
            text: チェック対象のテキスト
            threshold: 繰り返しと判定する回数

        Returns:
            繰り返しがある場合True
        """
        if not text:
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

        # 同じ2文字パターンがthreshold回以上連続
        for i in range(len(text) - 2 * threshold):
            pattern = text[i:i+2]
            if len(pattern) == 2 and pattern[0] != pattern[1]:
                repeated = pattern * threshold
                if repeated in text:
                    return True

        # 同じ単語が短い間隔で繰り返される（例: "鳥鳥鳥"）
        import re
        # 2-4文字の単語が4回以上連続
        if re.search(r'(.{2,4})\1{3,}', text):
            return True

        return False

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
            # 「ございます」は禁止なので含めない
            # 「ます」系も追加（例: 「来ました」「思います」など）
            markers = ["です", "ですよ", "ですね", "でしょう", "ます", "ました", "ません"]
            expected_desc = ["です", "ですね", "ですよ", "〜ます"]

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

        # 特別なケース: あゆは「です」系または「ます」系のいずれかが必須
        if speaker == "B":
            polite_variants = ["です", "ます", "ました", "ません"]
            has_polite = any(m in response for m in polite_variants)
            passed = passed and has_polite

        return {
            "passed": passed,
            "expected": expected_desc,
            "found": found,
            "missing": "マーカーが見つかりません" if not found else "",
        }

    def _check_setting_consistency(self, response: str) -> dict:
        """
        設定の整合性をチェックする（姉妹が別居しているかのような表現を検出）。

        Args:
            response: 評価対象の発言

        Returns:
            {
                "passed": bool,
                "issue": str,
                "suggestion": str
            }
        """
        for word in self.SEPARATION_WORDS:
            if word in response:
                return {
                    "passed": False,
                    "issue": f"設定破壊: 「{word}」は姉妹が別居しているかのような表現です",
                    "suggestion": "やなとあゆは同じ家に住んでいます。「うちに」「私たちの家」等を使ってください。",
                }

        return {
            "passed": True,
            "issue": "",
            "suggestion": "",
        }

    def _check_praise_words(self, response: str, speaker: str) -> dict:
        """
        褒め言葉チェック（あゆの発言のみ適用）。

        Args:
            response: 評価対象の発言
            speaker: "A" or "B"

        Returns:
            {
                "passed": bool,
                "issue": str,
                "suggestion": str
            }
        """
        # やな（A）の発言には適用しない
        if speaker == "A":
            return {"passed": True, "issue": "", "suggestion": ""}

        # あゆ（B）の発言のみチェック
        for word in self.PRAISE_WORDS_FOR_AYU:
            if word in response:
                return {
                    "passed": False,
                    "issue": f"あゆの褒め言葉使用: 「{word}」",
                    "suggestion": "評価・判定型の表現を避け、情報提供に徹してください",
                }
        return {"passed": True, "issue": "", "suggestion": ""}

    def _check_logical_consistency(self, response: str) -> dict:
        """
        論理的な矛盾や不自然な表現をチェックする。

        Args:
            response: 評価対象の発言

        Returns:
            {
                "passed": bool,
                "issue": str,
                "suggestion": str
            }
        """
        import re

        # 二重否定パターン（意味が逆になる）
        double_negative_patterns = [
            (r"まだ.{1,10}じゃない", "「まだ〇〇じゃない」は意味が逆になります"),
            (r"まだ.{1,10}ではない", "「まだ〇〇ではない」は意味が逆になります"),
            (r"もう.{1,10}じゃない", "「もう〇〇じゃない」は意味が曖昧です"),
        ]

        for pattern, message in double_negative_patterns:
            if re.search(pattern, response):
                match = re.search(pattern, response)
                return {
                    "passed": False,
                    "issue": f"論理矛盾: {message}（検出: 「{match.group()}」）",
                    "suggestion": "肯定形で言い換えてください。例: 「まだ未成年だよ」",
                }

        # 矛盾しやすい表現パターン
        contradictory_patterns = [
            (r"私.{0,5}未成年じゃない", "「私、未成年じゃない」は「私は成人だ」という意味になります"),
        ]

        for pattern, message in contradictory_patterns:
            if re.search(pattern, response):
                return {
                    "passed": False,
                    "issue": f"論理矛盾: {message}",
                    "suggestion": "意図した意味になっているか確認してください",
                }

        return {
            "passed": True,
            "issue": "",
            "suggestion": "",
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

    def _is_vague_hook(self, hook: str) -> bool:
        """
        曖昧語フックかどうか判定。
        曖昧語が含まれていても、具体名詞があればOK。
        """
        h = (hook or "").strip()
        if not h:
            return False

        has_vague = any(w in h for w in self.VAGUE_WORDS)
        has_specific = any(x in h for x in self.SPECIFIC_HINTS)

        # 曖昧語があり、具体名詞がなく、短い場合は曖昧フック
        return has_vague and not has_specific and len(h) <= 12

    def _is_off_topic_hook(self, hook: str, frame_description: str) -> bool:
        """
        hookがトピックと無関係かチェック。
        観光地名がトピックに含まれていなければ無関係と判定。
        """
        if not hook:
            return False

        for spot in self.TOURIST_SPOTS:
            if spot in hook and spot not in frame_description:
                return True
        return False

    def _detect_topic_loop(self, conversation_history: list, response: str) -> dict:
        """
        話題ループを検出する。

        Args:
            conversation_history: [(speaker, text), ...] のリスト
            response: 現在の発言

        Returns:
            {
                "detected": bool,
                "keyword": str or None,
                "count": int
            }
        """
        if not conversation_history or len(conversation_history) < 2:
            return {"detected": False, "keyword": None, "count": 0}

        # 直近の会話 + 現在の発言を結合
        recent_texts = [text for _, text in conversation_history[-4:]]
        recent_texts.append(response)
        combined_text = " ".join(recent_texts)

        # 頻出キーワードを検出
        for kw in self.LOOP_KEYWORDS:
            count = combined_text.count(kw)
            if count >= self.LOOP_THRESHOLD:
                return {"detected": True, "keyword": kw, "count": count}

        return {"detected": False, "keyword": None, "count": 0}

    def _get_new_topic_suggestion(self, loop_keyword: str) -> str:
        """
        ループしているキーワードに応じた新しい話題を提案する。

        Args:
            loop_keyword: ループしているキーワード

        Returns:
            新しい話題の提案
        """
        suggestions = self.NEW_TOPIC_SUGGESTIONS.get(
            loop_keyword, self.NEW_TOPIC_SUGGESTIONS["default"]
        )
        # ループしているキーワードを除外
        available = [t for t in suggestions if t != loop_keyword]
        return available[0] if available else "別の話題"

    def _detect_topic_loop_dynamic(self, conversation_history: list, response: str) -> dict:
        """
        動的に話題ループを検出（MeCab不要）。
        漢字・カタカナ・英数字の2文字以上の連続を「トピック候補」とみなす。

        Args:
            conversation_history: [(speaker, text), ...] のリスト
            response: 現在の発言

        Returns:
            {
                "detected": bool,
                "keyword": str or None
            }
        """
        if len(conversation_history) < 3:
            return {"detected": False, "keyword": None}

        # 正規表現で「意味がありそうな単語」を抽出
        # 漢字・カタカナ・英数字の2文字以上の連続
        pattern = r'[一-龠々ヶァ-ヴーa-zA-Z0-9]{2,}'

        # 直近3ターン + 現在の発言からそれぞれ単語セットを作成
        texts = [text for _, text in conversation_history[-3:]] + [response]
        word_sets = [set(re.findall(pattern, text)) for text in texts]

        # 全てに共通する単語を検出
        if not word_sets:
            return {"detected": False, "keyword": None}

        common_words = word_sets[0]
        for s in word_sets[1:]:
            common_words = common_words.intersection(s)

        # 固定リストに含まれる単語は既存のループ検出に任せる
        common_words = common_words - set(self.LOOP_KEYWORDS)

        # 短すぎる単語（2文字）や一般的すぎる単語を除外
        common_words = {w for w in common_words if len(w) >= 3}

        if common_words:
            # 最も長い単語を代表として返す（"QR"より"QRコード"を優先）
            topic = max(common_words, key=len)
            return {"detected": True, "keyword": topic}

        return {"detected": False, "keyword": None}

    def _is_scattered_response(self, response: str) -> dict:
        """
        散漫な応答（話題盛りすぎ）を検出する。

        Args:
            response: 評価対象の発言

        Returns:
            {
                "detected": bool,
                "issues": list[str]
            }
        """
        issues = []

        # 読点が多すぎる（4個以上で散漫と判定）
        comma_count = response.count("、")
        if comma_count >= 4:
            issues.append(f"読点が多すぎる({comma_count}個)")

        # 列挙表現が多い（「〜も」「あと」「それと」等の連続）
        scatter_patterns = [
            (r'も[、。！？]', "「〜も」"),
            (r'あと[、]', "「あと」"),
            (r'それと', "「それと」"),
            (r'さらに', "「さらに」"),
            (r'それから', "「それから」"),
        ]
        scatter_count = 0
        for pattern, _ in scatter_patterns:
            scatter_count += len(re.findall(pattern, response))

        if scatter_count >= 2:
            issues.append(f"列挙表現が多い({scatter_count}回)")

        # 文の数が多すぎる（3文以上で散漫と判定）
        sentence_count = len(re.findall(r'[。！？]', response))
        if sentence_count >= 3:
            issues.append(f"文が多すぎる({sentence_count}文)")

        if issues:
            return {"detected": True, "issues": issues}
        return {"detected": False, "issues": []}

    def is_fatal_modify(self, reason: str) -> bool:
        """
        MODIFYが致命的かどうか判定する。

        Args:
            reason: MODIFYの理由

        Returns:
            致命的な場合True（会話を停止すべき）
        """
        if not reason:
            return False
        return any(kw in reason for kw in self.FATAL_KEYWORDS)

    def _validate_director_output(self, data: dict, turn_number: int, frame_description: str = "") -> dict:
        """
        LLMの出力を検証し、誤爆条件にマッチしたら強制的にNOOPに書き換える。
        「コード側の最後の殺し」
        また、スキーマを守れない出力も補正する。
        さらに、Soft FailのMODIFYはRETRYに降格する。
        """
        # === Soft Fail降格処理（MODIFYをRETRYに） ===
        if data.get("status") == "MODIFY":
            reason = data.get("reason", "")
            # 致命的でないMODIFYはRETRYに降格
            if not self.is_fatal_modify(reason):
                # Soft Fail キーワードがあるか、または致命的キーワードがない場合は降格
                is_soft_fail = any(kw in reason for kw in self.SOFT_FAIL_KEYWORDS)
                if is_soft_fail or not self.is_fatal_modify(reason):
                    print(f"    ⚠️ Soft Fail検出: MODIFY→RETRYに降格 ({reason})")
                    data["status"] = "RETRY"

        # === スキーマ補正（後方互換性） ===
        if "action" not in data:
            data["action"] = "NOOP"
        if "evidence" not in data:
            data["evidence"] = {"dialogue": None, "frame": None}
        if data.get("next_instruction") == "":
            data["next_instruction"] = None
        if data.get("next_pattern") not in [None, "A", "B", "C", "D", "E"]:
            data["next_pattern"] = None
        if data.get("hook") == "":
            data["hook"] = None

        # === 強制NOOP判定 ===
        force_noop = False
        reason_override = ""

        action = data.get("action", "NOOP")
        hook = data.get("hook") or ""
        instruction = data.get("next_instruction") or ""
        evidence = data.get("evidence") or {}
        status = data.get("status", "PASS")

        has_dialogue_ev = bool(evidence.get("dialogue"))
        has_frame_ev = bool(evidence.get("frame"))
        has_any_evidence = has_dialogue_ev or has_frame_ev

        # (a) 導入フェーズの保護（ターン1-2で軽微な場合はNOOP）
        if turn_number <= 2 and action == "INTERVENE":
            # 重大な逸脱（RETRY/MODIFY）でなければ抑制
            is_major_issue = status in ["RETRY", "MODIFY"]
            if not is_major_issue:
                force_noop = True
                reason_override = "導入フェーズのため介入抑制"

        # (b) 曖昧語フックの検出
        if self._is_vague_hook(hook):
            force_noop = True
            reason_override = f"曖昧語フック検出: {hook}"

        # (c) 絶対禁止ワードの検出（演技指導）
        if instruction and any(w in instruction for w in self.HARD_BANNED_WORDS):
            force_noop = True
            reason_override = "演技指導ワード検出（絶対禁止）"

        # (d) 要注意ワードの検出（根拠なしならNOOP）
        if instruction and any(w in instruction for w in self.SOFT_BANNED_WORDS):
            if not has_any_evidence:
                force_noop = True
                reason_override = "演技指導ワード検出（根拠なし）"

        # (e) 根拠欠落（INTERVENEなのに根拠なし）
        if action == "INTERVENE" and not has_any_evidence:
            force_noop = True
            reason_override = "介入根拠なし"

        # (f) トピック無関係チェック（観光地名がトピックに含まれていない）
        if action == "INTERVENE" and self._is_off_topic_hook(hook, frame_description):
            force_noop = True
            reason_override = f"トピック無関係なフック: {hook}"

        # === 強制NOOP実行 ===
        if force_noop:
            print(f"    🛡️ Director Code Guard: Forcing NOOP ({reason_override})")
            data["action"] = "NOOP"
            data["next_instruction"] = None
            data["next_pattern"] = None
            data["hook"] = None

        # === NOOP時のクリーンアップ ===
        if data.get("action") == "NOOP":
            data["next_instruction"] = None
            data["next_pattern"] = None

        return data
