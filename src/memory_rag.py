"""
Memory RAG システム（拡張版）

エピソード記憶（体験/出来事）と事実記憶（ユーザー情報）を
分離して管理し、関連する記憶を検索・提供する。

設計原則:
- エピソード記憶を最優先（体験の共有感を重視）
- 事実記憶で補完
- 既存のsister_memoryとの互換性維持
"""

import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
from enum import Enum

import chromadb
from chromadb.config import Settings


class MemoryType(str, Enum):
    """記憶の種類"""
    EPISODE = "episode"  # 体験・出来事
    FACT = "fact"        # ユーザーに関する事実


class FactCategory(str, Enum):
    """事実記憶のカテゴリ"""
    PREFERENCE = "preference"    # 好み・趣味
    EXPERIENCE = "experience"    # 経験・背景
    INFO = "info"               # その他の情報


@dataclass
class EpisodeMemory:
    """エピソード記憶"""
    memory_id: str
    timestamp: str
    summary: str
    yana_perspective: str
    ayu_perspective: str
    emotional_tag: str
    importance: float           # 0.0 - 1.0
    context_tags: List[str]
    run_id: Optional[str] = None
    turn_number: Optional[int] = None
    relevance_score: float = 0.0

    def to_prompt_text(self, character: str) -> str:
        """プロンプト注入用テキストに変換"""
        perspective = self.yana_perspective if character == "yana" else self.ayu_perspective
        return f"【過去の体験】{self.summary}（{perspective}）"


@dataclass
class FactMemory:
    """事実記憶"""
    memory_id: str
    timestamp: str
    summary: str
    category: FactCategory
    subject: str = "user"       # 誰に関する事実か
    confidence: float = 1.0     # 確信度
    source_episode_id: Optional[str] = None  # 抽出元エピソード
    relevance_score: float = 0.0

    def to_prompt_text(self) -> str:
        """プロンプト注入用テキストに変換"""
        category_label = {
            FactCategory.PREFERENCE: "好み",
            FactCategory.EXPERIENCE: "経験",
            FactCategory.INFO: "情報"
        }.get(self.category, "情報")
        return f"【{category_label}】{self.summary}"


@dataclass
class MemorySearchResult:
    """統合検索結果"""
    episodes: List[EpisodeMemory]
    facts: List[FactMemory]

    def to_prompt_text(self, character: str) -> str:
        """プロンプト注入用テキスト"""
        parts = []

        if self.episodes:
            parts.append("=== 関連する過去の体験 ===")
            for ep in self.episodes[:3]:
                parts.append(ep.to_prompt_text(character))

        if self.facts:
            parts.append("=== 覚えている事実 ===")
            for fact in self.facts[:3]:
                parts.append(fact.to_prompt_text())

        return "\n".join(parts)


@dataclass
class MemoryRAGStats:
    """統計情報"""
    total_episodes: int
    total_facts: int
    episode_buffer_size: int
    fact_buffer_size: int
    by_emotional_tag: Dict[str, int]
    by_fact_category: Dict[str, int]


class MemoryRAG:
    """Memory RAGシステム（エピソード/事実分離版）"""

    def __init__(
        self,
        db_path: str = "./memories",
        episode_collection: str = "memory_episodes",
        fact_collection: str = "memory_facts"
    ):
        """
        Args:
            db_path: ChromaDB保存ベースパス
            episode_collection: エピソードコレクション名
            fact_collection: 事実コレクション名
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        # ChromaDB初期化
        self.client = chromadb.PersistentClient(
            path=str(self.db_path / "memory_rag"),
            settings=Settings(anonymized_telemetry=False)
        )

        # コレクション取得または作成
        self.episodes = self.client.get_or_create_collection(
            name=episode_collection,
            metadata={"hnsw:space": "cosine"}
        )

        self.facts = self.client.get_or_create_collection(
            name=fact_collection,
            metadata={"hnsw:space": "cosine"}
        )

        # 書き込みバッファ
        self.episode_buffer: List[EpisodeMemory] = []
        self.fact_buffer: List[FactMemory] = []

        # 設定
        self.duplicate_threshold = 0.9
        self.episode_boost = 0.1  # エピソードの検索優先度ブースト

    # === 検索 ===
    def search(
        self,
        query: str,
        character: str,
        top_k: int = 5,
        include_facts: bool = True
    ) -> MemorySearchResult:
        """
        関連する記憶を統合検索

        Args:
            query: 検索クエリ
            character: 視点を取得するキャラクター
            top_k: 取得件数
            include_facts: 事実記憶も含めるか

        Returns:
            エピソードと事実の統合結果
        """
        # エピソード検索
        episodes = self._search_episodes(query, character, top_k)

        # 事実検索（オプション）
        facts = []
        if include_facts:
            facts = self._search_facts(query, min(3, top_k))

        return MemorySearchResult(episodes=episodes, facts=facts)

    def _search_episodes(
        self,
        query: str,
        character: str,
        top_k: int
    ) -> List[EpisodeMemory]:
        """エピソード検索"""
        if self.episodes.count() == 0:
            return []

        try:
            results = self.episodes.query(
                query_texts=[query],
                n_results=min(top_k, self.episodes.count())
            )
        except Exception as e:
            print(f"Episode search error: {e}")
            return []

        return self._format_episode_results(results)

    def _search_facts(
        self,
        query: str,
        top_k: int
    ) -> List[FactMemory]:
        """事実検索"""
        if self.facts.count() == 0:
            return []

        try:
            results = self.facts.query(
                query_texts=[query],
                n_results=min(top_k, self.facts.count())
            )
        except Exception as e:
            print(f"Fact search error: {e}")
            return []

        return self._format_fact_results(results)

    def _format_episode_results(
        self,
        results: Dict[str, Any]
    ) -> List[EpisodeMemory]:
        """エピソード結果をフォーマット"""
        formatted = []

        if not results['documents'] or not results['documents'][0]:
            return formatted

        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i] if results['metadatas'] else {}
            distance = results['distances'][0][i] if results['distances'] else 0

            # スコア計算（エピソードにブースト）
            relevance_score = max(0, 1 - distance) + self.episode_boost

            # context_tags の復元
            context_tags_str = meta.get("context_tags", "")
            context_tags = context_tags_str.split(",") if context_tags_str else []

            formatted.append(EpisodeMemory(
                memory_id=meta.get("memory_id", ""),
                timestamp=meta.get("timestamp", ""),
                summary=meta.get("summary", doc),
                yana_perspective=meta.get("yana_perspective", ""),
                ayu_perspective=meta.get("ayu_perspective", ""),
                emotional_tag=meta.get("emotional_tag", "neutral"),
                importance=float(meta.get("importance", 0.5)),
                context_tags=context_tags,
                run_id=meta.get("run_id"),
                turn_number=int(meta.get("turn_number", 0)) if meta.get("turn_number") else None,
                relevance_score=relevance_score
            ))

        # スコアでソート
        formatted.sort(key=lambda x: x.relevance_score, reverse=True)
        return formatted

    def _format_fact_results(
        self,
        results: Dict[str, Any]
    ) -> List[FactMemory]:
        """事実結果をフォーマット"""
        formatted = []

        if not results['documents'] or not results['documents'][0]:
            return formatted

        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i] if results['metadatas'] else {}
            distance = results['distances'][0][i] if results['distances'] else 0

            relevance_score = max(0, 1 - distance)

            formatted.append(FactMemory(
                memory_id=meta.get("memory_id", ""),
                timestamp=meta.get("timestamp", ""),
                summary=meta.get("summary", doc),
                category=FactCategory(meta.get("category", "info")),
                subject=meta.get("subject", "user"),
                confidence=float(meta.get("confidence", 1.0)),
                source_episode_id=meta.get("source_episode_id"),
                relevance_score=relevance_score
            ))

        return formatted

    # === バッファリング ===
    def buffer_episode(
        self,
        summary: str,
        yana_perspective: str,
        ayu_perspective: str,
        emotional_tag: str,
        importance: float = 0.5,
        context_tags: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        turn_number: Optional[int] = None
    ) -> str:
        """エピソード記憶をバッファに追加"""
        memory_id = str(uuid.uuid4())

        entry = EpisodeMemory(
            memory_id=memory_id,
            timestamp=datetime.now().isoformat(),
            summary=summary,
            yana_perspective=yana_perspective,
            ayu_perspective=ayu_perspective,
            emotional_tag=emotional_tag,
            importance=importance,
            context_tags=context_tags or [],
            run_id=run_id,
            turn_number=turn_number
        )

        self.episode_buffer.append(entry)
        return memory_id

    def buffer_fact(
        self,
        summary: str,
        category: FactCategory,
        subject: str = "user",
        confidence: float = 1.0,
        source_episode_id: Optional[str] = None
    ) -> str:
        """事実記憶をバッファに追加"""
        memory_id = str(uuid.uuid4())

        entry = FactMemory(
            memory_id=memory_id,
            timestamp=datetime.now().isoformat(),
            summary=summary,
            category=category,
            subject=subject,
            confidence=confidence,
            source_episode_id=source_episode_id
        )

        self.fact_buffer.append(entry)
        return memory_id

    # === フラッシュ ===
    def flush_buffer(self) -> Dict[str, int]:
        """バッファをDBに書き込み"""
        result = {
            "episodes_written": 0,
            "episodes_skipped": 0,
            "facts_written": 0,
            "facts_skipped": 0
        }

        # エピソード書き込み
        for ep in self.episode_buffer:
            if not self._is_episode_duplicate(ep):
                self._write_episode(ep)
                result["episodes_written"] += 1
            else:
                result["episodes_skipped"] += 1

        # 事実書き込み
        for fact in self.fact_buffer:
            if not self._is_fact_duplicate(fact):
                self._write_fact(fact)
                result["facts_written"] += 1
            else:
                result["facts_skipped"] += 1

        # バッファクリア
        self.episode_buffer.clear()
        self.fact_buffer.clear()

        return result

    def _write_episode(self, ep: EpisodeMemory) -> None:
        """エピソードをDBに書き込み"""
        self.episodes.add(
            ids=[ep.memory_id],
            documents=[ep.summary],
            metadatas=[{
                "memory_id": ep.memory_id,
                "timestamp": ep.timestamp,
                "summary": ep.summary,
                "yana_perspective": ep.yana_perspective,
                "ayu_perspective": ep.ayu_perspective,
                "emotional_tag": ep.emotional_tag,
                "importance": ep.importance,
                "context_tags": ",".join(ep.context_tags),
                "run_id": ep.run_id or "",
                "turn_number": ep.turn_number or 0
            }]
        )

    def _write_fact(self, fact: FactMemory) -> None:
        """事実をDBに書き込み"""
        self.facts.add(
            ids=[fact.memory_id],
            documents=[fact.summary],
            metadatas=[{
                "memory_id": fact.memory_id,
                "timestamp": fact.timestamp,
                "summary": fact.summary,
                "category": fact.category.value,
                "subject": fact.subject,
                "confidence": fact.confidence,
                "source_episode_id": fact.source_episode_id or ""
            }]
        )

    def _is_episode_duplicate(self, ep: EpisodeMemory) -> bool:
        """エピソード重複チェック"""
        if self.episodes.count() == 0:
            return False

        results = self.episodes.query(
            query_texts=[ep.summary],
            n_results=1
        )

        if results['distances'] and results['distances'][0]:
            similarity = 1 - results['distances'][0][0]
            return similarity > self.duplicate_threshold

        return False

    def _is_fact_duplicate(self, fact: FactMemory) -> bool:
        """事実重複チェック"""
        if self.facts.count() == 0:
            return False

        results = self.facts.query(
            query_texts=[fact.summary],
            n_results=1
        )

        if results['distances'] and results['distances'][0]:
            similarity = 1 - results['distances'][0][0]
            return similarity > self.duplicate_threshold

        return False

    # === 直接書き込み（Reflection用） ===
    def add_episode_direct(
        self,
        summary: str,
        yana_perspective: str,
        ayu_perspective: str,
        emotional_tag: str,
        importance: float = 0.5,
        context_tags: Optional[List[str]] = None
    ) -> Optional[str]:
        """エピソードを直接追加（重複チェック付き）"""
        ep = EpisodeMemory(
            memory_id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            summary=summary,
            yana_perspective=yana_perspective,
            ayu_perspective=ayu_perspective,
            emotional_tag=emotional_tag,
            importance=importance,
            context_tags=context_tags or []
        )

        if self._is_episode_duplicate(ep):
            return None

        self._write_episode(ep)
        return ep.memory_id

    def add_fact_direct(
        self,
        summary: str,
        category: FactCategory,
        subject: str = "user",
        confidence: float = 1.0,
        source_episode_id: Optional[str] = None
    ) -> Optional[str]:
        """事実を直接追加（重複チェック付き）"""
        fact = FactMemory(
            memory_id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            summary=summary,
            category=category,
            subject=subject,
            confidence=confidence,
            source_episode_id=source_episode_id
        )

        if self._is_fact_duplicate(fact):
            return None

        self._write_fact(fact)
        return fact.memory_id

    # === 管理 ===
    def get_stats(self) -> MemoryRAGStats:
        """統計情報を取得"""
        by_emotional_tag: Dict[str, int] = {}
        by_fact_category: Dict[str, int] = {}

        # エピソード統計
        if self.episodes.count() > 0:
            ep_data = self.episodes.get(include=["metadatas"])
            for meta in ep_data['metadatas']:
                tag = meta.get("emotional_tag", "unknown")
                by_emotional_tag[tag] = by_emotional_tag.get(tag, 0) + 1

        # 事実統計
        if self.facts.count() > 0:
            fact_data = self.facts.get(include=["metadatas"])
            for meta in fact_data['metadatas']:
                cat = meta.get("category", "unknown")
                by_fact_category[cat] = by_fact_category.get(cat, 0) + 1

        return MemoryRAGStats(
            total_episodes=self.episodes.count(),
            total_facts=self.facts.count(),
            episode_buffer_size=len(self.episode_buffer),
            fact_buffer_size=len(self.fact_buffer),
            by_emotional_tag=by_emotional_tag,
            by_fact_category=by_fact_category
        )

    def clear_buffer(self) -> None:
        """バッファをクリア（書き込みせず破棄）"""
        self.episode_buffer.clear()
        self.fact_buffer.clear()


# シングルトンインスタンス
_memory_rag: Optional[MemoryRAG] = None


def get_memory_rag() -> MemoryRAG:
    """シングルトンインスタンスを取得"""
    global _memory_rag
    if _memory_rag is None:
        _memory_rag = MemoryRAG()
    return _memory_rag


def reset_memory_rag() -> None:
    """シングルトンをリセット（テスト用）"""
    global _memory_rag
    _memory_rag = None
