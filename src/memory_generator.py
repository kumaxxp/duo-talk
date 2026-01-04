"""
記憶自動生成システム（シンプル版）

対話履歴から重要なイベントを検出し、
姉妹それぞれの視点で記憶を生成する。

設計原則:
- ルールベースで軽量
- 走行中に呼び出し可能
- LLM不要（オプションで後から追加）
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from src.sister_memory import get_sister_memory


@dataclass
class DialogueTurn:
    """対話ターン"""
    speaker: str  # "yana" or "ayu"
    content: str
    timestamp: str


@dataclass
class DetectedEvent:
    """検出されたイベント"""
    event_type: str  # "success", "failure", "discovery", "disagreement", "routine"
    trigger_text: str
    speaker: str
    confidence: float


# イベント検出パターン
EVENT_PATTERNS = {
    "success": {
        "keywords": ["やった", "成功", "完璧", "うまく", "いい感じ", "できた", "クリア"],
        "weight": 1.0
    },
    "failure": {
        "keywords": ["失敗", "ダメ", "ミス", "やばい", "まずい", "ぶつか", "はみ出"],
        "weight": 1.0
    },
    "discovery": {
        "keywords": ["あ、", "あっ", "見て", "なんか", "おっ", "へぇ"],
        "weight": 0.8
    },
    "disagreement": {
        "keywords": ["でも", "違う", "いや", "そうかな", "本当に？", "ちょっと待"],
        "weight": 0.7
    },
    "analysis": {
        "keywords": ["データ", "計算", "分析", "%", "m/s", "秒"],
        "weight": 0.6
    }
}

# 感情タグマッピング
EMOTION_TAG_MAP = {
    ("success", "yana"): "success_yana",
    ("success", "ayu"): "success_ayu",
    ("success", "both"): "success_shared",
    ("failure", "yana"): "failure_learning",
    ("failure", "ayu"): "failure_learning",
    ("failure", "both"): "failure_learning",
    ("discovery", "yana"): "surprise",
    ("discovery", "ayu"): "surprise",
    ("disagreement", "both"): "disagreement",
    ("analysis", "ayu"): "routine",
}

# 視点生成テンプレート
PERSPECTIVE_TEMPLATES = {
    "success": {
        "yana": "うまくいった！{detail}",
        "ayu": "成功です。{detail}"
    },
    "failure": {
        "yana": "ちょっと失敗しちゃった...{detail}",
        "ayu": "改善点が見つかりました。{detail}"
    },
    "discovery": {
        "yana": "面白いもの見つけた！{detail}",
        "ayu": "興味深い発見です。{detail}"
    },
    "disagreement": {
        "yana": "あゆと意見が分かれたけど{detail}",
        "ayu": "姉様と見解が異なりましたが{detail}"
    },
    "analysis": {
        "yana": "あゆが色々分析してた。{detail}",
        "ayu": "データを分析しました。{detail}"
    },
    "routine": {
        "yana": "普通に走ってた。{detail}",
        "ayu": "通常の走行でした。{detail}"
    }
}


class MemoryGenerator:
    """記憶自動生成（シンプル版）"""

    def __init__(
        self,
        min_turns_for_memory: int = 4,
        min_confidence: float = 0.5
    ):
        """
        Args:
            min_turns_for_memory: 記憶生成に必要な最小ターン数
            min_confidence: イベント検出の最小確信度
        """
        self.min_turns = min_turns_for_memory
        self.min_confidence = min_confidence
        self.sister_memory = get_sister_memory()

    def process_dialogue(
        self,
        history: List[Dict[str, str]],
        run_id: Optional[str] = None,
        context_tags: Optional[List[str]] = None
    ) -> List[str]:
        """
        対話履歴を処理して記憶をバッファに追加

        Args:
            history: 対話履歴 [{"speaker": "yana", "content": "...", "timestamp": "..."}]
            run_id: 走行ID
            context_tags: 追加のコンテキストタグ

        Returns:
            生成された記憶のevent_idリスト
        """
        if len(history) < self.min_turns:
            return []

        context_tags = context_tags or []
        generated_ids = []

        # 対話をチャンクに分割（4ターンごと）
        chunks = self._split_into_chunks(history, chunk_size=4)

        for chunk_idx, chunk in enumerate(chunks):
            # イベント検出
            events = self._detect_events(chunk)

            if not events:
                continue

            # 最も重要なイベントを選択
            primary_event = max(events, key=lambda e: e.confidence)

            if primary_event.confidence < self.min_confidence:
                continue

            # サマリー生成
            summary = self._generate_summary(chunk, primary_event)

            # 視点生成
            yana_perspective = self._generate_perspective(
                chunk, primary_event, "yana"
            )
            ayu_perspective = self._generate_perspective(
                chunk, primary_event, "ayu"
            )

            # 感情タグ判定
            emotional_tag = self._determine_emotion_tag(chunk, primary_event)

            # バッファに追加
            event_id = self.sister_memory.buffer_event(
                event_summary=summary,
                yana_perspective=yana_perspective,
                ayu_perspective=ayu_perspective,
                emotional_tag=emotional_tag,
                context_tags=context_tags + [primary_event.event_type],
                run_id=run_id,
                turn_number=chunk_idx * 4
            )

            generated_ids.append(event_id)

        return generated_ids

    def _split_into_chunks(
        self,
        history: List[Dict[str, str]],
        chunk_size: int = 4
    ) -> List[List[DialogueTurn]]:
        """対話履歴をチャンクに分割"""
        chunks = []
        current_chunk = []

        for h in history:
            turn = DialogueTurn(
                speaker=h.get("speaker", "unknown"),
                content=h.get("content", ""),
                timestamp=h.get("timestamp", "")
            )
            current_chunk.append(turn)

            if len(current_chunk) >= chunk_size:
                chunks.append(current_chunk)
                current_chunk = []

        # 残りがあれば追加
        if current_chunk and len(current_chunk) >= 2:
            chunks.append(current_chunk)

        return chunks

    def _detect_events(
        self,
        chunk: List[DialogueTurn]
    ) -> List[DetectedEvent]:
        """チャンクからイベントを検出"""
        events = []

        for turn in chunk:
            for event_type, config in EVENT_PATTERNS.items():
                for keyword in config["keywords"]:
                    if keyword in turn.content:
                        events.append(DetectedEvent(
                            event_type=event_type,
                            trigger_text=keyword,
                            speaker=turn.speaker,
                            confidence=config["weight"]
                        ))
                        break  # 同じタイプの複数検出を避ける

        return events

    def _generate_summary(
        self,
        chunk: List[DialogueTurn],
        event: DetectedEvent
    ) -> str:
        """イベントのサマリーを生成"""
        # トリガーテキストを含むターンを見つける
        trigger_turn = None
        for turn in chunk:
            if event.trigger_text in turn.content:
                trigger_turn = turn
                break

        if trigger_turn:
            # コンテンツから短いサマリーを抽出
            content = trigger_turn.content
            # 50文字以内に収める
            if len(content) > 50:
                content = content[:47] + "..."
            return f"{event.event_type}: {content}"

        return f"{event.event_type}イベントが発生"

    def _generate_perspective(
        self,
        chunk: List[DialogueTurn],
        event: DetectedEvent,
        character: str
    ) -> str:
        """キャラクター視点を生成"""
        templates = PERSPECTIVE_TEMPLATES.get(
            event.event_type,
            PERSPECTIVE_TEMPLATES["routine"]
        )
        template = templates.get(character, templates.get("yana", "{detail}"))

        # 該当キャラクターの発言から詳細を抽出
        detail = ""
        for turn in chunk:
            if turn.speaker == character:
                # 最初の20文字を使用
                detail = turn.content[:20] + "..." if len(turn.content) > 20 else turn.content
                break

        if not detail:
            detail = "（特になし）"

        return template.format(detail=detail)

    def _determine_emotion_tag(
        self,
        chunk: List[DialogueTurn],
        event: DetectedEvent
    ) -> str:
        """感情タグを判定"""
        # 両方のキャラクターが関与しているか確認
        speakers = set(turn.speaker for turn in chunk)
        involvement = "both" if len(speakers) > 1 else event.speaker

        # マッピングから取得
        key = (event.event_type, involvement)
        return EMOTION_TAG_MAP.get(key, "routine")

    def flush_memories(self, validate: bool = True) -> Dict[str, int]:
        """
        バッファの記憶をDBに書き込み

        Args:
            validate: バリデーションを行うか

        Returns:
            書き込み結果 {"written": N, "skipped": N}
        """
        result = self.sister_memory.flush_buffer(validate)
        return {
            "total": result.total,
            "written": result.written,
            "skipped": result.skipped,
            "skipped_reasons": result.skipped_reasons
        }

    def get_buffer_size(self) -> int:
        """現在のバッファサイズを取得"""
        return self.sister_memory.get_buffer_size()


# シングルトン
_memory_generator: Optional[MemoryGenerator] = None


def get_memory_generator() -> MemoryGenerator:
    """シングルトンインスタンスを取得"""
    global _memory_generator
    if _memory_generator is None:
        _memory_generator = MemoryGenerator()
    return _memory_generator


def reset_memory_generator() -> None:
    """シングルトンをリセット（テスト用）"""
    global _memory_generator
    _memory_generator = None
