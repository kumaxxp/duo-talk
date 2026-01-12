"""
Style RAG システム

キャラクターの口調・演技パターンを管理し、
状況に応じた適切なスタイルサンプルを検索・提供する。

設計原則:
- 感情・状況に基づく検索
- Self-Evolution対応（👍評価のみ追加）
- テストデータの分離管理
"""

import uuid
import yaml
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from pathlib import Path
from enum import Enum

import chromadb
from chromadb.config import Settings


class DataOrigin(str, Enum):
    """データの出所"""
    INITIAL = "initial"           # 初期データ
    SELF_EVOLUTION = "self_evolution"  # ユーザー評価による追加
    TEST = "test"                 # テストデータ


@dataclass
class StyleSample:
    """スタイルサンプル"""
    sample_id: str
    character_id: str
    emotion: str
    situation: str
    example: str
    data_origin: DataOrigin
    created_at: str
    relevance_score: float = 0.0

    def to_prompt_text(self) -> str:
        """プロンプト注入用テキストに変換"""
        return f"【{self.situation}・{self.emotion}】{self.example}"


@dataclass
class StyleRAGStats:
    """統計情報"""
    total_samples: int
    by_character: Dict[str, int]
    by_emotion: Dict[str, int]
    by_origin: Dict[str, int]


class StyleRAG:
    """Style RAGシステム"""

    def __init__(
        self,
        db_path: str = "./memories/style_rag",
        data_dir: str = "./rag_data/style_samples"
    ):
        """
        Args:
            db_path: ChromaDB保存パス
            data_dir: スタイルサンプルYAMLのディレクトリ
        """
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.db_path.mkdir(parents=True, exist_ok=True)

        # ChromaDB初期化
        self.client = chromadb.PersistentClient(
            path=str(self.db_path),
            settings=Settings(anonymized_telemetry=False)
        )

        # コレクション取得または作成
        self.collection = self.client.get_or_create_collection(
            name="style_samples",
            metadata={"hnsw:space": "cosine"}
        )

        # 初回なら初期データをロード
        if self.collection.count() == 0:
            self._load_initial_data()

    def _load_initial_data(self) -> int:
        """初期データをYAMLからロード"""
        if not self.data_dir.exists():
            print(f"Warning: Style data directory not found: {self.data_dir}")
            return 0

        loaded_count = 0
        for yaml_file in self.data_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)

                if not data or 'samples' not in data:
                    continue

                character_id = data.get('character_id', yaml_file.stem)

                for sample in data['samples']:
                    self._add_sample(
                        character_id=character_id,
                        emotion=sample.get('emotion', 'neutral'),
                        situation=sample.get('situation', ''),
                        example=sample.get('example', ''),
                        data_origin=DataOrigin(sample.get('data_origin', 'initial'))
                    )
                    loaded_count += 1

            except Exception as e:
                print(f"Error loading {yaml_file}: {e}")

        print(f"Loaded {loaded_count} style samples from YAML files")
        return loaded_count

    def _add_sample(
        self,
        character_id: str,
        emotion: str,
        situation: str,
        example: str,
        data_origin: DataOrigin,
        sample_id: Optional[str] = None
    ) -> str:
        """サンプルをDBに追加"""
        if sample_id is None:
            sample_id = str(uuid.uuid4())

        # 検索用ドキュメント（状況・感情・例文を結合）
        document = f"{situation} {emotion} {example}"

        self.collection.add(
            ids=[sample_id],
            documents=[document],
            metadatas=[{
                "sample_id": sample_id,
                "character_id": character_id,
                "emotion": emotion,
                "situation": situation,
                "example": example,
                "data_origin": data_origin.value,
                "created_at": datetime.now().isoformat()
            }]
        )

        return sample_id

    # === 検索 ===
    def retrieve(
        self,
        character_id: str,
        query: str,
        emotion: Optional[str] = None,
        top_k: int = 3,
        exclude_test: bool = True
    ) -> List[StyleSample]:
        """
        現在の状況に合ったスタイルサンプルを検索

        Args:
            character_id: キャラクターID ("yana" or "ayu")
            query: 検索クエリ（現在の状況や感情）
            emotion: オプション: 感情フィルタ
            top_k: 取得件数
            exclude_test: テストデータを除外するか

        Returns:
            スタイルサンプルのリスト
        """
        if self.collection.count() == 0:
            return []

        # フィルタ構築
        where_conditions = [{"character_id": character_id}]

        if emotion:
            where_conditions.append({"emotion": emotion})

        if exclude_test:
            where_conditions.append({"data_origin": {"$ne": "test"}})

        # 複数条件の場合は $and を使用
        where_clause = None
        if len(where_conditions) == 1:
            where_clause = where_conditions[0]
        elif len(where_conditions) > 1:
            where_clause = {"$and": where_conditions}

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(top_k, self.collection.count()),
                where=where_clause
            )
        except Exception as e:
            print(f"Style RAG search error: {e}")
            return []

        return self._format_results(results)

    def retrieve_by_emotion(
        self,
        character_id: str,
        emotion: str,
        n_results: int = 3
    ) -> List[StyleSample]:
        """感情に基づいてサンプルを取得"""
        return self.retrieve(
            character_id=character_id,
            query=emotion,
            emotion=emotion,
            top_k=n_results
        )

    def _format_results(
        self,
        results: Dict[str, Any]
    ) -> List[StyleSample]:
        """検索結果をフォーマット"""
        formatted = []

        if not results['documents'] or not results['documents'][0]:
            return formatted

        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i] if results['metadatas'] else {}
            distance = results['distances'][0][i] if results['distances'] else 0

            # 距離をスコアに変換
            relevance_score = max(0, 1 - distance)

            formatted.append(StyleSample(
                sample_id=meta.get("sample_id", ""),
                character_id=meta.get("character_id", ""),
                emotion=meta.get("emotion", "neutral"),
                situation=meta.get("situation", ""),
                example=meta.get("example", ""),
                data_origin=DataOrigin(meta.get("data_origin", "initial")),
                created_at=meta.get("created_at", ""),
                relevance_score=relevance_score
            ))

        return formatted

    # === Self-Evolution ===
    def add_from_feedback(
        self,
        character_id: str,
        example: str,
        situation: str,
        emotion: str,
        feedback_type: str = "positive"
    ) -> Optional[str]:
        """
        ユーザーフィードバックからサンプルを追加

        Args:
            character_id: キャラクターID
            example: セリフ例
            situation: 状況
            emotion: 感情
            feedback_type: "positive" のみ追加

        Returns:
            追加された場合はsample_id、それ以外はNone
        """
        if feedback_type != "positive":
            return None

        # 重複チェック
        if self._is_duplicate(character_id, example):
            return None

        return self._add_sample(
            character_id=character_id,
            emotion=emotion,
            situation=situation,
            example=example,
            data_origin=DataOrigin.SELF_EVOLUTION
        )

    def _is_duplicate(
        self,
        character_id: str,
        example: str,
        threshold: float = 0.9
    ) -> bool:
        """重複チェック"""
        if self.collection.count() == 0:
            return False

        results = self.collection.query(
            query_texts=[example],
            n_results=1,
            where={"character_id": character_id}
        )

        if results['distances'] and results['distances'][0]:
            similarity = 1 - results['distances'][0][0]
            return similarity > threshold

        return False

    # === 管理 ===
    def delete_test_data(self, character_id: Optional[str] = None) -> int:
        """テストデータを削除"""
        where_clause = {"data_origin": "test"}
        if character_id:
            where_clause = {
                "$and": [
                    {"data_origin": "test"},
                    {"character_id": character_id}
                ]
            }

        try:
            # テストデータのIDを取得
            results = self.collection.get(where=where_clause)
            if results['ids']:
                self.collection.delete(ids=results['ids'])
                return len(results['ids'])
        except Exception as e:
            print(f"Error deleting test data: {e}")

        return 0

    def get_stats(self) -> StyleRAGStats:
        """統計情報を取得"""
        by_character: Dict[str, int] = {}
        by_emotion: Dict[str, int] = {}
        by_origin: Dict[str, int] = {}

        total = self.collection.count()

        if total > 0:
            all_data = self.collection.get(include=["metadatas"])
            for meta in all_data['metadatas']:
                char = meta.get("character_id", "unknown")
                by_character[char] = by_character.get(char, 0) + 1

                emotion = meta.get("emotion", "unknown")
                by_emotion[emotion] = by_emotion.get(emotion, 0) + 1

                origin = meta.get("data_origin", "unknown")
                by_origin[origin] = by_origin.get(origin, 0) + 1

        return StyleRAGStats(
            total_samples=total,
            by_character=by_character,
            by_emotion=by_emotion,
            by_origin=by_origin
        )

    def export_samples(
        self,
        output_path: str,
        character_id: Optional[str] = None
    ) -> None:
        """サンプルをYAML形式でエクスポート"""
        where_clause = None
        if character_id:
            where_clause = {"character_id": character_id}

        all_data = self.collection.get(
            include=["metadatas"],
            where=where_clause
        )

        # キャラクターごとにグループ化
        by_character: Dict[str, List[Dict]] = {}
        for meta in all_data['metadatas']:
            char = meta.get("character_id", "unknown")
            if char not in by_character:
                by_character[char] = []

            by_character[char].append({
                "id": meta.get("sample_id", ""),
                "emotion": meta.get("emotion", ""),
                "situation": meta.get("situation", ""),
                "example": meta.get("example", ""),
                "data_origin": meta.get("data_origin", "")
            })

        # 各キャラクターのファイルを出力
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        for char, samples in by_character.items():
            output_file = output_dir / f"{char}.yaml"
            with open(output_file, 'w', encoding='utf-8') as f:
                yaml.dump(
                    {"character_id": char, "samples": samples},
                    f,
                    allow_unicode=True,
                    default_flow_style=False
                )


# シングルトンインスタンス
_style_rag: Optional[StyleRAG] = None


def get_style_rag() -> StyleRAG:
    """シングルトンインスタンスを取得"""
    global _style_rag
    if _style_rag is None:
        _style_rag = StyleRAG()
    return _style_rag


def reset_style_rag() -> None:
    """シングルトンをリセット（テスト用）"""
    global _style_rag
    _style_rag = None
