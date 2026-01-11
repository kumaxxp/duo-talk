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

        injections = {
            LoopBreakStrategy.FORCE_SPECIFIC_SLOT: (
                f"【切り口変更：具体化】「{topic}」について、具体的な情報を1つ追加すること：\n"
                "- 数値（速度、距離、時間、温度、回数など）\n"
                "- 場所（どのコーナー、どの位置、どの区間）\n"
                "- 過去の具体的な出来事（「前に〜した」「あの時〜だった」）"
            ),
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN: (
                f"【切り口変更：意見対立】「{topic}」について、姉妹で意見が分かれる点を出すこと：\n"
                "- やな：直感や感覚での判断（「なんか〜な気がする」）\n"
                "- あゆ：データや数値での根拠（「数値では〜です」）\n"
                "※ 軽い対立 → 妥協 or 決着の流れで"
            ),
            LoopBreakStrategy.FORCE_ACTION_NEXT: (
                f"【切り口変更：次の行動】「{topic}」の話を踏まえて、次に何をするか決めること：\n"
                "- 具体的なアクションを決める\n"
                "- 「じゃあ〜しよう」「まず〜してみよう」\n"
                "※ 話を前に進める"
            ),
            LoopBreakStrategy.FORCE_PAST_REFERENCE: (
                f"【切り口変更：過去参照】「{topic}」に関連する過去の出来事を参照すること：\n"
                "- 「前に似たことがあった」\n"
                "- 「あの時は失敗/成功した」\n"
                "- 「そこから学んだことを活かす」"
            ),
            LoopBreakStrategy.FORCE_WHY: (
                f"【切り口変更：深掘り】「{topic}」について、「なぜ？」を掘り下げること：\n"
                "- 「でも、なんでそうなるの？」\n"
                "- 原因や理由を探る\n"
                "- 背景にある仕組みを説明する"
            ),
            LoopBreakStrategy.FORCE_EXPAND: (
                f"【切り口変更：話題拡張】「{topic}」から関連する話題に広げること：\n"
                "- 「それって、〜にも関係あるよね」\n"
                "- 別の角度から見てみる\n"
                "- 新しい視点を加える"
            ),
            LoopBreakStrategy.FORCE_CHANGE_TOPIC: (
                f"【話題強制終了】「{topic}」の話はもう十分にしました。この話はここで切り上げ、全く別の話題に移ってください。\n"
                "- 目の前の景色の別の部分に注目する\n"
                "- 相手に全く新しい質問を投げかける\n"
                "- 以前の話題を引きずらないこと"
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
        self.turn_count = 0
        self.topic_state = TopicState()

    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        return {
            "turn_count": self.turn_count,
            "history_length": len(self.recent_nouns),
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
