"""
Reflection Engine

会話終了時（または一定ターンごと）に、重要な情報を抽出・要約して
Memory RAGに保存する。

設計原則:
- LLMを使った高品質な要約
- エピソード記憶と事実記憶の自動分類
- バックグラウンド実行対応
"""

import json
import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from enum import Enum

from src.memory_rag import (
    get_memory_rag,
    MemoryRAG,
    FactCategory,
    EpisodeMemory,
    FactMemory
)


@dataclass
class DialogueEntry:
    """対話エントリ"""
    speaker: str  # "yana", "ayu", "user"
    content: str
    timestamp: str


@dataclass
class ExtractedEpisode:
    """抽出されたエピソード"""
    summary: str
    importance: float
    emotional_tag: str
    yana_perspective: Optional[str] = None
    ayu_perspective: Optional[str] = None


@dataclass
class ExtractedFact:
    """抽出された事実"""
    summary: str
    category: str  # "preference", "experience", "info"
    confidence: float = 1.0


@dataclass
class ReflectionResult:
    """Reflection結果"""
    episodes_extracted: int
    facts_extracted: int
    episodes_saved: int
    facts_saved: int
    raw_extraction: Optional[Dict[str, Any]] = None


# 抽出プロンプトテンプレート
EXTRACTION_PROMPT = """以下の会話から、重要な情報を2種類に分けて抽出してください。

## 会話履歴
{conversation_history}

## 抽出する情報

### エピソード記憶（出来事）
- 何か特別なことが起きた？
- 感情的に印象的だった瞬間は？
- 関係性の変化はあった？
- 成功や失敗の体験は？

### 事実記憶（ユーザー情報）
- ユーザーの好み・趣味
- ユーザーの経験・背景
- ユーザーが共有した情報

## 重要度の基準
- 0.9-1.0: 非常に重要（関係性の大きな変化、感動的な瞬間）
- 0.7-0.8: 重要（成功/失敗体験、新しい発見）
- 0.5-0.6: やや重要（日常的だが記憶に値する）
- 0.3-0.4: あまり重要でない（ルーティン的な会話）

## 出力フォーマット（JSONで出力）
```json
{{
  "episodes": [
    {{
      "summary": "何が起きたかの簡潔な説明",
      "importance": 0.8,
      "emotional_tag": "success|failure|discovery|disagreement|bonding|routine"
    }}
  ],
  "facts": [
    {{
      "summary": "ユーザーについての事実",
      "category": "preference|experience|info",
      "confidence": 1.0
    }}
  ]
}}
```

重要でない会話の場合は、episodesとfactsを空配列にしてください。
感情タグは会話の文脈から最も適切なものを選んでください。
"""

# 視点生成プロンプト
PERSPECTIVE_PROMPT = """以下のエピソードについて、やなとあゆそれぞれの視点での短いコメントを生成してください。

エピソード: {episode_summary}

やなの性格:
- カジュアルで元気
- 「〜じゃん」「〜だよね」などの語尾
- 直感的、行動派

あゆの性格:
- 丁寧で論理的
- 「〜ですね」「〜でしょうか」などの語尾
- データ重視、姉様と呼ぶ

## 出力フォーマット（JSONで出力）
```json
{{
  "yana_perspective": "やなの視点での短いコメント（20文字程度）",
  "ayu_perspective": "あゆの視点での短いコメント（20文字程度）"
}}
```
"""


class ReflectionEngine:
    """Reflection Engine"""

    def __init__(
        self,
        memory_rag: Optional[MemoryRAG] = None,
        llm_generate: Optional[Callable[[str], str]] = None,
        min_turns_for_reflection: int = 5
    ):
        """
        Args:
            memory_rag: Memory RAGインスタンス（Noneならシングルトンを使用）
            llm_generate: LLM生成関数（プロンプト -> レスポンス）
            min_turns_for_reflection: Reflectionを行う最小ターン数
        """
        self.memory_rag = memory_rag or get_memory_rag()
        self.llm_generate = llm_generate
        self.min_turns = min_turns_for_reflection

    def process_conversation(
        self,
        history: List[Dict[str, str]],
        generate_perspectives: bool = True
    ) -> ReflectionResult:
        """
        会話履歴を処理してMemory RAGに保存

        Args:
            history: 会話履歴 [{"speaker": "...", "content": "...", "timestamp": "..."}]
            generate_perspectives: 視点生成を行うか

        Returns:
            Reflection結果
        """
        if len(history) < self.min_turns:
            return ReflectionResult(
                episodes_extracted=0,
                facts_extracted=0,
                episodes_saved=0,
                facts_saved=0
            )

        # 会話履歴をテキスト化
        conversation_text = self._format_history(history)

        # LLMによる抽出
        extraction = self._extract_memories(conversation_text)

        if not extraction:
            return ReflectionResult(
                episodes_extracted=0,
                facts_extracted=0,
                episodes_saved=0,
                facts_saved=0
            )

        episodes = extraction.get("episodes", [])
        facts = extraction.get("facts", [])

        # エピソードの保存
        episodes_saved = 0
        for ep_data in episodes:
            ep = self._parse_episode(ep_data)
            if ep:
                # 視点生成
                if generate_perspectives and self.llm_generate:
                    perspectives = self._generate_perspectives(ep.summary)
                    if perspectives:
                        ep.yana_perspective = perspectives.get("yana_perspective", "")
                        ep.ayu_perspective = perspectives.get("ayu_perspective", "")

                # デフォルト視点
                if not ep.yana_perspective:
                    ep.yana_perspective = self._default_yana_perspective(ep)
                if not ep.ayu_perspective:
                    ep.ayu_perspective = self._default_ayu_perspective(ep)

                # 保存
                memory_id = self.memory_rag.add_episode_direct(
                    summary=ep.summary,
                    yana_perspective=ep.yana_perspective,
                    ayu_perspective=ep.ayu_perspective,
                    emotional_tag=ep.emotional_tag,
                    importance=ep.importance,
                    context_tags=[ep.emotional_tag]
                )
                if memory_id:
                    episodes_saved += 1

        # 事実の保存
        facts_saved = 0
        for fact_data in facts:
            fact = self._parse_fact(fact_data)
            if fact:
                memory_id = self.memory_rag.add_fact_direct(
                    summary=fact.summary,
                    category=FactCategory(fact.category),
                    confidence=fact.confidence
                )
                if memory_id:
                    facts_saved += 1

        return ReflectionResult(
            episodes_extracted=len(episodes),
            facts_extracted=len(facts),
            episodes_saved=episodes_saved,
            facts_saved=facts_saved,
            raw_extraction=extraction
        )

    def _format_history(self, history: List[Dict[str, str]]) -> str:
        """会話履歴をテキスト化"""
        lines = []
        for entry in history:
            speaker = entry.get("speaker", "unknown")
            content = entry.get("content", "")

            # キャラクター名の変換
            speaker_name = {
                "yana": "やな",
                "ayu": "あゆ",
                "user": "ユーザー"
            }.get(speaker, speaker)

            lines.append(f"{speaker_name}: {content}")

        return "\n".join(lines)

    def _extract_memories(
        self,
        conversation_text: str
    ) -> Optional[Dict[str, Any]]:
        """LLMで記憶を抽出"""
        if not self.llm_generate:
            # LLMがない場合はルールベースで抽出
            return self._rule_based_extraction(conversation_text)

        prompt = EXTRACTION_PROMPT.format(
            conversation_history=conversation_text
        )

        try:
            response = self.llm_generate(prompt)
            return self._parse_json_response(response)
        except Exception as e:
            print(f"Reflection extraction error: {e}")
            return None

    def _rule_based_extraction(
        self,
        conversation_text: str
    ) -> Dict[str, Any]:
        """ルールベースの抽出（LLMなしのフォールバック）"""
        episodes = []
        facts = []

        # 成功パターン
        success_patterns = ["成功", "やった", "できた", "うまくいった"]
        for pattern in success_patterns:
            if pattern in conversation_text:
                episodes.append({
                    "summary": f"{pattern}という体験があった",
                    "importance": 0.7,
                    "emotional_tag": "success"
                })
                break

        # 失敗パターン
        failure_patterns = ["失敗", "ダメ", "うまくいかない"]
        for pattern in failure_patterns:
            if pattern in conversation_text:
                episodes.append({
                    "summary": f"うまくいかないことがあった",
                    "importance": 0.6,
                    "emotional_tag": "failure"
                })
                break

        # 好みパターン
        preference_patterns = ["好き", "嫌い", "得意", "苦手"]
        for pattern in preference_patterns:
            if pattern in conversation_text:
                # 簡易抽出
                facts.append({
                    "summary": f"ユーザーの好みに関する情報がある",
                    "category": "preference",
                    "confidence": 0.6
                })
                break

        return {"episodes": episodes, "facts": facts}

    def _generate_perspectives(
        self,
        episode_summary: str
    ) -> Optional[Dict[str, str]]:
        """LLMで視点を生成"""
        if not self.llm_generate:
            return None

        prompt = PERSPECTIVE_PROMPT.format(episode_summary=episode_summary)

        try:
            response = self.llm_generate(prompt)
            return self._parse_json_response(response)
        except Exception as e:
            print(f"Perspective generation error: {e}")
            return None

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """LLMレスポンスからJSONを抽出"""
        # JSONブロックを探す
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # JSONブロックがない場合は全体をパース試行
            json_str = response

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 複数行のJSONを探す
            try:
                start = response.find('{')
                end = response.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(response[start:end])
            except:
                pass
            return None

    def _parse_episode(self, data: Dict[str, Any]) -> Optional[ExtractedEpisode]:
        """エピソードデータをパース"""
        summary = data.get("summary", "").strip()
        if not summary:
            return None

        return ExtractedEpisode(
            summary=summary,
            importance=float(data.get("importance", 0.5)),
            emotional_tag=data.get("emotional_tag", "routine")
        )

    def _parse_fact(self, data: Dict[str, Any]) -> Optional[ExtractedFact]:
        """事実データをパース"""
        summary = data.get("summary", "").strip()
        if not summary:
            return None

        category = data.get("category", "info")
        if category not in ["preference", "experience", "info"]:
            category = "info"

        return ExtractedFact(
            summary=summary,
            category=category,
            confidence=float(data.get("confidence", 1.0))
        )

    def _default_yana_perspective(self, ep: ExtractedEpisode) -> str:
        """やなのデフォルト視点"""
        templates = {
            "success": "やった！うまくいった",
            "failure": "ちょっと失敗しちゃった...",
            "discovery": "面白いもの見つけた！",
            "disagreement": "あゆと意見が分かれた",
            "bonding": "いい感じだった！",
            "routine": "普通にやってた"
        }
        return templates.get(ep.emotional_tag, "そんなことあったね")

    def _default_ayu_perspective(self, ep: ExtractedEpisode) -> str:
        """あゆのデフォルト視点"""
        templates = {
            "success": "良い結果でしたね",
            "failure": "改善点が見つかりました",
            "discovery": "興味深い発見でした",
            "disagreement": "姉様と見解が異なりました",
            "bonding": "良い時間でした",
            "routine": "通常の対話でした"
        }
        return templates.get(ep.emotional_tag, "記録しておきます")


# シングルトンインスタンス
_reflection_engine: Optional[ReflectionEngine] = None


def get_reflection_engine() -> ReflectionEngine:
    """シングルトンインスタンスを取得"""
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine()
    return _reflection_engine


def reset_reflection_engine() -> None:
    """シングルトンをリセット（テスト用）"""
    global _reflection_engine
    _reflection_engine = None


def configure_reflection_engine(
    llm_generate: Optional[Callable[[str], str]] = None,
    min_turns: int = 5
) -> ReflectionEngine:
    """Reflection Engineを設定して取得"""
    global _reflection_engine
    _reflection_engine = ReflectionEngine(
        llm_generate=llm_generate,
        min_turns_for_reflection=min_turns
    )
    return _reflection_engine
