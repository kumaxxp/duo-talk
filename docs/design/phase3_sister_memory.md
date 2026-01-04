# Phase 3: 姉妹記憶システム設計書

## 1. 概要

### 1.1 目的
やなとあゆが過去の体験を「姉妹それぞれの視点」で記憶し、会話に自然に反映させるシステム。

### 1.2 設計原則（ChatGPT/Geminiフィードバック反映）

| 原則 | 内容 | 理由 |
|------|------|------|
| 読み出し優先 | 走行中は検索のみ | レイテンシ確保 |
| バッチ書き込み | 終了後にまとめて保存 | I/O負荷軽減 |
| キャラ崩壊防止 | 保存前フィルタ必須 | 「やなはデータ重視」等の逆転防止 |
| 視点分離 | 同じ出来事を別視点で保存 | duo-talk独自の発明 |

---

## 2. アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────┐
│                    SisterMemory システム                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                    Memory Entry                           │ │
│  │  ┌─────────────┬─────────────┬─────────────────────────┐ │ │
│  │  │   event_id  │  timestamp  │  event_summary          │ │ │
│  │  │  (UUID)     │  (ISO8601)  │  "カーブでスピン発生"   │ │ │
│  │  ├─────────────┴─────────────┴─────────────────────────┤ │ │
│  │  │                                                     │ │ │
│  │  │  yana_perspective:                                  │ │ │
│  │  │    "やっぱり攻めすぎたかな...でも限界知れてよかった" │ │ │
│  │  │                                                     │ │ │
│  │  │  ayu_perspective:                                   │ │ │
│  │  │    "姉様の進入速度は推奨値を15%超過していました"    │ │ │
│  │  │                                                     │ │ │
│  │  │  emotional_tag: "failure_learning"                  │ │ │
│  │  │  context_tags: ["curve", "speed", "spin"]           │ │ │
│  │  └─────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────┘ │
│                              │                                  │
│                              ▼                                  │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                      ChromaDB                             │ │
│  │  ┌─────────────────┐  ┌─────────────────────────────────┐│ │
│  │  │ sister_memories │  │ Embedding: sentence-transformers ││ │
│  │  │ (collection)    │  │ Model: paraphrase-multilingual   ││ │
│  │  └─────────────────┘  └─────────────────────────────────┘│ │
│  └───────────────────────────────────────────────────────────┘ │
│                              │                                  │
│         ┌────────────────────┼────────────────────┐            │
│         ▼                    ▼                    ▼            │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐      │
│  │   Search    │     │   Buffer    │     │   Flush     │      │
│  │  (走行中)   │     │  (蓄積)     │     │ (終了後)    │      │
│  │             │     │             │     │             │      │
│  │ query →     │     │ memory →    │     │ filter →    │      │
│  │ top-k結果   │     │ list追加    │     │ DB書込み    │      │
│  └─────────────┘     └─────────────┘     └─────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. データモデル

### 3.1 MemoryEntry

```python
@dataclass
class MemoryEntry:
    """記憶エントリ"""
    event_id: str                    # UUID
    timestamp: str                   # ISO8601
    event_summary: str               # 出来事の客観的要約
    yana_perspective: str            # やな視点の解釈
    ayu_perspective: str             # あゆ視点の解釈
    emotional_tag: str               # 感情タグ
    context_tags: List[str]          # コンテキストタグ
    run_id: Optional[str] = None     # 関連するrun_id
    turn_number: Optional[int] = None  # 発生ターン
```

### 3.2 感情タグ一覧

| タグ | 説明 | やな視点の傾向 | あゆ視点の傾向 |
|------|------|---------------|---------------|
| `success_shared` | 共有の成功 | 「やったね！」 | 「計画通りです」 |
| `success_yana` | やなの手柄 | 「私の勘が当たった」 | 「結果的に成功しました」 |
| `success_ayu` | あゆの手柄 | 「あゆの計算すごい」 | 「予測が正確でした」 |
| `failure_learning` | 失敗からの学び | 「次は気をつける」 | 「データを記録しました」 |
| `disagreement` | 意見の相違 | 「でも私はこう思う」 | 「データはこう示しています」 |
| `surprise` | 予想外の出来事 | 「え、マジで！？」 | 「想定外でした」 |
| `routine` | 日常的な出来事 | 「いつもの感じ」 | 「標準的な結果です」 |

### 3.3 コンテキストタグ

```yaml
# 走行関連
driving:
  - curve, straight, corner
  - speed, throttle, steering
  - obstacle, collision, near_miss
  - success, failure, recovery

# センサー関連
sensor:
  - distance, temperature
  - vision, road_percentage
  - anomaly, normal

# 感情関連
emotion:
  - excited, nervous, calm
  - proud, frustrated, curious
```

---

## 4. クラス設計

### 4.1 SisterMemory

```python
class SisterMemory:
    """姉妹視点の記憶システム"""
    
    def __init__(
        self,
        db_path: str = "./memories/sister_memory.db",
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    ):
        """
        Args:
            db_path: ChromaDB保存パス
            embedding_model: sentence-transformersモデル名
        """
        pass
    
    # === 検索（走行中使用） ===
    def search(
        self,
        query: str,
        character: str,  # "yana" or "ayu"
        n_results: int = 3,
        filters: Optional[Dict] = None
    ) -> List[MemoryResult]:
        """
        関連する記憶を検索
        
        Args:
            query: 検索クエリ（現在の状況や話題）
            character: 視点を取得するキャラクター
            n_results: 取得件数
            filters: 追加フィルタ（emotional_tag, context_tags等）
        
        Returns:
            キャラクター視点でフォーマットされた記憶リスト
        """
        pass
    
    def search_by_tags(
        self,
        tags: List[str],
        character: str,
        n_results: int = 3
    ) -> List[MemoryResult]:
        """タグベースの検索"""
        pass
    
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
        pass
    
    def get_buffer_size(self) -> int:
        """現在のバッファサイズを取得"""
        pass
    
    # === フラッシュ（走行終了後使用） ===
    def flush_buffer(
        self,
        validate: bool = True
    ) -> FlushResult:
        """
        バッファの記憶をDBに書き込み
        
        Args:
            validate: キャラ崩壊フィルタを適用するか
        
        Returns:
            書き込み結果（成功数、スキップ数、エラー）
        """
        pass
    
    def clear_buffer(self) -> None:
        """バッファをクリア（書き込みせず破棄）"""
        pass
    
    # === 管理 ===
    def get_stats(self) -> MemoryStats:
        """統計情報を取得"""
        pass
    
    def export_memories(
        self,
        output_path: str,
        format: str = "json"
    ) -> None:
        """記憶をエクスポート"""
        pass
```

### 4.2 MemoryResult

```python
@dataclass
class MemoryResult:
    """検索結果"""
    event_id: str
    summary: str              # 出来事の要約
    perspective: str          # 指定キャラの視点
    emotional_tag: str
    relevance_score: float    # 類似度スコア (0.0-1.0)
    timestamp: str
    
    def to_prompt_text(self) -> str:
        """プロンプト注入用テキストに変換"""
        return f"【過去の記憶】{self.summary}（{self.perspective}）"
```

### 4.3 FlushResult

```python
@dataclass
class FlushResult:
    """フラッシュ結果"""
    total: int
    written: int
    skipped: int
    errors: List[str]
    skipped_reasons: Dict[str, int]  # スキップ理由ごとのカウント
```

---

## 5. キャラ崩壊防止フィルタ

### 5.1 フィルタルール

```python
class MemoryValidator:
    """記憶の妥当性検証"""
    
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
    
    def validate(self, memory: MemoryEntry) -> ValidationResult:
        """記憶を検証"""
        pass
```

### 5.2 検証フロー

```
記憶エントリ
    │
    ▼
┌─────────────────────┐
│ 1. やな視点チェック  │
│    YANA_FORBIDDEN   │
└─────────────────────┘
    │ NG → スキップ（理由: yana_character_violation）
    ▼ OK
┌─────────────────────┐
│ 2. あゆ視点チェック  │
│    AYU_FORBIDDEN    │
└─────────────────────┘
    │ NG → スキップ（理由: ayu_character_violation）
    ▼ OK
┌─────────────────────┐
│ 3. 関係性チェック    │
│  RELATIONSHIP_FORBIDDEN │
└─────────────────────┘
    │ NG → スキップ（理由: relationship_violation）
    ▼ OK
┌─────────────────────┐
│ 4. 重複チェック      │
│  類似度 > 0.95 ?    │
└─────────────────────┘
    │ NG → スキップ（理由: duplicate）
    ▼ OK
DBに書き込み
```

---

## 6. プロンプト統合

### 6.1 Injection優先度

```python
# src/injection.py に追加

PRIORITY_SISTER_MEMORY = 35  # PRIORITY_LONG_MEMORY(30) と PRIORITY_RAG(40) の間
```

### 6.2 Character統合

```python
# src/character.py の speak_v2() に統合

def speak_v2(self, ...):
    # 記憶検索
    memories = self.sister_memory.search(
        query=frame_description,
        character=self.internal_id.replace("char_", ""),
        n_results=2
    )
    
    # プロンプトビルダーに追加
    if memories:
        memory_text = "\n".join([m.to_prompt_text() for m in memories])
        builder.add(
            f"【関連する過去の記憶】\n{memory_text}",
            priority=PRIORITY_SISTER_MEMORY,
            source="sister_memory"
        )
```

---

## 7. 記憶生成タイミング

### 7.1 自動生成トリガー

| トリガー | 説明 | emotional_tag |
|---------|------|---------------|
| 走行成功 | 難しいセクションをクリア | `success_*` |
| 走行失敗 | スピン、衝突、コースアウト | `failure_learning` |
| ループ検知 | NoveltyGuardがループ検知 | `routine` |
| 意見対立 | やな/あゆの主張が対立 | `disagreement` |
| 予想外イベント | センサー異常、予測外れ | `surprise` |

### 7.2 生成フロー

```python
class MemoryGenerator:
    """記憶を自動生成"""
    
    def generate_from_dialogue(
        self,
        yana_utterance: str,
        ayu_utterance: str,
        context: Dict,
        llm_client: LlmClient
    ) -> Optional[MemoryEntry]:
        """
        対話から記憶を生成
        
        LLMを使って:
        1. 出来事の要約を生成
        2. やな視点を生成
        3. あゆ視点を生成
        4. 感情タグを判定
        """
        pass
```

---

## 8. API エンドポイント

### 8.1 新規エンドポイント

```
GET  /api/v2/memory/search
     ?query=カーブ&character=yana&n=3
     → 関連記憶を検索

GET  /api/v2/memory/stats
     → 統計情報（総記憶数、タグ分布等）

POST /api/v2/memory/buffer
     {event_summary, yana_perspective, ayu_perspective, ...}
     → 記憶をバッファに追加

POST /api/v2/memory/flush
     → バッファをDBに書き込み

GET  /api/v2/memory/buffer/size
     → 現在のバッファサイズ

DELETE /api/v2/memory/buffer
     → バッファをクリア
```

---

## 9. 設定ファイル

### 9.1 config/memory_settings.yaml

```yaml
sister_memory:
  # DB設定
  db_path: "./memories/sister_memory.db"
  embedding_model: "paraphrase-multilingual-MiniLM-L12-v2"
  
  # 検索設定
  default_n_results: 3
  min_relevance_score: 0.5
  
  # バッファ設定
  max_buffer_size: 100
  auto_flush_threshold: 50
  
  # フィルタ設定
  enable_validation: true
  duplicate_threshold: 0.95
  
  # 生成設定
  auto_generate:
    on_success: true
    on_failure: true
    on_loop_detected: false
    on_disagreement: true
```

---

## 10. テスト計画

### 10.1 ユニットテスト

```python
# tests/test_sister_memory.py

class TestSisterMemory:
    def test_search_returns_correct_perspective(self):
        """キャラクター別視点が正しく返されるか"""
        pass
    
    def test_buffer_and_flush(self):
        """バッファリングとフラッシュが正常に動作するか"""
        pass
    
    def test_validation_rejects_character_violation(self):
        """キャラ崩壊フィルタが機能するか"""
        pass
    
    def test_duplicate_detection(self):
        """重複検出が機能するか"""
        pass

class TestMemoryGenerator:
    def test_generate_from_dialogue(self):
        """対話から記憶が正しく生成されるか"""
        pass
    
    def test_emotional_tag_detection(self):
        """感情タグが正しく判定されるか"""
        pass
```

### 10.2 統合テスト

```python
# tests/test_memory_integration.py

class TestMemoryIntegration:
    def test_speak_v2_with_memory(self):
        """speak_v2で記憶が正しく注入されるか"""
        pass
    
    def test_memory_affects_dialogue(self):
        """記憶が対話内容に影響を与えるか"""
        pass
```

---

## 11. 実装優先順位

| 順序 | 内容 | 依存 |
|------|------|------|
| 1 | SisterMemory基本クラス | なし |
| 2 | MemoryValidator | 1 |
| 3 | Character統合 | 1, 2 |
| 4 | MemoryGenerator | 1 |
| 5 | APIエンドポイント | 1-4 |
| 6 | GUI統合 | 5 |
