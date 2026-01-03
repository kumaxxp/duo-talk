"""
duo-talk v2.1 - NoveltyGuard
話題ループを検知し、同トピック内で切り口を変える

設計方針：
- 話題を変更するのではなく、同じ話題の切り口を変える
- 直近で使った戦略は避ける（バリエーション確保）
- 具体性・対立・行動・過去参照の4戦略
"""

from typing import List, Set, Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
import re


class LoopBreakStrategy(Enum):
    """ループ脱出戦略（話題変更ではなく切り口変更）"""
    FORCE_SPECIFIC_SLOT = "specific_slot"      # 具体スロット要求
    FORCE_CONFLICT_WITHIN = "conflict_within"  # 同トピ内の対立
    FORCE_ACTION_NEXT = "action_next"          # 次の行動を決める
    FORCE_PAST_REFERENCE = "past_reference"    # 過去の具体的エピソード
    NOOP = "noop"                              # 介入なし


@dataclass
class LoopCheckResult:
    """ループ検知結果"""
    loop_detected: bool = False
    stuck_nouns: List[str] = field(default_factory=list)
    strategy: LoopBreakStrategy = LoopBreakStrategy.NOOP
    injection: Optional[str] = None
    topic_depth: int = 0


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

    def __init__(self, max_topic_depth: int = 3):
        """
        Args:
            max_topic_depth: ループと判定するまでの同一話題ターン数
        """
        self.max_topic_depth = max_topic_depth
        self.recent_nouns: List[Set[str]] = []
        self.recent_strategies: List[LoopBreakStrategy] = []

        # 除外する一般的な名詞
        self.stop_nouns = {
            "こと", "もの", "ところ", "とき", "ため", "よう",
            "それ", "これ", "あれ", "どれ", "ここ", "そこ",
            "私", "あなた", "姉様", "方", "人", "今", "前",
        }

    def extract_nouns(self, text: str) -> Set[str]:
        """
        テキストから名詞を抽出

        Note: 本番環境ではMeCab等での形態素解析を推奨
        """
        # カタカナ・漢字の連続を抽出
        nouns = set(re.findall(r'[ァ-ヶー]{2,}|[一-龯]{2,}', text))

        # 短すぎる名詞と一般的な名詞を除外
        nouns = {n for n in nouns if len(n) >= 2 and n not in self.stop_nouns}

        return nouns

    def check_and_update(self, text: str) -> LoopCheckResult:
        """
        ループ検知して結果を返す

        Args:
            text: チェックするテキスト（直近の発言）

        Returns:
            LoopCheckResult: 検知結果
        """
        current_nouns = self.extract_nouns(text)

        result = LoopCheckResult()

        if len(self.recent_nouns) >= self.max_topic_depth:
            overlap_count = 0
            common_nouns = current_nouns.copy()

            for past_nouns in self.recent_nouns[-self.max_topic_depth:]:
                intersection = current_nouns & past_nouns
                if intersection:
                    overlap_count += 1
                    common_nouns &= past_nouns

            result.topic_depth = overlap_count

            if overlap_count >= self.max_topic_depth and common_nouns:
                result.loop_detected = True
                result.stuck_nouns = list(common_nouns)[:5]  # 最大5つ
                result.strategy = self._select_strategy()
                result.injection = self._generate_injection(
                    result.strategy,
                    result.stuck_nouns
                )

        # 履歴更新
        self.recent_nouns.append(current_nouns)
        if len(self.recent_nouns) > 10:
            self.recent_nouns.pop(0)

        return result

    def _select_strategy(self) -> LoopBreakStrategy:
        """戦略を選択（直近で使った戦略は避ける）"""
        strategies = [
            LoopBreakStrategy.FORCE_SPECIFIC_SLOT,
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN,
            LoopBreakStrategy.FORCE_ACTION_NEXT,
            LoopBreakStrategy.FORCE_PAST_REFERENCE,
        ]

        # 直近2回で使った戦略は避ける
        recent_set = set(self.recent_strategies[-2:]) if self.recent_strategies else set()

        for strategy in strategies:
            if strategy not in recent_set:
                self.recent_strategies.append(strategy)
                if len(self.recent_strategies) > 10:
                    self.recent_strategies.pop(0)
                return strategy

        # 全部使った場合は最初の戦略
        self.recent_strategies.append(strategies[0])
        return strategies[0]

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
                "- 次の走行でどう変えるか\n"
                "- 設定やパラメータを調整するか\n"
                "- 休憩、確認、準備をするか\n"
                "※ 具体的なアクションを決める"
            ),
            LoopBreakStrategy.FORCE_PAST_REFERENCE: (
                f"【切り口変更：過去参照】「{topic}」に関連する過去の出来事を参照すること：\n"
                "- 「前に似たことがあった」\n"
                "- 「あの時は失敗/成功した」\n"
                "- 「そこから学んだことを活かす」\n"
                "※ 具体的な過去のエピソードを出す"
            ),
        }

        return injections.get(strategy, "")

    def reset(self) -> None:
        """状態をリセット（新しいセッション開始時）"""
        self.recent_nouns.clear()
        self.recent_strategies.clear()

    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        return {
            "history_length": len(self.recent_nouns),
            "recent_strategies": [s.value for s in self.recent_strategies[-5:]],
            "current_nouns": list(self.recent_nouns[-1]) if self.recent_nouns else []
        }
