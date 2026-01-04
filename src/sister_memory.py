"""
姉妹視点記憶システム

やなとあゆが過去の体験を「姉妹それぞれの視点」で記憶し、
会話に自然に反映させる。

設計原則:
- 走行中は読み出しのみ（レイテンシ確保）
- バッチ書き込み（終了後にまとめて保存）
- キャラ崩壊防止フィルタ必須
"""

import uuid
import re
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path

import chromadb
from chromadb.config import Settings


@dataclass
class MemoryEntry:
    """記憶エントリ"""
    event_id: str
    timestamp: str
    event_summary: str
    yana_perspective: str
    ayu_perspective: str
    emotional_tag: str
    context_tags: List[str]
    run_id: Optional[str] = None
    turn_number: Optional[int] = None


@dataclass
class MemoryResult:
    """検索結果"""
    event_id: str
    summary: str
    perspective: str
    emotional_tag: str
    relevance_score: float
    timestamp: str

    def to_prompt_text(self) -> str:
        """プロンプト注入用テキストに変換"""
        return f"【過去の記憶】{self.summary}（{self.perspective}）"


@dataclass
class FlushResult:
    """フラッシュ結果"""
    total: int
    written: int
    skipped: int
    errors: List[str]
    skipped_reasons: Dict[str, int]


@dataclass
class MemoryStats:
    """統計情報"""
    total_memories: int
    buffer_size: int
    emotional_tag_distribution: Dict[str, int]
    oldest_memory: Optional[str]
    newest_memory: Optional[str]


class MemoryValidator:
    """記憶の妥当性検証（キャラ崩壊防止）"""

    # やなの禁止パターン
    YANA_FORBIDDEN = [
        r"データ(を|で|が)重視",
        r"計算(を|で|が)優先",
        r"リスク(を|は)避け",
        r"慎重に(判断|分析)",
        r"統計的に",
        r"論理的に考え",
    ]

    # あゆの禁止パターン
    AYU_FORBIDDEN = [
        r"直感(で|が|を)",
        r"なんとなく",
        r"とりあえず(やって|試し)",
        r"勢いで",
        r"感覚(で|が|を)",
        r"理屈(より|じゃなく)",
    ]

    # 関係性破壊パターン
    RELATIONSHIP_FORBIDDEN = [
        r"姉様(を|が)馬鹿に",
        r"あゆ(を|が)見下",
        r"嫌い",
        r"うざい",
        r"邪魔",
    ]

    def validate(self, memory: MemoryEntry) -> tuple[bool, Optional[str]]:
        """
        記憶を検証

        Returns:
            (is_valid, reason): 妥当性とスキップ理由
        """
        # やな視点チェック
        for pattern in self.YANA_FORBIDDEN:
            if re.search(pattern, memory.yana_perspective):
                return False, "yana_character_violation"

        # あゆ視点チェック
        for pattern in self.AYU_FORBIDDEN:
            if re.search(pattern, memory.ayu_perspective):
                return False, "ayu_character_violation"

        # 関係性チェック
        combined = memory.yana_perspective + memory.ayu_perspective
        for pattern in self.RELATIONSHIP_FORBIDDEN:
            if re.search(pattern, combined):
                return False, "relationship_violation"

        return True, None


class SisterMemory:
    """姉妹視点の記憶システム"""

    def __init__(
        self,
        db_path: str = "./memories/sister_memory",
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    ):
        """
        Args:
            db_path: ChromaDB保存パス
            embedding_model: sentence-transformersモデル名
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # ChromaDB初期化
        self.client = chromadb.PersistentClient(
            path=str(self.db_path),
            settings=Settings(anonymized_telemetry=False)
        )

        # コレクション取得または作成
        self.collection = self.client.get_or_create_collection(
            name="sister_memories",
            metadata={"hnsw:space": "cosine"}
        )

        # バッファと検証器
        self.write_buffer: List[MemoryEntry] = []
        self.validator = MemoryValidator()

        # 設定
        self.duplicate_threshold = 0.95

    # === 検索（走行中使用） ===
    def search(
        self,
        query: str,
        character: str,
        n_results: int = 3,
        filters: Optional[Dict[str, str]] = None
    ) -> List[MemoryResult]:
        """
        関連する記憶を検索

        Args:
            query: 検索クエリ（現在の状況や話題）
            character: 視点を取得するキャラクター ("yana" or "ayu")
            n_results: 取得件数
            filters: 追加フィルタ

        Returns:
            キャラクター視点でフォーマットされた記憶リスト
        """
        if self.collection.count() == 0:
            return []

        # フィルタ構築
        where_clause = None
        if filters:
            where_clause = filters

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(n_results, self.collection.count()),
                where=where_clause
            )
        except Exception as e:
            print(f"Memory search error: {e}")
            return []

        return self._format_results(results, character)

    def search_by_tags(
        self,
        tags: List[str],
        character: str,
        n_results: int = 3
    ) -> List[MemoryResult]:
        """タグベースの検索"""
        if not tags or self.collection.count() == 0:
            return []

        # タグをクエリとして使用
        query = " ".join(tags)
        return self.search(query, character, n_results)

    def _format_results(
        self,
        results: Dict[str, List[List[str]]],
        character: str
    ) -> List[MemoryResult]:
        """検索結果をフォーマット"""
        formatted = []

        if not results['documents'] or not results['documents'][0]:
            return formatted

        perspective_key = f"{character}_perspective"

        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i] if results['metadatas'] else {}
            distance = results['distances'][0][i] if results['distances'] else 0

            # 距離をスコアに変換（cosine距離なので1-distanceで類似度に）
            relevance_score = max(0, 1 - distance)

            formatted.append(MemoryResult(
                event_id=meta.get("event_id", ""),
                summary=meta.get("event_summary", doc),
                perspective=meta.get(perspective_key, ""),
                emotional_tag=meta.get("emotional_tag", "neutral"),
                relevance_score=relevance_score,
                timestamp=meta.get("timestamp", "")
            ))

        return formatted

    # === バッファリング（走行中使用） ===
    def buffer_event(
        self,
        event_summary: str,
        yana_perspective: str,
        ayu_perspective: str,
        emotional_tag: str,
        context_tags: List[str],
        run_id: Optional[str] = None,
        turn_number: Optional[int] = None
    ) -> str:
        """
        記憶をバッファに追加（DBには書き込まない）

        Returns:
            生成されたevent_id
        """
        event_id = str(uuid.uuid4())

        entry = MemoryEntry(
            event_id=event_id,
            timestamp=datetime.now().isoformat(),
            event_summary=event_summary,
            yana_perspective=yana_perspective,
            ayu_perspective=ayu_perspective,
            emotional_tag=emotional_tag,
            context_tags=context_tags,
            run_id=run_id,
            turn_number=turn_number
        )

        self.write_buffer.append(entry)
        return event_id

    def get_buffer_size(self) -> int:
        """現在のバッファサイズを取得"""
        return len(self.write_buffer)

    # === フラッシュ（走行終了後使用） ===
    def flush_buffer(self, validate: bool = True) -> FlushResult:
        """
        バッファの記憶をDBに書き込み

        Args:
            validate: キャラ崩壊フィルタを適用するか

        Returns:
            書き込み結果
        """
        total = len(self.write_buffer)
        written = 0
        skipped = 0
        errors: List[str] = []
        skipped_reasons: Dict[str, int] = {}

        for entry in self.write_buffer:
            try:
                # 検証
                if validate:
                    is_valid, reason = self.validator.validate(entry)
                    if not is_valid:
                        skipped += 1
                        if reason:
                            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                        continue

                # 重複チェック
                if self._is_duplicate(entry):
                    skipped += 1
                    skipped_reasons["duplicate"] = skipped_reasons.get("duplicate", 0) + 1
                    continue

                # DB書き込み
                self._write_to_db(entry)
                written += 1

            except Exception as e:
                errors.append(f"Error writing {entry.event_id}: {e}")

        # バッファクリア
        self.write_buffer.clear()

        return FlushResult(
            total=total,
            written=written,
            skipped=skipped,
            errors=errors,
            skipped_reasons=skipped_reasons
        )

    def clear_buffer(self) -> None:
        """バッファをクリア（書き込みせず破棄）"""
        self.write_buffer.clear()

    def _is_duplicate(self, entry: MemoryEntry) -> bool:
        """重複チェック"""
        if self.collection.count() == 0:
            return False

        results = self.collection.query(
            query_texts=[entry.event_summary],
            n_results=1
        )

        if results['distances'] and results['distances'][0]:
            similarity = 1 - results['distances'][0][0]
            return similarity > self.duplicate_threshold

        return False

    def _write_to_db(self, entry: MemoryEntry) -> None:
        """DBに書き込み"""
        self.collection.add(
            ids=[entry.event_id],
            documents=[entry.event_summary],
            metadatas=[{
                "event_id": entry.event_id,
                "timestamp": entry.timestamp,
                "event_summary": entry.event_summary,
                "yana_perspective": entry.yana_perspective,
                "ayu_perspective": entry.ayu_perspective,
                "emotional_tag": entry.emotional_tag,
                "context_tags": ",".join(entry.context_tags),
                "run_id": entry.run_id or "",
                "turn_number": entry.turn_number or 0
            }]
        )

    # === 管理 ===
    def get_stats(self) -> MemoryStats:
        """統計情報を取得"""
        total = self.collection.count()

        # 感情タグ分布を取得
        tag_distribution: Dict[str, int] = {}
        oldest: Optional[str] = None
        newest: Optional[str] = None

        if total > 0:
            all_data = self.collection.get(include=["metadatas"])
            for meta in all_data['metadatas']:
                tag = meta.get("emotional_tag", "unknown")
                tag_distribution[tag] = tag_distribution.get(tag, 0) + 1

                ts = meta.get("timestamp", "")
                if ts:
                    if oldest is None or ts < oldest:
                        oldest = ts
                    if newest is None or ts > newest:
                        newest = ts

        return MemoryStats(
            total_memories=total,
            buffer_size=len(self.write_buffer),
            emotional_tag_distribution=tag_distribution,
            oldest_memory=oldest,
            newest_memory=newest
        )

    def export_memories(
        self,
        output_path: str,
        format: str = "json"
    ) -> None:
        """記憶をエクスポート"""
        import json

        all_data = self.collection.get(include=["metadatas", "documents"])

        memories = []
        for i, doc in enumerate(all_data['documents']):
            meta = all_data['metadatas'][i]
            memories.append({
                "document": doc,
                **meta
            })

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)


# シングルトンインスタンス
_sister_memory: Optional[SisterMemory] = None


def get_sister_memory() -> SisterMemory:
    """シングルトンインスタンスを取得"""
    global _sister_memory
    if _sister_memory is None:
        _sister_memory = SisterMemory()
    return _sister_memory


def reset_sister_memory() -> None:
    """シングルトンをリセット（テスト用）"""
    global _sister_memory
    _sister_memory = None
