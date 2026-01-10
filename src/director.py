"""
Director LLM that orchestrates character dialogue.
Monitors: 進行度 (progress), 参加度 (participation), 知識領域 (knowledge domain)
Now includes fact-checking capability via web search.
"""

import re
from typing import Optional

from src.llm_client import get_llm_client
from src.config import config
from src.types import DirectorEvaluation, DirectorStatus, TopicState
from src.prompt_manager import get_prompt_manager
from src.beat_tracker import get_beat_tracker
from src.fact_checker import get_fact_checker, FactCheckResult
from src.novelty_guard import NoveltyGuard, LoopCheckResult


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
        # Director v3: Topic Manager
        self.topic_state = TopicState()
        # 前回処理したフレーム番号（フレーム変更検出用）
        self.last_frame_num: int = -1
        # Director v3: NoveltyGuard for loop detection
        self.novelty_guard = NoveltyGuard(max_topic_depth=3)

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
        frame_num: int = 1,
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
        # フレームが変わったらTopic Stateをリセット
        if frame_num != self.last_frame_num:
            self.reset_topic_state()
            self.novelty_guard.reset()  # NoveltyGuardもリセット
            self.last_frame_num = frame_num
            print(f"    🔄 Frame changed to {frame_num}, topic state reset")

        # ========== Step 0: NoveltyGuard Loop Detection ==========
        # 最初は update=False でチェックのみ行い、リトライ時は状態を壊さないようにする
        novelty_result = self.novelty_guard.check_and_update(response, update=False)
        if novelty_result.loop_detected:
            print(f"    🔁 NoveltyGuard: ループ検知 stuck_nouns={novelty_result.stuck_nouns}")
            print(f"       戦略: {novelty_result.strategy.value}")
            # ループ検知時は早期リターンでINTERVENE
            return DirectorEvaluation(
                status=DirectorStatus.PASS,
                reason=f"NoveltyGuard: 話題「{'、'.join(novelty_result.stuck_nouns[:3])}」がループ中",
                action="INTERVENE",
                next_instruction=novelty_result.injection,
                next_pattern="D",  # 脱線→修正パターン
                beat_stage=self.beat_tracker.get_current_beat(turn_number),
                hook="、".join(novelty_result.stuck_nouns[:2]) if novelty_result.stuck_nouns else None,
                evidence={"dialogue": f"同一名詞が{novelty_result.topic_depth}ターン連続", "frame": None},
                novelty_info={
                    "loop_detected": True,
                    "stuck_nouns": novelty_result.stuck_nouns,
                    "strategy": novelty_result.strategy.value,
                    "topic_depth": novelty_result.topic_depth,
                },
            )

        # Get current beat stage from turn number
        current_beat = self.beat_tracker.get_current_beat(turn_number)
        beat_info = self.beat_tracker.get_beat_info(current_beat)

        # ========== Director v3: Topic Manager - 判定準備 ==========
        detected_hook = self._extract_hook_from_response(response, frame_description)
        is_premature_switch = False  # 早すぎる話題転換フラグ

        if not self.topic_state.focus_hook:
            print(f"    📊 Topic init (check): {detected_hook}")

        # 現在のtopic状態を一時的に取得（RETRYでなければ後で正式に更新）
        # ※ 注意: self.topic_state 自体を更新してしまっているので、RETRY時は巻き戻す必要がある。
        # または、最初から更新せずに新しい状態を計算する。
        
        # 簡易的な巻き戻しのために以前の状態を保持
        import copy
        old_topic_state = copy.deepcopy(self.topic_state)
        
        # 判定用の仮更新（既存ロジックを流用）
        temp_is_premature = False
        if self.topic_state.focus_hook:
            is_same_topic = (
                detected_hook == self.topic_state.focus_hook or
                detected_hook in self.topic_state.focus_hook or
                self.topic_state.focus_hook in detected_hook
            )
            if is_same_topic:
                self.topic_state.advance_depth()
            else:
                if not self.topic_state.can_switch_topic():
                    temp_is_premature = True
                    is_premature_switch = True
                else:
                    self.topic_state.switch_topic(detected_hook)
        else:
            self.topic_state.focus_hook = detected_hook
            self.topic_state.must_include = [detected_hook]

        # 現在のtopic状態をキャプチャ（早期リターンでも使用）
        current_topic_fields = {
            "focus_hook": self.topic_state.focus_hook,
            "hook_depth": self.topic_state.hook_depth,
            "depth_step": self.topic_state.depth_step,
            "forbidden_topics": self.topic_state.forbidden_topics.copy(),
            "must_include": self.topic_state.must_include.copy(),
            "character_role": self._get_character_role(speaker, self.topic_state.depth_step),
        }

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
        # 出力形式のチェック
        format_check = self._check_format(response)
        if not format_check["passed"]:
            # RETRY時はトピック状態を巻き戻す
            self.topic_state = old_topic_state
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=f"出力形式の問題: {format_check['issue']}",
                suggestion=format_check["suggestion"],
                **current_topic_fields,
            )
        
        # WARN収集用リスト
        static_warnings = []
        
        # Format WARN (lines >= 6) cannot easily be retrieved from _check_format unless we modify it to return issue even on pass,
        # but _check_format currently prints and returns passed=True.
        # We can re-check length here or trust _check_format logic.
        # Since I modified _check_format to print warning but return passed=True, I'll stick to that
        # OR I can re-check line count to append to static_warnings.
        lines = [line.strip() for line in response.split("\n") if line.strip()]
        if 6 <= len(lines) < 8:
            static_warnings.append(f"format: 発言が長すぎます（{len(lines)}行）。5行以内にしてください。")

        # 設定整合性のチェック（姉妹が別居しているかのような表現）
        setting_check = self._check_setting_consistency(response)
        if not setting_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=setting_check["issue"],
                suggestion=setting_check["suggestion"],
                **current_topic_fields,
            )

        # 褒め言葉チェック（あゆの発言のみ適用）
        praise_check = self._check_praise_words(response, speaker)
        if not praise_check["passed"]:
            # RETRY時はトピック状態を巻き戻す
            self.topic_state = old_topic_state
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=praise_check["issue"],
                suggestion=praise_check["suggestion"],
                **current_topic_fields,
            )
        elif praise_check.get("issue", "").startswith("WARN:"):
             # WARN
             static_warnings.append(praise_check["issue"])

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
                **current_topic_fields,
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
                **current_topic_fields,
            )

        # 散漫検出（複数話題への全レス）
        scatter_check = self._is_scattered_response(response)
        if scatter_check["detected"]:
            # level check
            level = scatter_check.get("level", "WARN")
            issues_str = "、".join(scatter_check["issues"])
            
            if level == "RETRY":
                self.topic_state = old_topic_state
                return DirectorEvaluation(
                    status=DirectorStatus.RETRY,
                    reason=f"応答が散漫(RETRY): {issues_str}",
                    suggestion="【制限】50〜80文字、2文以内、読点2個以内で応答してください。",
                    **current_topic_fields,
                )
            else:
                 print(f"    ⚠️ 散漫検出(WARN): {issues_str}")
                 static_warnings.append(f"scatter: {issues_str}。話題を絞ってください。")

        # 論理的矛盾のチェック（二重否定など）
        logic_check = self._check_logical_consistency(response)
        if not logic_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=logic_check["issue"],
                suggestion=logic_check["suggestion"],
                **current_topic_fields,
            )

        # 口調マーカーの事前チェック
        tone_check = self._check_tone_markers(speaker, response)
        if not tone_check["passed"]:
            # RETRY時はトピック状態を巻き戻す
            self.topic_state = old_topic_state
            # 口調マーカーが欠けている場合はRETRYを推奨
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=f"口調マーカー不足: {tone_check['missing']}",
                suggestion=f"以下のマーカーを含めてください: {', '.join(tone_check['expected'])}",
                **current_topic_fields,
            )
        elif tone_check.get("missing", "").startswith("WARN:"):
             # WARN (Score 1)
             static_warnings.append(tone_check["missing"])

        # 口調マーカーの詳細情報を取得（LLM評価用）
        tone_info = tone_check

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
                static_warnings.append(f"fact_error: {fact_check_result.claim} は間違いの可能性があります。")

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
            static_warnings=static_warnings,
        )

        try:
            result_text = self.llm.call(
                system=self.system_prompt,
                user=user_prompt,
                temperature=0.3,  # Lower temperature for consistency
                max_tokens=300,  # Increased for detailed evaluation
            )

            # Parse JSON response (robust extraction)
            import json
            import re

            json_text = result_text.strip()
            data = None

            # Robust JSON extraction
            code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", json_text)
            if code_block_match:
                try: data = json.loads(code_block_match.group(1).strip())
                except json.JSONDecodeError: pass
            
            if data is None:
                json_match = re.search(r"\{[\s\S]*\}", json_text)
                if json_match:
                    try: data = json.loads(json_match.group(0))
                    except json.JSONDecodeError: pass

            if data is None:
                 try: data = json.loads(json_text)
                 except json.JSONDecodeError: pass

            if data is None:
                # パース失敗時は安全側に倒してPASS/NOOP
                # パース失敗はLLMの出力異常なのでRETRY扱いにはせずPASSさせるが、トピックは更新しない
                self.topic_state = old_topic_state
                return DirectorEvaluation(
                    status=DirectorStatus.PASS,
                    reason="JSON Parse Error - Safe Fallback",
                    next_instruction=None,
                    next_pattern=None,
                    beat_stage=current_beat,
                    **current_topic_fields,
                )

            # ★ コードによる「最後の殺し」実行
            validated_data = self._validate_director_output(data, turn_number, frame_description)

            # ★ Scoring System Logic
            scores = data.get("scores", {})
            score_values = []
            for k in ["frame_consistency", "roleplay", "connection", "information_density", "naturalness"]:
                val = scores.get(k)
                if isinstance(val, (int, float)):
                    score_values.append(val)
            
            avg_score = sum(score_values) / len(score_values) if score_values else 0
            
            # Determine Status from Score
            if avg_score > 0: # If scores are missing, rely on 'status' field or fallback
                if avg_score < 3.5:
                    status = DirectorStatus.RETRY
                else:
                    status = DirectorStatus.PASS
                    # 3.5 <= avg < 4.0 is WARN (Pass with issues)
            else:
                # Fallback to status field if no scores
                status_str = data.get("status", "PASS").upper()
                status = DirectorStatus.RETRY if status_str == "RETRY" else DirectorStatus.PASS
                avg_score = 0.0

            # Handle RETRY
            if status == DirectorStatus.RETRY:
                self.topic_state = old_topic_state
                print(f"    🛡️ Director: RETRY (Score={avg_score:.1f})")
                
                # Check if we should override reason/suggestion from LLM
                reason = data.get("reason", f"Score low ({avg_score:.1f})")
                suggestion = data.get("suggestion", "全体的に見直してください")
                
                return DirectorEvaluation(
                    status=DirectorStatus.RETRY,
                    reason=reason,
                    suggestion=suggestion,
                    **current_topic_fields,
                )

            # Handle PASS (including WARN cases)
            self.novelty_guard.check_and_update(response, update=True)
            
            # Warn handling for Next Instruction
            next_instruction = data.get("next_instruction")
            
            # If WARN (Avg < 4.0 OR static_warnings exist), inject warnings into next_instruction
            is_warn_score = 0 < avg_score < 4.0
            llm_issues = data.get("issues", [])
            
            warning_messages = []
            if static_warnings:
                warning_messages.extend([f"[Warn: {w}]" for w in static_warnings])
            if is_warn_score:
                warning_messages.append(f"[Score: {avg_score:.1f} (Low)]")
            if llm_issues:
                 warning_messages.extend([f"[Issue: {i}]" for i in llm_issues])

            if warning_messages:
                # Append warnings to next instruction to guide correction
                warn_text = " ".join(warning_messages)
                print(f"    ⚠️ PASS with Warnings: {warn_text}")
                
                prefix = f"（前の発言に{len(warning_messages)}件の改善点あり: {warn_text}）"
                if next_instruction:
                    next_instruction = f"{prefix} {next_instruction}"
                else:
                    # action=NOOP but we want to pass context. 
                    next_instruction = prefix 

            # Topic Logging
            if temp_is_premature:
                print(f"    ⚠️ Topic premature switch detected (PASS): {old_topic_state.focus_hook} → {detected_hook}")
            elif detected_hook == old_topic_state.focus_hook:
                 print(f"    📊 Topic: {self.topic_state.focus_hook} depth={self.topic_state.hook_depth}/3 step={self.topic_state.depth_step}")
            else:
                 print(f"    🔀 Topic switch: → {detected_hook}")

            # action判定
            action = data.get("action", "NOOP")
            next_pattern = data.get("next_pattern")
            
            if action == "NOOP":
                next_pattern = None
                # If we have next_instruction from warnings, we should keep it?
                # Usually NOOP implies next_instruction is None.
                # But if we have warnings, passing them to next_instruction is useful.
                # BUT, get_instruction_for_next_turn will generate the instruction for the next turn independently?
                # No, DirectorEvaluation.next_instruction is used for INTERVENE.
                # If action=NOOP, DirectorEvaluation.next_instruction is typically ignored by the main loop (main.py or beat_manager).
                # Wait, if action is NOOP, we should verify if next_instruction is used.
                # If not used, we might lose the warning.
                # So if warnings exist, maybe we should force INTERVENE?
                if warning_messages:
                     action = "INTERVENE"
                     print("    ⚠️ Upgrading to INTERVENE to convey warnings.")
                else:
                     next_instruction = None

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

            # Build reason with issues if available
            reason = validated_data.get("reason", "")
            issues = validated_data.get("issues", [])
            if issues and isinstance(issues, list):
                reason_with_issues = f"{reason}\n- " + "\n- ".join(issues[:2])
            else:
                reason_with_issues = reason
            
            beat_stage = validated_data.get("beat_stage", current_beat)

            # ========== Director v3: 早すぎる話題転換のINTERVENE処理 ==========
            # 早期に検出したpremature switchフラグがある場合、INTERVENEで戻す
            if is_premature_switch:
                return DirectorEvaluation(
                    status=DirectorStatus.PASS,
                    reason=f"話題が早すぎる転換（{self.topic_state.focus_hook}→{detected_hook}）",
                    action="INTERVENE",
                    next_instruction=self._build_strong_intervention(speaker),
                    beat_stage=beat_stage,
                    **current_topic_fields,
                )

            return DirectorEvaluation(
                status=status,
                reason=reason_with_issues,
                suggestion=validated_data.get("suggestion"),
                next_pattern=next_pattern,
                next_instruction=next_instruction,
                beat_stage=beat_stage,
                action=action,
                hook=validated_data.get("hook"),
                evidence=validated_data.get("evidence"),
                **current_topic_fields,
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
                **current_topic_fields,
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
        static_warnings: list = None,
    ) -> str:
        """Build comprehensive evaluation prompt checking all 5 criteria with beat orchestration"""
        char_desc = "Elder Sister (やな) - action-driven, quick-witted" if speaker == "A" else "Younger Sister (あゆ) - logical, reflective, formal"
        domains_str = ", ".join(domains or [])
        static_warnings = static_warnings or []

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

        # Static Check Warnings Section
        warning_section = ""
        if static_warnings:
             warning_list_str = "\n".join([f"- {w}" for w in static_warnings])
             warning_section = f"""
【Static Analysis Warnings】
The system has detected the following minor issues. Please consider them in your instruction if status is PASS/WARN.
{warning_list_str}
"""

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
            tone_status = "\n【口調マーカー検証結果】✗ 未検出または弱信号 → 口調に注意が必要"

        prompt += f"""
{tone_status}
{warning_section}

【評価の前提】
- status(PASS/RETRY) は「今の発言の品質」評価
- action(NOOP/INTERVENE) は「次ターンに介入する価値があるか」
- 基本は NOOP 推奨だが、**会話がループしている場合は積極的に介入せよ**

【Scoring Criteria (1-5)】
1. Frame Consistency: その場の状況（景色や場所）に合った内容か
2. Roleplay: 姉妹の関係性、性格が守られているか
3. Connection: 直前の相手の発言を無視していないか
4. Density: 内容が薄すぎないか、または詰め込みすぎていないか
5. Naturalness: 機械的な繰り返しや、唐突な表現がないか

【判定基準 (Avg Score)】
- Avg < 3.5 -> RETRY
- 3.5 <= Avg < 4.0 -> WARN (Status=PASS but issues noted)
- Avg >= 4.0 -> PASS

【応答フォーマット】
JSON ONLY:
{{
  "scores": {{
    "frame_consistency": int,
    "roleplay": int,
    "connection": int,
    "information_density": int,
    "naturalness": int
  }},
  "status": "PASS" | "RETRY", 
  "reason": "評価理由（30字以内）",
  "issues": ["問題点があれば記述"],
  "suggestion": "修正案（RETRY時のみ）",
  "beat_stage": "{current_beat}",
  "action": "NOOP" | "INTERVENE",
  "hook": "具体名詞を含む短い句 or null",
  "evidence": {{ "dialogue": "抜粋 or null", "frame": "抜粋 or null" }},
  "next_pattern": "A" | "B" | "C" | "D" | "E" | null,
  "next_instruction": "INTERVENEの場合、またはStatic Warningsがある場合は必ず修正指示を記述"
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
        口調マーカーの多信号判定を行う。
        Score 0 -> RETRY
        Score 1 -> WARN (passed=True, but missing info)
        Score 2+ -> PASS

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
        # 正規化（引用部分などを除外して判定）
        normalized = self._normalize_text(response)
        
        # 定義：マーカーリスト
        # 語尾マーカー
        MARKERS_YANA = ["ね", "わ", "へ？", "かな", "かも"] # 調整：spec通り
        MARKERS_AYU = ["です", "ます", "でしょう", "ですね", "ました"]

        # 語彙マーカー
        VOCAB_YANA = ["やだ", "ほんと", "えー", "うーん", "すっごい", "そっか", "だね"] # spec + alpha
        VOCAB_AYU = ["つまり", "要するに", "一般的に", "目安", "推奨", "ですよ", "ません"]

        if speaker == "A":
            target_markers = MARKERS_YANA
            target_vocab = VOCAB_YANA
            expected_desc = ["〜ね", "わ！", "〜かな", "〜かも"]
        else:
            target_markers = MARKERS_AYU
            target_vocab = VOCAB_AYU
            expected_desc = ["です", "ます", "でしょう", "ですね"]

        marker_hit = 0
        found_markers = []
        for m in target_markers:
            if m in normalized:
                marker_hit = 1
                found_markers.append(m)
                break # 1つあれば1点
        
        vocab_hit = 0
        for v in target_vocab:
            if v in normalized:
                vocab_hit = 1
                found_markers.append(v)
                break

        style_hit = 0
        if speaker == "A":
            # やな: 2文以下かつ感嘆符（！または？）を含む
            # 文数カウント（簡易）
            sentence_count = normalized.count("。") + normalized.count("！") + normalized.count("？")
            # 句点なしで終わる場合も考慮（正規化後なので文末記号がない場合もあるが）
            if sentence_count == 0 and len(normalized) > 0:
                sentence_count = 1
            
            has_exclamation = "！" in normalized or "？" in normalized
            if sentence_count <= 2 and has_exclamation:
                style_hit = 1
                found_markers.append("【文体:短文+感嘆】")
        else:
            # あゆ: 文末に丁寧語が2回以上出現
            # 文末判定は難しいので、単純に丁寧語の出現回数で近似するか、文末分割してチェック
            # spec: "文末に丁寧語（です/ます/でした/ました）が2回以上出現"
            # ここではシンプルに丁寧語カウント >= 2 で判定（文末でなくても丁寧ならOKとする緩和）
            polite_count = 0
            for p in ["です", "ます", "でした", "ました"]:
                polite_count += normalized.count(p)
            
            if polite_count >= 2:
                style_hit = 1
                found_markers.append("【文体:丁寧語多用】")

        tone_score = marker_hit + vocab_hit + style_hit
        
        # 判定
        passed = True
        missing_msg = ""
        
        if tone_score == 0:
            passed = False
            missing_msg = "口調スコア0: 語尾・語彙・文体のいずれもキャラクターらしくありません"
        elif tone_score == 1:
            # WARN扱い -> PASSだが警告メッセージを残す（呼び出し元で処理）
            passed = True 
            missing_msg = "WARN: 口調スコア1（弱）: もう少しキャラクターらしさを強調してください"
        
        # 特別な禁止ワードチェック（やなの姉様呼び）は維持
        if speaker == "A" and "姉様" in response:
             return {
                "passed": False,
                "expected": expected_desc,
                "found": found_markers,
                "missing": "禁止ワード「姉様」を使用（やなは姉なので「姉様」は使えません）",
            }

        return {
            "passed": passed,
            "expected": expected_desc,
            "found": found_markers,
            "missing": missing_msg,
            "score": tone_score 
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
        評価語 + 相手への肯定 = RETRY
        評価語のみ = WARN

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

        # 正規化済みテキストで判定することを推奨するが、
        # 褒め言葉は意味レベルなので原文でも良い。
        # ただしspecに従い "「すごいね」は...除外" なので正規化を使う。
        normalized = self._normalize_text(response)

        # 評価語リスト
        praise_words = ["すごい", "素晴らしい", "正解", "完璧", "天才", "素敵", "見事"]
        
        # 相手への肯定パターン (例: "あなたの考えは正しい")
        # 厳密な正規表現は複雑だが、簡易的に「あなた」「君」「ユーザー」などの後に「正しい」「合ってる」等が来るかを見る
        user_affirmation_pattern = r"(あなた|君|ユーザー|その(答え|考え|意見)).*(正しい|合って|良い|素敵|見事)"

        import re
        has_praise = False
        found_word = ""
        for word in praise_words:
            if word in normalized:
                has_praise = True
                found_word = word
                break
        
        has_affirmation = bool(re.search(user_affirmation_pattern, normalized))

        if has_praise and has_affirmation:
            # RETRY
            return {
                "passed": False,
                "issue": f"あゆの褒め言葉（評価＋肯定）: 「{found_word}」＋相手肯定",
                "suggestion": "評価・判定を行わず、事実やデータのみを提供してください。",
            }
        elif has_praise:
            # WARN (PASSだが警告)
            return {
                "passed": True, # WARN扱い
                "issue": f"WARN: あゆの褒め言葉使用（弱）: 「{found_word}」",
                "suggestion": "なるべく評価的な言葉は避けてください。",
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
        # 「」で始まる発言のチェック（緩和案：警告にとどめ、RETRYにはしない）
        stripped = response.strip()
        if stripped.startswith("「") or stripped.startswith("『"):
            # 台本形式だが、一応PASSさせる（指示で修正を促す）
            print(f"    ⚠️ Format: 台本形式を検出しましたが、続行します。")
            # return {
            #     "passed": False,
            #     "issue": "発言が「」で囲まれています（台本形式）",
            #     "suggestion": "「」を外して、直接話すように出力してください。例: わ！金閣寺だね！",
            # }

        # 複数の「」ブロックがあるかチェック
        quote_count = response.count("「")
        if quote_count >= 2:
            print(f"    ⚠️ Format: 複数の「」ブロック（{quote_count}個）を検出しましたが、続行します。")
            # return {
            #     "passed": False,
            #     "issue": f"複数の「」ブロックがあります（{quote_count}個）",
            #     "suggestion": "1つの連続した発言として出力してください。「」は使わず、直接話してください。",
            # }

        # 改行で複数ブロックに分かれているかチェック
        # 仕様変更: 8行以上でRETRY, 6-7行でWARN, 5行以下はPASS
        lines = [line.strip() for line in response.split("\n") if line.strip()]
        if len(lines) >= 8:
            return {
                "passed": False,
                "issue": f"発言が長すぎます（{len(lines)}行）",
                "suggestion": "5行以内にまとめて、簡潔に出力してください。",
            }
        elif len(lines) >= 6:
            # WARN扱い（PASSさせるが次回介入）
            print(f"    ⚠️ Format: {len(lines)}行を検出（WARN）。次回短縮を指示します。")
            # 内部的にはPASSだが、指導が必要な状態として扱うフラグやメッセージを持たせる設計が理想
            # 現状はPASS返却のみ

        return {
            "passed": True,
            "issue": "",
            "suggestion": "",
        }

    def _normalize_text(self, text: str) -> str:
        """
        判定用にテキストを正規化する。
        1. 引用・台本除外（「」、（）内の除去）
           ただし、全体が「」で囲まれている場合は中身を採用する。
        2. 記号正規化（！！→！、。。→。）
        3. 空白正規化
        """
        import re
        normalized = text.strip()

        # 全体が「」で囲まれている場合は中身を取り出す（台本形式の救済）
        # 文頭が「、文末が」で、かつ途中に閉じ括弧がない、あるいは
        # 単純に最初と最後を取り除く
        if normalized.startswith("「") and normalized.endswith("」"):
             # 中身だけ取り出す（ただし、途中で閉じてまた開くケース "「A」「B」" は除外すべきだが
             # ここでは簡易的に、全体がひとつの発言とみなせるなら剥がす）
             # 厳密には count("「") == 1 とかチェックすると良い
             if normalized.count("「") == 1:
                 normalized = normalized[1:-1]
        
        # 引用・台本除外: 「」や（）で囲まれた部分を削除
        # ただし、上記で剥がした後の残りの「」は引用とみなして削除
        normalized = re.sub(r"「.*?」", "", normalized)
        normalized = re.sub(r"（.*?）", "", normalized)
        normalized = re.sub(r"\(.*?\)", "", normalized)

        # 記号正規化
        # ！！ -> ！
        normalized = re.sub(r"！+", "！", normalized)
        normalized = re.sub(r"？+", "？", normalized)
        normalized = re.sub(r"、+", "、", normalized)
        normalized = re.sub(r"。+", "。", normalized)
        normalized = re.sub(r"…+", "…", normalized)

        # 空白正規化
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

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
        if not conversation_history or len(conversation_history) < 3:
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
        正規化については、文数カウントは記号依存なので原文（または正規化）どちらでも良いが、
        specに "記号正規化" があるので正規化済みテキストを使うのが安全。

        判定基準:
          4文以上 かつ 話題3つ以上 -> RETRY
          3文 または 話題2つ -> WARN

        Args:
            response: 評価対象の発言

        Returns:
            {
                "detected": bool,
                "issues": list[str],
                "level": str # "RETRY" or "WARN"
            }
        """
        normalized = self._normalize_text(response)

        # 文数カウント
        # 読点ではなく、句点・感嘆符・疑問符でカウント
        # 改行は正規化でスペースになっているので考慮不要（ただし正規化で繋がってしまった場合は文脈が変わる恐れがあるが、
        # normalize_textの実装は \s+ -> " " なので改行もスペースになる。文末記号がないと文が繋がる。
        # しかし通常は文末記号があるはず。）
        sentence_enders = ["。", "！", "？"]
        sentence_count = 0
        for char in sentence_enders:
             sentence_count += normalized.count(char)
        
        # 句点なしで終わっている短い文が連続する場合などはカウント漏れするが、
        # normalizedでは改行がないので、文末記号がないと文の区切りは判別不能。
        # AIは通常文末記号をつけるのでこれで近似する。
        if sentence_count == 0 and len(normalized) > 0:
            sentence_count = 1

        # 話題数の推定
        # 「〜について」「〜は」「〜の話」などの切り替え語
        topic_switch_pattern = r"(について|に関しては|の話|ですが|一方で|ちなみに)"
        topic_boundaries = len(re.findall(topic_switch_pattern, normalized))
        # 文頭の「〜は」は話題提示だが、文中の「〜は」は主語提示なので区別が難しい。
        # 簡易的にキーワードヒット数で近似。

        issues = []
        level = "PASS"

        # RETRY条件
        # 4文以上 かつ 話題3つ以上 (spec: "4文以上かつ話題が3つ以上" -> RETRY)
        # ちょっと待って、specは "4文以上かつ話題が3つ以上で RETRY"
        # "3文または話題2つは WARN"
        
        if sentence_count >= 4 and topic_boundaries >= 3:
            issues.append(f"話題と文が多すぎる（{sentence_count}文, 切換{topic_boundaries}回）")
            level = "RETRY"
        elif sentence_count >= 3 or topic_boundaries >= 2:
            issues.append(f"やや散漫（{sentence_count}文, 切換{topic_boundaries}回）")
            level = "WARN"

        if issues:
            return {"detected": True, "issues": issues, "level": level}
        
        return {"detected": False, "issues": [], "level": "PASS"}

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

    # ========== Director v3: Topic Manager Methods ==========

    def _get_character_role(self, speaker: str, depth_step: str) -> str:
        """深掘り段階に応じたキャラクター役割を返す"""
        roles = {
            "A": {  # やな（姉）
                "DISCOVER": "発見して驚く（「わ！」「へぇ！」）",
                "SURFACE": "素朴な疑問を投げかける（「どうして？」「何それ？」）",
                "WHY": "もっと知りたがる（「なんで？」「どういう仕組み？」）",
                "EXPAND": "関連することに興味を示す（「じゃあ〇〇も？」）",
            },
            "B": {  # あゆ（妹）
                "DISCOVER": "姉の発見に反応する",
                "SURFACE": "基本情報を提供する（「〇〇というものですよ」）",
                "WHY": "詳しく解説する（「実は〇〇なんです」）",
                "EXPAND": "豆知識を追加する（「ちなみに〇〇も」）",
            },
        }
        return roles.get(speaker, {}).get(depth_step, "自然に会話する")

    def _extract_hook_from_response(self, response: str, frame_description: str = "") -> str:
        """
        直前の発言から話題hookを抽出する。

        重要: 全体の会話ではなく、直前の発言（response）からのみ抽出する。
        これにより、会話の自然な流れが維持される。
        """
        # 正規表現で名詞候補を抽出（漢字・カタカナ・英数字の2文字以上）
        pattern = r'[一-龠々ヶァ-ヴーa-zA-Z]{2,}'

        # 直前の発言からのみ抽出
        candidates = re.findall(pattern, response)

        # 禁止トピックを除外
        candidates = [c for c in candidates if c not in self.topic_state.forbidden_topics]

        # 一般的すぎる単語を除外（拡張版）
        stop_words = {
            "そう", "ですね", "ます", "です", "やな", "あゆ", "姉様", "姉", "妹",
            "本当", "確か", "良い", "いい", "今年", "毎年", "今日", "昨日",
            "ちょっと", "なんか", "すごい", "とても", "少し", "やっぱり",
            "大事", "大切", "楽しみ", "嬉しい", "面白い", "一緒", "みんな",
        }
        candidates = [c for c in candidates if c not in stop_words and len(c) >= 2]

        # 最も長い候補を返す（具体的な話題である可能性が高い）
        if candidates:
            return max(candidates, key=len)

        # フォールバック: フレームから抽出（直前発言に具体的な話題がない場合のみ）
        if frame_description:
            frame_candidates = re.findall(pattern, frame_description)
            frame_candidates = [c for c in frame_candidates if c not in stop_words and len(c) >= 2]
            if frame_candidates:
                return max(frame_candidates, key=len)

        return ""  # 空を返す（hookなしとして扱う）

    def _build_strong_intervention(self, speaker: str) -> str:
        """
        介入指示を生成する（緩和版: 強制ではなくヒントとして）
        """
        role = self._get_character_role(speaker, self.topic_state.depth_step)
        forbidden_str = "、".join(self.topic_state.forbidden_topics) if self.topic_state.forbidden_topics else ""

        intervention = f"""【会話のヒント】
前の発言に自然に反応してください。

今の話題: {self.topic_state.focus_hook}
段階: {self.topic_state.depth_step}（深さ {self.topic_state.hook_depth}/3）
あなたの役割: {role}"""

        if forbidden_str:
            intervention += f"\n避けるべき話題: {forbidden_str}"

        intervention += "\n\n※50〜80文字、2文以内で応答してください。"

        return intervention

    def reset_topic_state(self):
        """話題状態をリセット（新しいナレーション開始時に呼ぶ）"""
        self.topic_state.reset()

    def reset_for_new_session(self):
        """新しいセッション開始時に全状態をリセット"""
        self.topic_state.reset()
        self.novelty_guard.reset()
        self.recent_patterns.clear()
        self.last_frame_num = -1
        print("    🔄 Director: 新しいセッションのため状態をリセット")

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
