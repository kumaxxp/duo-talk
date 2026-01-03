# duo-talk v2.1 使用ガイド

## 概要

v2.1は、duo-talkシステムの大幅な改良版です。
設計書 `duo_talk_design_v2_revised.md` に基づき、以下を実装しました。

## 実装済みPhase

### Phase 0: VLM統合基盤

**ファイル**: `src/vlm_analyzer.py`, `src/vision_to_signals.py`

カメラ画像をVLMで解析し、構造化されたシーン情報（scene_facts）に変換。
```python
from src.vlm_analyzer import VLMAnalyzer

analyzer = VLMAnalyzer()
result = analyzer.analyze_image("path/to/image.jpg")
print(result.to_scene_facts())
# {'road_condition': 'clear', 'visibility': 'good', ...}
```

### Phase 1: 状態共有基盤

**ファイル**: `src/signals.py`, `src/injection.py`, `src/novelty_guard.py`

#### DuoSignals

姉妹間で共有する状態を管理するシングルトンクラス。
```python
from src.signals import DuoSignals, SignalEvent, EventType

signals = DuoSignals()

# センサーイベント
signals.update(SignalEvent(
    event_type=EventType.SENSOR,
    data={"speed": 1.5, "steering": 10.0}
))

# 状態取得
state = signals.snapshot()
print(f"Speed: {state.current_speed}")
```

#### PromptBuilder

優先度ベースでプロンプトを構築。
```python
from src.injection import PromptBuilder, Priority

builder = PromptBuilder(max_tokens=6000)
builder.add("システム設定", Priority.SYSTEM)
builder.add("キャラクター設定", Priority.DEEP_VALUES)
builder.add("直前の発言", Priority.LAST_UTTERANCE)

prompt = builder.build()
```

#### NoveltyGuard

話題のループを検知し、切り口変更を提案。
```python
from src.novelty_guard import NoveltyGuard

guard = NoveltyGuard(max_topic_depth=3)
result = guard.check_and_update("センサーの値が...")

if result.loop_detected:
    print(f"Strategy: {result.strategy.value}")
    # specific_slot, conflict_within, action_next
```

### Phase 2: キャラクター強化

**ファイル**: `src/character.py`, `src/prompt_loader.py`, `src/few_shot_injector.py`

#### speak_v2メソッド

統合された発話生成メソッド。
```python
from src.character import Character

char_a = Character("A")  # やな
result = char_a.speak_v2(
    last_utterance="前方に障害物があります",
    context={"history": [...]},
    frame_description="走行可能領域75%。前方にコーンあり。"
)

print(result["content"])  # 発話内容
print(result["debug"])    # ループ検知、戦略など
```

#### YAMLプロンプト

キャラクター設定はYAMLファイルで管理。
```yaml
# persona/char_a/prompt.yaml
name: やな
role: 発見役
speaking_style:
  tone: カジュアル
  endings: ["〜ね", "〜かな？", "〜じゃない？"]
```

### Phase 3: 記憶システム（未実装）

設計書に従い後回し。ChromaDBを使用した姉妹記憶を予定。

---

## API リファレンス

### v2.1 エンドポイント

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/v2/signals` | GET | DuoSignals状態取得 |
| `/api/v2/signals/update` | POST | シグナル更新（テスト用） |
| `/api/v2/signals/stream` | GET | SSEストリーム |
| `/api/v2/novelty/status` | GET | NoveltyGuard状態 |
| `/api/v2/novelty/check` | POST | ループ検知チェック |
| `/api/v2/silence/check` | GET | 沈黙判定 |
| `/api/v2/speak` | POST | speak_v2発話生成 |
| `/api/v2/jetracer/connect` | POST | JetRacer接続 |
| `/api/v2/jetracer/fetch` | GET | センサーデータ取得 |
| `/api/v2/jetracer/stream` | GET | JetRacer SSEストリーム |
| `/api/v2/live/dialogue` | POST | ライブ対話生成 |

### 使用例
```bash
# JetRacer接続
curl -X POST http://localhost:5000/api/v2/jetracer/connect \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.65:8000", "mode": "vision"}'

# シグナル取得
curl http://localhost:5000/api/v2/signals

# 対話生成
curl -X POST http://localhost:5000/api/v2/live/dialogue \
  -H "Content-Type: application/json" \
  -d '{"frame_description": "走行可能領域80%", "turns": 2}'
```

---

## トラブルシューティング

### JetRacer接続失敗
```
Error: Connection failed
```

**対処**:
1. JetRacerの電源確認
2. IPアドレス確認（ping 192.168.1.65）
3. JetRacer APIサーバーが起動しているか確認

### ループ検知が頻発

**対処**:
1. `max_topic_depth`を増やす（デフォルト3）
2. 入力データ（frame_description）に変化を持たせる
3. Few-shotパターンを追加

### キャラクター性が崩れる

**対処**:
1. `persona/char_*/prompt.yaml`を確認
2. LLMの温度パラメータを下げる
3. Few-shotパターンを調整

---

## 設定ファイル

### 環境変数（.env）
```
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_MODEL=qwen2.5:14b-instruct-q4_K_M
FLASK_PORT=5000
```

### キャラクター設定

- `persona/char_a/prompt.yaml` - やな（姉）
- `persona/char_b/prompt.yaml` - あゆ（妹）
- `persona/director/prompt.yaml` - ディレクター
- `persona/world_rules.yaml` - 世界観ルール
- `persona/few_shots/patterns.yaml` - Few-shotパターン

---

## 今後の予定

- [ ] Phase 3: 姉妹記憶システム（ChromaDB）
- [ ] TTS統合（音声合成）
- [ ] LivePortraitアバター連携
- [ ] 長時間走行テスト
