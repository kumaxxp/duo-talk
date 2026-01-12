"""
duo-talk v2.2 - Injection Priority System with Dual-RAG Support
プロンプトへの情報注入を優先度で管理

設計方針：
- 優先度が低い数字ほど先に配置（文脈として早く）
- LAST_UTTERANCE は HISTORY の直後（55）に配置
- スロット未充足時は強制注入
- Dual-RAG (Style RAG + Memory RAG) 対応
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any
from enum import IntEnum


class Priority(IntEnum):
    """注入優先度（低い数字 = 先に配置）"""
    SYSTEM = 10              # システムプロンプト（固定）
    WORLD_RULES = 15         # 姉妹共同行動ルール（固定）
    DEEP_VALUES = 20         # キャラクター深層設定（短く）
    STYLE_RAG = 25           # Style RAGからの口調サンプル [NEW]
    LONG_MEMORY = 30         # 長期記憶（姉妹の共有体験）
    MEMORY_RAG_EPISODE = 32  # Memory RAG エピソード記憶 [NEW]
    MEMORY_RAG_FACT = 34     # Memory RAG 事実記憶 [NEW]
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


class ForbiddenContextManager:
    """
    禁止コンテキスト管理

    特定のキーワード、エピソードID、トピックの注入を防ぐ。
    ループ検出時に動的に禁止リストを更新できる。
    """

    def __init__(self):
        self.forbidden_keywords: Set[str] = set()  # 禁止キーワード
        self.forbidden_episode_ids: Set[str] = set()  # 禁止エピソードID
        self.forbidden_patterns: List[str] = []  # 禁止パターン（正規表現）

    def add_keyword(self, keyword: str) -> None:
        """禁止キーワードを追加"""
        if keyword and len(keyword) >= 2:
            self.forbidden_keywords.add(keyword)
            print(f"    🚫 Forbidden context added: {keyword}")

    def add_keywords(self, keywords: List[str]) -> None:
        """複数の禁止キーワードを追加"""
        for kw in keywords:
            self.add_keyword(kw)

    def add_episode_id(self, episode_id: str) -> None:
        """禁止エピソードIDを追加"""
        if episode_id:
            self.forbidden_episode_ids.add(episode_id)

    def add_pattern(self, pattern: str) -> None:
        """禁止パターン（正規表現）を追加"""
        if pattern:
            self.forbidden_patterns.append(pattern)

    def is_forbidden(self, text: str, episode_id: str = "") -> bool:
        """テキストまたはエピソードIDが禁止されているか判定"""
        import re

        # エピソードIDチェック
        if episode_id and episode_id in self.forbidden_episode_ids:
            return True

        # キーワードチェック
        for keyword in self.forbidden_keywords:
            if keyword in text:
                return True

        # パターンチェック
        for pattern in self.forbidden_patterns:
            if re.search(pattern, text):
                return True

        return False

    def filter_episodes(self, episodes: List[Any]) -> List[Any]:
        """エピソードリストから禁止コンテキストを除外"""
        filtered = []
        for ep in episodes:
            # エピソードの内容を取得（様々な形式に対応）
            content = getattr(ep, 'content', '') or getattr(ep, 'text', '') or str(ep)
            ep_id = getattr(ep, 'id', '') or getattr(ep, 'memory_id', '')

            if not self.is_forbidden(content, ep_id):
                filtered.append(ep)
            else:
                print(f"    🚫 Episode filtered: {ep_id[:20]}...")

        return filtered

    def filter_facts(self, facts: List[Any]) -> List[Any]:
        """事実リストから禁止コンテキストを除外"""
        filtered = []
        for fact in facts:
            content = getattr(fact, 'content', '') or getattr(fact, 'text', '') or str(fact)
            fact_id = getattr(fact, 'id', '') or getattr(fact, 'memory_id', '')

            if not self.is_forbidden(content, fact_id):
                filtered.append(fact)
            else:
                print(f"    🚫 Fact filtered: {fact_id[:20]}...")

        return filtered

    def clear(self) -> None:
        """禁止リストをクリア"""
        count = len(self.forbidden_keywords) + len(self.forbidden_episode_ids)
        self.forbidden_keywords.clear()
        self.forbidden_episode_ids.clear()
        self.forbidden_patterns.clear()
        if count > 0:
            print(f"    🔄 Forbidden context cleared ({count} items)")

    def get_stats(self) -> Dict[str, int]:
        """統計情報を取得"""
        return {
            "keywords": len(self.forbidden_keywords),
            "episode_ids": len(self.forbidden_episode_ids),
            "patterns": len(self.forbidden_patterns),
        }


# グローバルインスタンス
_forbidden_context_manager: Optional[ForbiddenContextManager] = None


def get_forbidden_context_manager() -> ForbiddenContextManager:
    """ForbiddenContextManagerのグローバルインスタンスを取得"""
    global _forbidden_context_manager
    if _forbidden_context_manager is None:
        _forbidden_context_manager = ForbiddenContextManager()
    return _forbidden_context_manager


class DualRAGInjector:
    """
    Dual-RAG (Style RAG + Memory RAG) をPromptBuilderに注入するヘルパー

    使用方法:
        from src.style_rag import get_style_rag
        from src.memory_rag import get_memory_rag

        injector = DualRAGInjector(
            style_rag=get_style_rag(),
            memory_rag=get_memory_rag()
        )

        # PromptBuilderに注入
        injector.inject(
            builder=builder,
            character_id="yana",
            query="現在の状況や話題",
            emotion="excited"
        )
    """

    def __init__(
        self,
        style_rag: Optional[Any] = None,
        memory_rag: Optional[Any] = None,
        max_style_samples: int = 3,
        max_episodes: int = 3,
        max_facts: int = 3,
        forbidden_context: Optional[ForbiddenContextManager] = None
    ):
        """
        Args:
            style_rag: StyleRAGインスタンス
            memory_rag: MemoryRAGインスタンス
            max_style_samples: 注入するスタイルサンプルの最大数
            max_episodes: 注入するエピソード記憶の最大数
            max_facts: 注入する事実記憶の最大数
            forbidden_context: 禁止コンテキストマネージャ
        """
        self.style_rag = style_rag
        self.memory_rag = memory_rag
        self.max_style_samples = max_style_samples
        self.max_episodes = max_episodes
        self.max_facts = max_facts
        self.forbidden_context = forbidden_context or get_forbidden_context_manager()

    def inject(
        self,
        builder: PromptBuilder,
        character_id: str,
        query: str,
        emotion: Optional[str] = None,
        include_style: bool = True,
        include_memory: bool = True
    ) -> Dict[str, int]:
        """
        Dual-RAGの結果をPromptBuilderに注入

        Args:
            builder: 注入先のPromptBuilder
            character_id: キャラクターID ("yana" or "ayu")
            query: 検索クエリ（現在の状況や話題）
            emotion: オプション: 感情フィルタ
            include_style: Style RAGを含めるか
            include_memory: Memory RAGを含めるか

        Returns:
            注入された要素数 {"style": N, "episodes": N, "facts": N}
        """
        result = {"style": 0, "episodes": 0, "facts": 0}

        # Style RAG注入
        if include_style and self.style_rag:
            result["style"] = self._inject_style(
                builder, character_id, query, emotion
            )

        # Memory RAG注入
        if include_memory and self.memory_rag:
            ep_count, fact_count = self._inject_memory(
                builder, character_id, query
            )
            result["episodes"] = ep_count
            result["facts"] = fact_count

        return result

    def _inject_style(
        self,
        builder: PromptBuilder,
        character_id: str,
        query: str,
        emotion: Optional[str]
    ) -> int:
        """Style RAGを注入"""
        try:
            samples = self.style_rag.retrieve(
                character_id=character_id,
                query=query,
                emotion=emotion,
                top_k=self.max_style_samples
            )

            if not samples:
                return 0

            # スタイルセクションを構築
            lines = [
                "# Speaking Style Guide",
                "Your speaking style must follow these examples:",
                "--- BEGIN STYLE SAMPLES ---"
            ]

            for sample in samples:
                lines.append(sample.to_prompt_text())

            lines.append("--- END STYLE SAMPLES ---")

            builder.add(
                "\n".join(lines),
                Priority.STYLE_RAG,
                "style_rag"
            )

            return len(samples)

        except Exception as e:
            print(f"Style RAG injection error: {e}")
            return 0

    def _inject_memory(
        self,
        builder: PromptBuilder,
        character_id: str,
        query: str
    ) -> tuple:
        """Memory RAGを注入（禁止コンテキストフィルター適用）"""
        try:
            search_result = self.memory_rag.search(
                query=query,
                character=character_id,
                top_k=max(self.max_episodes, self.max_facts),
                include_facts=True
            )

            ep_count = 0
            fact_count = 0

            # エピソード記憶を注入（禁止コンテキストフィルター適用）
            if search_result.episodes:
                episodes = search_result.episodes[:self.max_episodes]

                # 禁止コンテキストを除外
                episodes = self.forbidden_context.filter_episodes(episodes)

                if episodes:
                    lines = ["# Long-term Memory (Episodes)"]
                    for ep in episodes:
                        lines.append(ep.to_prompt_text(character_id))

                    builder.add(
                        "\n".join(lines),
                        Priority.MEMORY_RAG_EPISODE,
                        "memory_rag_episode"
                    )
                    ep_count = len(episodes)

            # 事実記憶を注入（禁止コンテキストフィルター適用）
            if search_result.facts:
                facts = search_result.facts[:self.max_facts]

                # 禁止コンテキストを除外
                facts = self.forbidden_context.filter_facts(facts)

                if facts:
                    lines = ["# Known Facts"]
                    for fact in facts:
                        lines.append(fact.to_prompt_text())

                    builder.add(
                        "\n".join(lines),
                        Priority.MEMORY_RAG_FACT,
                        "memory_rag_fact"
                    )
                    fact_count = len(facts)

            return ep_count, fact_count

        except Exception as e:
            print(f"Memory RAG injection error: {e}")
            return 0, 0

    def inject_style_only(
        self,
        builder: PromptBuilder,
        character_id: str,
        query: str,
        emotion: Optional[str] = None
    ) -> int:
        """Style RAGのみ注入"""
        return self.inject(
            builder, character_id, query, emotion,
            include_style=True, include_memory=False
        )["style"]

    def inject_memory_only(
        self,
        builder: PromptBuilder,
        character_id: str,
        query: str
    ) -> Dict[str, int]:
        """Memory RAGのみ注入"""
        result = self.inject(
            builder, character_id, query,
            include_style=False, include_memory=True
        )
        return {"episodes": result["episodes"], "facts": result["facts"]}
