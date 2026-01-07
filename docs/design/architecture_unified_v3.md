# duo-talk v3.0 アーキテクチャ統一 完了報告

**作成日**: 2026年1月7日  
**対象**: duo-talk プロジェクト  
**ステータス**: Phase 1-4 完了

---

## 1. 概要

### 1.1 目的

Console/RUNS/LIVE の3つの実行パスを `UnifiedPipeline` に統一し、コードの重複を排除、メンテナンス性を向上させる。

### 1.2 達成内容

| Phase | 内容 | 状態 |
|-------|------|------|
| **Phase 1** | speak()/speak_v2() 非推奨化 | ✅ 完了 |
| **Phase 2** | UnifiedPipeline.run_continuous() 追加 | ✅ 完了 |
| **Phase 3** | run_jetracer_live.py 移行 | ✅ 完了 |
| **Phase 4** | run_commentary.py 移行 | ✅ 完了 |

---

## 2. 新アーキテクチャ

### 2.1 実行パス統一図

```
                    Entry Points
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   Console          GUI/API           LIVE
   (run_commentary) (api_unified)  (run_jetracer_live)
        │                │                │
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   UnifiedPipeline    │
              │                      │
              │  ├─ run()            │ ← バッチ実行
              │  └─ run_continuous() │ ← 連続実行
              │                      │
              │  内部統合:           │
              │  - Director          │
              │  - NoveltyGuard      │
              │  - InputCollector    │
              │  - Logger            │
              └──────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │      Character       │
              │                      │
              │  └─ speak_unified()  │ ← 唯一の推奨メソッド
              │                      │
              │  [DEPRECATED]        │
              │  ├─ speak()          │
              │  └─ speak_v2()       │
              └──────────────────────┘
```

### 2.2 メソッド対応表

| 旧メソッド | 新メソッド | 用途 |
|------------|------------|------|
| `Character.speak()` | `Character.speak_unified()` | 発話生成 |
| `Character.speak_v2()` | `Character.speak_unified()` | 発話生成 |
| `Character.speak_with_history()` | `Character.speak_unified()` | 履歴付き発話生成 |
| 独自ループ | `UnifiedPipeline.run()` | バッチ対話生成 |
| 独自ループ | `UnifiedPipeline.run_continuous()` | 連続実行（LIVE用） |

---

## 3. API リファレンス

### 3.1 UnifiedPipeline

```python
from src.unified_pipeline import UnifiedPipeline
from src.input_source import InputBundle, InputSource, SourceType

# 初期化
pipeline = UnifiedPipeline(
    jetracer_client=None,       # JetRacerClient（オプション）
    enable_fact_check=True,     # Director事実チェック
    jetracer_mode=None,         # None=自動判定, True/False=強制
)

# バッチ実行
result = pipeline.run(
    initial_input=InputBundle(...),
    max_turns=8,
    run_id=None,                # 省略時は自動生成
    interrupt_callback=None,    # 割り込み入力コールバック
    event_callback=None,        # イベント通知コールバック
)

# 連続実行（LIVE用）
result = pipeline.run_continuous(
    input_generator=lambda: InputBundle(...),  # 入力生成コールバック
    max_frames=None,            # 最大フレーム数
    frame_interval=3.0,         # フレーム間隔（秒）
    turns_per_frame=4,          # フレームあたりターン数
    run_id=None,
    event_callback=None,
    stop_callback=None,         # 停止判定コールバック
)
```

### 3.2 Character.speak_unified()

```python
from src.character import Character

char = Character("A", jetracer_mode=False)

response = char.speak_unified(
    frame_description="状況説明",
    conversation_history=[("B", "前の発言")],  # [(speaker, text), ...]
    director_instruction=None,   # Directorからの指示
    vision_info=None,            # 視覚情報テキスト
    topic_guidance=None,         # Topic Manager情報
    owner_instruction=None,      # オーナー介入指示
)
```

### 3.3 DialogueResult

```python
@dataclass
class DialogueResult:
    run_id: str
    dialogue: List[DialogueTurn]  # 対話ターンのリスト
    status: str                   # "success", "paused", "error"
    frame_context: Optional[FrameContext]
    error: Optional[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]: ...
    def get_dialogue_text(self) -> str: ...
```

---

## 4. 使用例

### 4.1 コマンドライン実行（Console）

```bash
# 一般会話モード
python scripts/run_commentary.py "今日の天気について" --turns 4

# JetRacerモード
python scripts/run_commentary.py "コーナーに進入中" --turns 4 --jetracer

# 複数トピック
python scripts/run_commentary.py "話題1" "話題2" --turns 2
```

### 4.2 JetRacer LIVE 実況

```bash
# 基本実行
python scripts/run_jetracer_live.py

# カスタム設定
python scripts/run_jetracer_live.py --url http://192.168.1.65:8000 --interval 2 --turns 4

# 10フレームで終了
python scripts/run_jetracer_live.py --frames 10
```

### 4.3 Python から直接使用

```python
from src.unified_pipeline import UnifiedPipeline
from src.input_source import InputBundle, InputSource, SourceType

# パイプライン初期化
pipeline = UnifiedPipeline(jetracer_mode=False)

# 入力バンドル作成
bundle = InputBundle(sources=[
    InputSource(source_type=SourceType.TEXT, content="お正月の準備について話して")
])

# 対話生成
result = pipeline.run(initial_input=bundle, max_turns=4)

# 結果表示
for turn in result.dialogue:
    print(f"[{turn.speaker_name}] {turn.text}")
```

---

## 5. 非推奨メソッドの警告

### 5.1 DeprecationWarning

`speak()` と `speak_v2()` を呼び出すと `DeprecationWarning` が発生します。

```python
import warnings

# 警告を表示する設定
warnings.simplefilter("always", DeprecationWarning)

char = Character("A")
char.speak(...)  # DeprecationWarning: speak() is deprecated, use speak_unified() instead
```

### 5.2 移行ガイド

**旧コード:**
```python
response = char.speak(
    frame_description="状況",
    partner_speech="相手の発言",
    conversation_context="履歴テキスト",
)
```

**新コード:**
```python
response = char.speak_unified(
    frame_description="状況",
    conversation_history=[("B", "相手の発言")],
)
```

---

## 6. 変更ファイル一覧

### 6.1 修正ファイル

| ファイル | 変更内容 |
|----------|----------|
| `src/character.py` | speak()/speak_v2()に非推奨警告追加 |
| `src/unified_pipeline.py` | run_continuous()追加 |
| `scripts/run_commentary.py` | v3.0: UnifiedPipeline使用 |
| `scripts/run_jetracer_live.py` | v3.0: UnifiedPipeline使用 |
| `src/jetracer_client.py` | get_camera_image()追加 |

### 6.2 新規ファイル

| ファイル | 内容 |
|----------|------|
| `tests/test_architecture_unification.py` | Phase 1-2 テスト |
| `docs/design/architecture_unified_v3.md` | 本ドキュメント |

---

## 7. 今後の予定

### 7.1 Phase 5（将来）

- 旧メソッド（speak, speak_v2）の完全削除
- 旧スクリプトの廃止

### 7.2 残課題

| 課題 | 優先度 | 備考 |
|------|--------|------|
| api_unified.py の検証 | 中 | GUI経由での動作確認 |
| Florence-2 統合 | 中 | VisionPipelineとの連携 |
| JetRacerカメラエンドポイント確認 | 低 | 実機での動作確認 |

---

## 8. テスト結果

### 8.1 自動テスト

```
tests/test_architecture_unification.py - 19/19 パス
```

### 8.2 手動テスト

| テスト | 結果 |
|--------|------|
| run_commentary.py 一般会話 | ✅ |
| run_commentary.py JetRacerモード | ✅ |
| run_jetracer_live.py 接続・実行 | ✅ |
| 非推奨警告表示 | ✅ |

---

*最終更新: 2026年1月7日*
