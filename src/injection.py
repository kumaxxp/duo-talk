"""
duo-talk v2.1 - Injection Priority System
プロンプトへの情報注入を優先度で管理

設計方針：
- 優先度が低い数字ほど先に配置（文脈として早く）
- LAST_UTTERANCE は HISTORY の直後（55）に配置
- スロット未充足時は強制注入
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any
from enum import IntEnum


class Priority(IntEnum):
    """注入優先度（低い数字 = 先に配置）"""
    SYSTEM = 10              # システムプロンプト（固定）
    WORLD_RULES = 15         # 姉妹共同行動ルール（固定）
    DEEP_VALUES = 20         # キャラクター深層設定（短く）
    LONG_MEMORY = 30         # 長期記憶（姉妹の共有体験）
    SISTER_MEMORY = 35       # 姉妹視点記憶（過去の体験）
    RAG = 40                 # RAG知識
    HISTORY = 50             # 会話履歴
    LAST_UTTERANCE = 55      # 直前の相手の発言（HISTORYの直後）
    SHORT_MEMORY = 60        # 短期記憶（最近のイベント）
    SCENE_FACTS = 65         # VLM観測
    WORLD_STATE = 70         # 現在の走行状態
    SLOT_FILLER = 75         # 未充足スロットの強制注入
    DIRECTOR = 80            # ディレクター指示
    OWNER_INSTRUCTION = 82   # オーナー介入指示
    FEW_SHOT = 85            # Few-shot例（状況トリガー）


@dataclass
class PromptInjection:
    """プロンプトへの情報注入"""
    text: str
    priority: int
    source: str = ""
    slot_type: Optional[str] = None  # 充足するスロットタイプ

    def __post_init__(self):
        if isinstance(self.priority, Priority):
            self.priority = int(self.priority)


# 情報スロット定義
SLOT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "具体性": {
        "description": "具体的な数値・場所・エピソード",
        "indicators": ["数値", "m/s", "秒", "回", "コーナー", "位置", "前に", "あの時"],
        "injection_template": (
            "【必須】現在の話題について、以下のいずれかを1つ以上含めること：\n"
            "- 具体的な数値（速度、距離、時間、回数）\n"
            "- 具体的な場所や位置（どのコーナー、どの区間）\n"
            "- 過去の具体的なエピソード"
        )
    },
    "関係性": {
        "description": "姉妹が一緒にいることが分かる要素",
        "indicators": ["私たち", "うちら", "二人で", "一緒に", "姉様に", "あゆに"],
        "injection_template": (
            "【必須】姉妹が「一緒にいる」ことが分かる要素を含めること：\n"
            "- 「私たち」「うちら」など共同表現\n"
            "- 相手への依頼や確認\n"
            "- 役割分担の言及"
        )
    },
    "非対称性": {
        "description": "姉妹の役割の違いが分かる要素",
        "indicators": ["感覚", "データ", "計算", "直感", "分析", "数字"],
        "injection_template": (
            "【推奨】姉妹の役割の違いを活かすこと：\n"
            "- やな：感覚や直感での判断・発見\n"
            "- あゆ：データや数値での補足・分析"
        )
    }
}


class SlotChecker:
    """スロット充足チェッカー"""

    def __init__(self):
        self.filled_slots: Set[str] = set()

    def check_text(self, text: str) -> Set[str]:
        """テキストから充足されたスロットを検出"""
        filled = set()
        for slot_name, slot_def in SLOT_DEFINITIONS.items():
            for indicator in slot_def["indicators"]:
                if indicator in text:
                    filled.add(slot_name)
                    break
        return filled

    def update(self, text: str) -> None:
        """テキストでスロット充足状態を更新"""
        self.filled_slots.update(self.check_text(text))

    def get_unfilled(self, required: Optional[List[str]] = None) -> List[str]:
        """未充足スロットを取得"""
        if required is None:
            required = ["具体性"]  # デフォルトで具体性は必須
        return [s for s in required if s not in self.filled_slots]

    def reset(self) -> None:
        """リセット（新しいターンの開始時）"""
        self.filled_slots.clear()


class PromptBuilder:
    """
    優先度に基づいてプロンプトを組み立てる

    使用方法:
        builder = PromptBuilder()
        builder.add("システムプロンプト", Priority.SYSTEM, "system")
        builder.add("会話履歴", Priority.HISTORY, "history")
        builder.add("直前の発言", Priority.LAST_UTTERANCE, "last_utterance")

        # スロットチェック
        builder.check_and_inject_slots("センサー")

        prompt = builder.build()
    """

    def __init__(self, max_tokens: int = 6000):
        self.injections: List[PromptInjection] = []
        self.max_tokens = max_tokens
        self.slot_checker = SlotChecker()

    def add(
        self,
        text: str,
        priority: int,
        source: str = "",
        slot_type: Optional[str] = None
    ) -> None:
        """
        プロンプト要素を追加

        Args:
            text: 注入するテキスト
            priority: 優先度（Priority enumまたはint）
            source: デバッグ用のソース名
            slot_type: この要素が充足するスロットタイプ
        """
        if isinstance(priority, Priority):
            priority = int(priority)

        self.injections.append(PromptInjection(text, priority, source, slot_type))

        # スロット充足をチェック
        if slot_type:
            self.slot_checker.filled_slots.add(slot_type)
        self.slot_checker.update(text)

    def check_and_inject_slots(
        self,
        current_topic: str,
        required_slots: Optional[List[str]] = None,
        topic_depth: int = 0
    ) -> List[str]:
        """
        未充足スロットがあれば強制注入

        Args:
            current_topic: 現在の話題
            required_slots: 必須スロットのリスト
            topic_depth: 同じ話題の継続ターン数

        Returns:
            List[str]: 注入されたスロットのリスト
        """
        if required_slots is None:
            required_slots = ["具体性"]
            # 3ターン以上同じ話題なら関係性も要求
            if topic_depth >= 3:
                required_slots.append("関係性")

        unfilled = self.slot_checker.get_unfilled(required_slots)

        for slot_name in unfilled:
            if slot_name in SLOT_DEFINITIONS:
                template = SLOT_DEFINITIONS[slot_name]["injection_template"]
                injection_text = f"{template}\n（現在の話題: {current_topic}）"
                self.add(
                    injection_text,
                    Priority.SLOT_FILLER,
                    f"slot_filler_{slot_name}"
                )

        return unfilled

    def build(self, include_debug: bool = False) -> str:
        """
        プロンプトを組み立てる

        Args:
            include_debug: デバッグ情報を含めるか

        Returns:
            str: 組み立てられたプロンプト
        """
        # 優先度でソート（低い順）
        sorted_injections = sorted(self.injections, key=lambda x: x.priority)

        if include_debug:
            parts = []
            for inj in sorted_injections:
                parts.append(f"<!-- [{inj.priority}] {inj.source} -->\n{inj.text}")
            return "\n\n".join(parts)
        else:
            return "\n\n".join([inj.text for inj in sorted_injections])

    def get_structure(self) -> List[Dict[str, Any]]:
        """デバッグ用: プロンプト構造を取得"""
        sorted_injections = sorted(self.injections, key=lambda x: x.priority)
        return [
            {
                "priority": inj.priority,
                "source": inj.source,
                "slot_type": inj.slot_type,
                "length": len(inj.text)
            }
            for inj in sorted_injections
        ]

    def reset(self) -> None:
        """ビルダーをリセット"""
        self.injections.clear()
        self.slot_checker.reset()
