"""
duo-talk v2.2 - NoveltyGuard
話題ループを検知し、同トピック内で切り口を変える

設計方針：
- 話題を変更するのではなく、同じ話題の切り口を変える
- 直近で使った戦略は避ける（バリエーション確保）
- 具体性・対立・行動・過去参照の4戦略
- 具体スロット充足チェック（一般論検知）

v2.2変更点：
- 具体性チェック機能追加
- トピック深度の詳細トラッキング
- 戦略選択ロジックの改善
- FewShotInjectorとの連携強化
"""

from typing import List, Set, Dict, Optional, Any, Tuple
from enum import Enum
from dataclasses import dataclass, field
import re


class LoopBreakStrategy(Enum):
    """ループ脱出戦略（話題変更ではなく切り口変更）"""
    FORCE_SPECIFIC_SLOT = "specific_slot"      # 具体スロット要求
    FORCE_CONFLICT_WITHIN = "conflict_within"  # 同トピ内の対立
    FORCE_ACTION_NEXT = "action_next"          # 次の行動を決める
    FORCE_PAST_REFERENCE = "past_reference"    # 過去の具体的エピソード
    FORCE_WHY = "force_why"                    # なぜ？を掘り下げる
    FORCE_EXPAND = "force_expand"              # 話題を広げる
    FORCE_CHANGE_TOPIC = "change_topic"        # 話題を強制的に変える
    NOOP = "noop"                              # 介入なし


@dataclass
class LoopCheckResult:
    """ループ検知結果"""
    loop_detected: bool = False
    stuck_nouns: List[str] = field(default_factory=list)
    strategy: LoopBreakStrategy = LoopBreakStrategy.NOOP
    injection: Optional[str] = None
    topic_depth: int = 0
    lacks_specificity: bool = False  # 具体性不足フラグ
    reason: str = ""  # 検知理由


@dataclass
class TopicState:
    """話題の状態トラッキング"""
    current_topic: str = ""
    topic_nouns: Set[str] = field(default_factory=set)
    depth: int = 0  # 同一話題での深さ
    has_specific_info: bool = False  # 具体的情報があるか
    has_numbers: bool = False  # 数値があるか
    has_examples: bool = False  # 例示があるか
    last_update_turn: int = 0


class NoveltyGuard:
    """
    話題ループを検知し、同トピック内で切り口を変える

    使用方法:
        guard = NoveltyGuard()

        # 各ターンで呼び出し
        result = guard.check_and_update(character_response)

        if result.loop_detected:
            # result.injection をプロンプトに追加
            builder.add(result.injection, Priority.DIRECTOR, "novelty_guard")
    """

    def __init__(
        self,
        max_topic_depth: int = 3,
        specificity_threshold: int = 2,
    ):
        """
        Args:
            max_topic_depth: ループと判定するまでの同一話題ターン数
            specificity_threshold: 具体性不足と判定するターン数
        """
        self.max_topic_depth = max_topic_depth
        self.specificity_threshold = specificity_threshold

        self.recent_nouns: List[Set[str]] = []
        self.recent_strategies: List[LoopBreakStrategy] = []
        self.turn_count: int = 0

        # トピック状態トラッキング
        self.topic_state = TopicState()

        # 具体性指標の履歴
        self.specificity_history: List[bool] = []

        # セマンティック重複検出用：発話履歴
        self.recent_utterances: List[str] = []
        self.max_utterance_history = 10

        # 重複パターン検出用の正規化パターン
        self.question_patterns = [
            r'覚えて(る|いる|いますか|ますか)(\?|？)?',
            r'知って(る|いる|いますか|ますか)(\?|？)?',
            r'〜(だ|です)(よね|ね)(\?|？)?',
            r'〜(じゃない|ではない)(\?|？)?',
        ]

        # 除外する一般的な名詞
        self.stop_nouns = {
            "こと", "もの", "ところ", "とき", "ため", "よう",
            "それ", "これ", "あれ", "どれ", "ここ", "そこ",
            "私", "あなた", "姉様", "方", "人", "今", "前",
            "感じ", "気持ち", "思い", "話", "言葉", "意味",
            "前回", "今回", "今日", "明日", "昨日", "最近",
        }
        
        # 具体性を示すパターン
        self.specific_patterns = [
            r'\d+',  # 数値
            r'[0-9０-９]+',  # 全角数値
            r'%|パーセント|割',  # 割合
            r'm/s|km/h|度|℃|秒|分|時間',  # 単位
            r'例えば|たとえば|具体的に',  # 例示
            r'〜した時|〜の時|前に|以前',  # 過去参照
            r'どこ|どの|何番|何回',  # 具体的な場所/回数
        ]

    def extract_nouns(self, text: str) -> Set[str]:
        """
        テキストから名詞を抽出

        Note: 本番環境ではMeCab等での形態素解析を推奨
        """
        # カタカナ、漢字の連続、および「お/ご」で始まる名詞を抽出
        nouns = set(re.findall(r'[ァ-ヶー・]{2,}|[一-龠]{2,}|[おご][一-龠]{1,}[ぁ-ん]?', text))

        # 短すぎる名詞と一般的な名詞を除外
        nouns = {n for n in nouns if len(n) >= 2 and n not in self.stop_nouns}

        return nouns

    def check_specificity(self, text: str) -> Tuple[bool, Dict[str, bool]]:
        """
        テキストの具体性をチェック
        
        Args:
            text: チェックするテキスト
            
        Returns:
            (具体的か, 詳細情報dict)
        """
        details = {
            "has_numbers": False,
            "has_examples": False,
            "has_past_ref": False,
            "has_location": False,
        }
        
        # 数値チェック
        if re.search(r'\d+|[0-9０-９]+', text):
            details["has_numbers"] = True
        
        # 例示チェック
        if re.search(r'例えば|たとえば|具体的に|〜みたいな|〜のような', text):
            details["has_examples"] = True
        
        # 過去参照チェック
        if re.search(r'前に|以前|〜した時|あの時|その時', text):
            details["has_past_ref"] = True
        
        # 場所/位置チェック
        if re.search(r'どこ|どの|何番|右|左|前|後|上|下|〜コーナー|〜区間', text):
            details["has_location"] = True
        
        # 1つでも具体的な要素があればTrue
        is_specific = any(details.values())

        return is_specific, details

    def check_semantic_repetition(self, text: str) -> Tuple[bool, str, float]:
        """
        セマンティックレベルの重複をチェック

        同じ内容（同じ質問、同じエピソード参照など）が繰り返されているか検出。

        Args:
            text: チェックするテキスト

        Returns:
            (重複検出, 重複パターン説明, 類似度スコア)
        """
        # 最低3件の履歴がないとセマンティック重複は検出しない
        # （初期ターンでの誤検出を防ぐ）
        if len(self.recent_utterances) < 3:
            return False, "", 0.0

        # テキストを正規化（句読点・空白除去）
        normalized_text = self._normalize_for_comparison(text)

        max_similarity = 0.0
        most_similar_idx = -1

        for i, past_utterance in enumerate(self.recent_utterances):
            normalized_past = self._normalize_for_comparison(past_utterance)

            # 文字レベルの類似度
            similarity = self._calculate_similarity(normalized_text, normalized_past)

            if similarity > max_similarity:
                max_similarity = similarity
                most_similar_idx = i

        # 高い類似度（0.7以上）で重複検出
        if max_similarity >= 0.7:
            pattern = "文全体の類似"
            if max_similarity >= 0.9:
                pattern = "ほぼ同一の発言"
            return True, pattern, max_similarity

        # 特定のパターンの繰り返しをチェック
        pattern_match = self._check_question_pattern_repetition(text)
        if pattern_match:
            return True, pattern_match, 0.8

        return False, "", max_similarity

    def _normalize_for_comparison(self, text: str) -> str:
        """比較用にテキストを正規化"""
        # 句読点・空白・改行を除去
        normalized = re.sub(r'[、。！？!?,.\s\n]', '', text)
        # ひらがなの語尾変化を正規化
        normalized = re.sub(r'(ます|です|だよ|だね|よね|かな|だな)$', '', normalized)
        return normalized

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        2つのテキストの類似度を計算（シンプルなn-gram Jaccard）
        """
        if not text1 or not text2:
            return 0.0

        # 2-gram セット
        def get_ngrams(text: str, n: int = 2) -> Set[str]:
            return {text[i:i+n] for i in range(len(text) - n + 1)} if len(text) >= n else {text}

        ngrams1 = get_ngrams(text1)
        ngrams2 = get_ngrams(text2)

        if not ngrams1 or not ngrams2:
            return 0.0

        intersection = len(ngrams1 & ngrams2)
        union = len(ngrams1 | ngrams2)

        return intersection / union if union > 0 else 0.0

    def _check_question_pattern_repetition(self, text: str) -> Optional[str]:
        """
        同じ質問パターンの繰り返しをチェック

        例: 「覚えてる？」が複数回出現
        """
        # 「覚えてる」系のパターン
        remember_pattern = r'覚えて(る|いる|いますか|ますか|ない)?'
        if re.search(remember_pattern, text):
            # 過去の発言で同じパターンが何回出たか
            count = sum(1 for u in self.recent_utterances if re.search(remember_pattern, u))
            if count >= 2:
                return f"「覚えてる？」の繰り返し ({count+1}回目)"

        # 「〜の時」パターン（同じエピソード参照）
        episode_pattern = r'(前に|あの時|その時).{5,30}(た|だ)(時|とき)'
        matches_current = re.findall(episode_pattern, text)
        if matches_current:
            for past_utterance in self.recent_utterances[-3:]:
                matches_past = re.findall(episode_pattern, past_utterance)
                if matches_past:
                    return "同じエピソードへの繰り返し参照"

        return None

    def _update_utterance_history(self, text: str) -> None:
        """発話履歴を更新"""
        self.recent_utterances.append(text)
        if len(self.recent_utterances) > self.max_utterance_history:
            self.recent_utterances.pop(0)

    def _generate_semantic_repeat_injection(self, repeat_pattern: str, severe: bool) -> str:
        """セマンティック重複検出時のインジェクションを生成"""
        if severe:
            return (
                f"【重複発言検出】「{repeat_pattern}」が検出されました。\n"
                "この発言パターンは既に使われています。完全に別のアプローチに切り替えてください：\n"
                "- 同じ質問やエピソードを参照しない\n"
                "- 新しい話題や視点を導入する\n"
                "- 繰り返しを避けて対話を前に進める"
            )
        else:
            return (
                f"【類似発言検出】「{repeat_pattern}」のような発言パターンが検出されました。\n"
                "同じような内容を繰り返さず、別の角度から話を展開してください：\n"
                "- 新しい具体例を挙げる\n"
                "- 別の側面について話す\n"
                "- 話を次のステップに進める"
            )

    def check_phrase_repetition(self, text: str) -> Tuple[bool, str, float]:
        """
        定型フレーズ繰り返し検出（履歴全体で同じフレーズが出現していないか）

        「それもまた良い思い出ですね」のような定型フレーズの繰り返しを検出。
        履歴が1件でも動作し、高い類似度で過去に同じ発言がないかチェック。

        Args:
            text: チェックするテキスト

        Returns:
            (繰り返し検出, マッチしたフレーズ, 類似度)
        """
        if not self.recent_utterances:
            return False, "", 0.0

        normalized_text = self._normalize_for_comparison(text)

        # 短すぎる発言は無視
        if len(normalized_text) < 8:
            return False, "", 0.0

        # 履歴全体をチェック（直前以外も含む）
        for past_utterance in self.recent_utterances:
            normalized_past = self._normalize_for_comparison(past_utterance)

            if len(normalized_past) < 8:
                continue

            similarity = self._calculate_similarity(normalized_text, normalized_past)

            # 高い閾値（0.85以上）で同一フレーズと判定
            if similarity >= 0.85:
                # 短いフレーズを表示用に抽出
                display_phrase = past_utterance[:20] + "..." if len(past_utterance) > 20 else past_utterance
                return True, display_phrase, similarity

        return False, "", 0.0

    def check_parrot_back(self, text: str) -> Tuple[bool, float]:
        """
        オウム返し検出（直前の発言との高類似度チェック）

        相手の発言をほぼそのまま繰り返しているかを検出。
        セマンティック重複とは別に、直前発言のみを高閾値でチェック。

        Args:
            text: チェックするテキスト

        Returns:
            (オウム返し検出, 類似度)
        """
        if not self.recent_utterances:
            return False, 0.0

        # 直前の発言のみチェック
        last_utterance = self.recent_utterances[-1]

        normalized_text = self._normalize_for_comparison(text)
        normalized_last = self._normalize_for_comparison(last_utterance)

        # 短すぎる発言は無視（相槌など）
        if len(normalized_text) < 10 or len(normalized_last) < 10:
            return False, 0.0

        similarity = self._calculate_similarity(normalized_text, normalized_last)

        # 高い閾値（0.75以上）でオウム返し検出
        # これは「直前の発言をコピー」なので明確な問題
        if similarity >= 0.75:
            return True, similarity

        return False, similarity

    def check_and_update(self, text: str, update: bool = True) -> LoopCheckResult:
        """
        ループ検知して結果を返す

        Args:
            text: チェックするテキスト（直近の発言）
            update: 内部状態を更新するかどうか

        Returns:
            LoopCheckResult: 検知結果
        """
        self.turn_count += 1 if update else 0
        current_nouns = self.extract_nouns(text)
        is_specific, specificity_details = self.check_specificity(text)

        result = LoopCheckResult()
        result.topic_depth = 0

        # === 定型フレーズ繰り返し検出（履歴全体で同じフレーズが出現していないか） ===
        is_phrase_repeat, matched_phrase, phrase_similarity = self.check_phrase_repetition(text)
        if is_phrase_repeat:
            result.loop_detected = True
            result.stuck_nouns = list(current_nouns)[:5]
            result.reason = f"定型フレーズ繰り返し: 「{matched_phrase}」 (類似度: {phrase_similarity:.2f})"
            result.strategy = LoopBreakStrategy.FORCE_EXPAND
            result.injection = (
                f"【定型フレーズ繰り返し検出】「{matched_phrase}」に類似した発言が既に使われています。\n"
                "同じ表現の繰り返しは避け、別の言い方や視点で話してください：\n"
                "- 具体的な感想や意見を述べる\n"
                "- 新しい話題や質問を提起する\n"
                "- 相手の発言に対して別の角度からリアクションする"
            )
            if update:
                self._update_utterance_history(text)
            return result

        # === オウム返し検出（直前発言との高類似度） ===
        is_parrot, parrot_similarity = self.check_parrot_back(text)
        if is_parrot:
            result.loop_detected = True
            result.stuck_nouns = list(current_nouns)[:5]
            result.reason = f"オウム返し検出 (類似度: {parrot_similarity:.2f})"
            result.strategy = LoopBreakStrategy.FORCE_EXPAND
            result.injection = (
                "【オウム返し検出】相手の発言をほぼそのまま繰り返しています。\n"
                "自分の言葉で別の視点や意見を述べてください：\n"
                "- 相手の発言に対する自分の感想や意見\n"
                "- 新しい情報や視点の追加\n"
                "- 別の話題への自然な展開"
            )
            if update:
                self._update_utterance_history(text)
            return result

        # === セマンティック重複検出 ===
        is_semantic_repeat, repeat_pattern, similarity = self.check_semantic_repetition(text)
        if is_semantic_repeat:
            result.loop_detected = True
            result.stuck_nouns = list(current_nouns)[:5]
            result.reason = f"セマンティック重複: {repeat_pattern} (類似度: {similarity:.2f})"

            # 高い類似度の場合は強制話題転換
            if similarity >= 0.9:
                result.strategy = LoopBreakStrategy.FORCE_CHANGE_TOPIC
                result.injection = self._generate_semantic_repeat_injection(repeat_pattern, severe=True)
            else:
                result.strategy = LoopBreakStrategy.FORCE_EXPAND
                result.injection = self._generate_semantic_repeat_injection(repeat_pattern, severe=False)

            # 発話履歴を更新してから早期リターン
            if update:
                self._update_utterance_history(text)
            return result

        # 具体性履歴を更新
        if update:
            self.specificity_history.append(is_specific)
            if len(self.specificity_history) > 10:
                self.specificity_history.pop(0)

        # === ループ検知 ===
        target_nouns = self.recent_nouns
        if len(target_nouns) >= self.max_topic_depth:
            overlap_count = 0
            common_nouns = current_nouns.copy()

            # 深いループの判定（連続する過去 N 件の重なりを確認）
            deep_overlap_count = 0
            for past_nouns in reversed(self.recent_nouns):
                if current_nouns & past_nouns:
                    deep_overlap_count += 1
                else:
                    break

            for past_nouns in self.recent_nouns[-self.max_topic_depth:]:
                intersection = current_nouns & past_nouns
                if intersection:
                    overlap_count += 1
                    common_nouns &= past_nouns

            result.topic_depth = overlap_count # 互換性のため維持

            # ループ検知条件
            if overlap_count >= self.max_topic_depth and common_nouns:
                result.loop_detected = True
                result.stuck_nouns = list(common_nouns)[:5]
                result.reason = f"同じ話題が{deep_overlap_count}ターン連続"
                
                # 深いループ（5ターン以上）の場合は強制話題転換
                if deep_overlap_count >= 5:
                    result.strategy = LoopBreakStrategy.FORCE_CHANGE_TOPIC
                else:
                    # 戦略選択
                    result.strategy = self._select_strategy(specificity_details, update=update)

                result.injection = self._generate_injection(
                    result.strategy,
                    result.stuck_nouns
                )

        # === 具体性不足検知 ===
        if not result.loop_detected and len(self.specificity_history) >= self.specificity_threshold:
            recent_specificity = self.specificity_history[-self.specificity_threshold:]
            if not any(recent_specificity):
                # 直近N発言が全て具体性不足
                result.lacks_specificity = True
                result.reason = f"直近{self.specificity_threshold}発言に具体的情報なし"
                
                # 具体化を強制
                if not result.loop_detected:
                    result.strategy = LoopBreakStrategy.FORCE_SPECIFIC_SLOT
                    result.injection = self._generate_specificity_injection()

        # トピック状態を更新
        if update:
            self._update_topic_state(current_nouns, is_specific, specificity_details)

            # 履歴更新
            self.recent_nouns.append(current_nouns)
            if len(self.recent_nouns) > 10:
                self.recent_nouns.pop(0)

            # 発話履歴更新（セマンティック重複検出用）
            self._update_utterance_history(text)

        return result

    def _update_topic_state(
        self,
        nouns: Set[str],
        is_specific: bool,
        details: Dict[str, bool]
    ) -> None:
        """トピック状態を更新"""
        # 話題が変わったかチェック
        if self.topic_state.topic_nouns:
            overlap = nouns & self.topic_state.topic_nouns
            overlap_ratio = len(overlap) / max(len(self.topic_state.topic_nouns), 1)
            
            if overlap_ratio < 0.3:
                # 話題が変わった
                self.topic_state = TopicState()
        
        # 状態更新
        self.topic_state.topic_nouns = nouns
        self.topic_state.depth += 1
        self.topic_state.has_specific_info = is_specific or self.topic_state.has_specific_info
        self.topic_state.has_numbers = details["has_numbers"] or self.topic_state.has_numbers
        self.topic_state.has_examples = details["has_examples"] or self.topic_state.has_examples
        self.topic_state.last_update_turn = self.turn_count

    def _select_strategy(self, specificity_details: Dict[str, bool], update: bool = True) -> LoopBreakStrategy:
        """
        状況に応じた戦略を選択
        
        Args:
            specificity_details: 具体性の詳細情報
            update: 選択した戦略を履歴に追加するか
        """
        # 直近2回で使った戦略は避ける
        recent_set = set(self.recent_strategies[-2:]) if self.recent_strategies else set()
        
        # 優先順位付き戦略リスト（状況に応じた調整）
        strategies = []
        
        # 数値がない場合は具体化優先
        if not specificity_details.get("has_numbers"):
            strategies.append(LoopBreakStrategy.FORCE_SPECIFIC_SLOT)
        
        # 過去参照がない場合
        if not specificity_details.get("has_past_ref"):
            strategies.append(LoopBreakStrategy.FORCE_PAST_REFERENCE)
        
        # その他の戦略を追加
        strategies.extend([
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN,
            LoopBreakStrategy.FORCE_ACTION_NEXT,
            LoopBreakStrategy.FORCE_WHY,
            LoopBreakStrategy.FORCE_EXPAND,
        ])
        
        # 重複を除去しつつ順序を維持
        seen = set()
        unique_strategies = []
        for s in strategies:
            if s not in seen:
                seen.add(s)
                unique_strategies.append(s)
        
        # 直近で使っていない戦略を選択
        selected_strategy = LoopBreakStrategy.FORCE_SPECIFIC_SLOT
        for strategy in unique_strategies:
            if strategy not in recent_set:
                selected_strategy = strategy
                break

        if update:
            self.recent_strategies.append(selected_strategy)
            if len(self.recent_strategies) > 10:
                self.recent_strategies.pop(0)
                
        return selected_strategy

    def _generate_injection(
        self,
        strategy: LoopBreakStrategy,
        stuck_nouns: List[str]
    ) -> str:
        """戦略に応じた注入プロンプトを生成"""
        topic = "、".join(stuck_nouns[:3]) if stuck_nouns else "現在の話題"

        # 禁止警告を全ての戦略に追加
        forbidden_warning = f"\n\n⚠️【禁止】「{topic}」という単語を直接使わないでください。別の表現や話題に切り替えてください。"

        injections = {
            LoopBreakStrategy.FORCE_SPECIFIC_SLOT: (
                f"【話題転換：別の視点へ】「{topic}」の話はループしています。\n"
                "同じ話題を続けず、以下のいずれかに切り替えてください：\n"
                "- 目の前の景色の別の部分に注目\n"
                "- 全く違う具体的な話題を出す\n"
                "- 相手に新しい質問を投げかける"
                + forbidden_warning
            ),
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN: (
                f"【話題転換：違う角度へ】「{topic}」がループしています。\n"
                "この話題から離れて、別のことについて話してください：\n"
                "- 姉妹の意見が分かれる別の話題\n"
                "- 今見えている別のものについて\n"
                "- 新しい発見や疑問"
                + forbidden_warning
            ),
            LoopBreakStrategy.FORCE_ACTION_NEXT: (
                f"【話題転換：行動へ】「{topic}」の話はここで終わり：\n"
                "- 別の場所に移動する提案\n"
                "- 「じゃあ〜を見に行こう」\n"
                "- 全く違うことを始める"
                + forbidden_warning
            ),
            LoopBreakStrategy.FORCE_PAST_REFERENCE: (
                f"【話題転換：別の思い出へ】「{topic}」とは無関係な思い出を話してください：\n"
                "- 全く違う場所での出来事\n"
                "- 別のテーマの過去の話\n"
                "- 今見えているものとは関係ない思い出"
                + forbidden_warning
            ),
            LoopBreakStrategy.FORCE_WHY: (
                f"【話題転換：新しい疑問へ】「{topic}」以外のことについて質問してください：\n"
                "- 今見えている別のものについて「なぜ？」\n"
                "- 相手のことについて質問\n"
                "- 全く新しいテーマへの興味"
                + forbidden_warning
            ),
            LoopBreakStrategy.FORCE_EXPAND: (
                f"【話題転換：別の話題へ】「{topic}」から完全に離れてください：\n"
                "- 視界の中の別のものに注目\n"
                "- 全く関係ない新しい話題を出す\n"
                "- 相手の興味を引く別のことを提案"
                + forbidden_warning
            ),
            LoopBreakStrategy.FORCE_CHANGE_TOPIC: (
                f"【話題強制終了】「{topic}」の話は禁止です。全く別の話題に移ってください。\n"
                "- 目の前の景色の別の部分に注目する\n"
                "- 相手に全く新しい質問を投げかける\n"
                "- 以前の話題を引きずらないこと"
                + forbidden_warning
            ),
        }

        return injections.get(strategy, "")

    def _generate_specificity_injection(self) -> str:
        """具体性不足時の注入プロンプトを生成"""
        return (
            "【具体化要求】会話が一般的になっています。以下のいずれかを追加してください：\n"
            "- 具体的な数値（〜回、〜秒、〜度など）\n"
            "- 具体的な例（「例えば〜」「〜みたいな」）\n"
            "- 具体的な場所や時間（「〜の時」「〜で」）\n"
            "- 具体的な経験（「前に〜した」「〜を試した」）"
        )

    def reset(self) -> None:
        """状態をリセット（新しいセッション開始時）"""
        self.recent_nouns.clear()
        self.recent_strategies.clear()
        self.specificity_history.clear()
        self.recent_utterances.clear()  # セマンティック重複検出用履歴もクリア
        self.turn_count = 0
        self.topic_state = TopicState()

    def seed_with_history(self, history: List[str]) -> None:
        """
        過去の発話履歴でNoveltyGuardを初期化（継続会話用）

        Args:
            history: 過去の発話リスト（発言テキストのみ）
        """
        for utterance in history:
            if utterance:
                # 履歴をシード：update=Trueで内部状態を更新
                self.check_and_update(utterance, update=True)
        print(f"    📚 NoveltyGuard seeded with {len(history)} historical utterances")

    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        return {
            "turn_count": self.turn_count,
            "history_length": len(self.recent_nouns),
            "utterance_history_length": len(self.recent_utterances),  # 発話履歴長
            "recent_strategies": [s.value for s in self.recent_strategies[-5:]],
            "current_nouns": list(self.recent_nouns[-1]) if self.recent_nouns else [],
            "topic_depth": self.topic_state.depth,
            "has_specific_info": self.topic_state.has_specific_info,
            "recent_specificity": self.specificity_history[-5:] if self.specificity_history else [],
        }

    def get_topic_state(self) -> Dict[str, Any]:
        """現在のトピック状態を取得"""
        return {
            "topic_nouns": list(self.topic_state.topic_nouns),
            "depth": self.topic_state.depth,
            "has_specific_info": self.topic_state.has_specific_info,
            "has_numbers": self.topic_state.has_numbers,
            "has_examples": self.topic_state.has_examples,
        }
