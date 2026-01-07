# duo-talk

JetRacerの実況システム。姉妹AIが自律走行車の状態を実況します。

## クイックスタート

```bash
# セットアップ
conda activate duo-talk
pip install -r requirements.txt

# サーバー起動
python server/api_unified.py

# ブラウザで開く
open http://localhost:5000
```

## システム構成

```
JetRacer (192.168.1.65:8000)
    ↓ センサー + カメラ
duo-talk Server (FastAPI)
    ↓ UnifiedPipeline
LLM (vLLM/Ollama)
    ↓ 対話生成
GUI (React) / TTS
```

## v3.0 アーキテクチャ統一（NEW）

v3.0ではConsole/RUNS/LIVEの3実行パスを`UnifiedPipeline`に統一しました。

```
Entry Points
├── scripts/run_commentary.py     → UnifiedPipeline.run()
├── scripts/run_jetracer_live.py  → UnifiedPipeline.run_continuous()
└── server/api_unified.py         → UnifiedPipeline.run()
         ↓
UnifiedPipeline v3.0
├── run()           - バッチ実行
├── run_continuous() - 連続実行（LIVE用）
└── 内部でDirector/NoveltyGuard統合
         ↓
Character.speak_unified()  ← 唯一の推奨メソッド
```

### コマンドライン実行

```bash
# 一般会話モード
python scripts/run_commentary.py "今日の天気について" --turns 4

# JetRacerモード
python scripts/run_commentary.py "コーナーに進入中" --turns 4 --jetracer

# JetRacer LIVE実況
python scripts/run_jetracer_live.py --interval 3 --turns 4
```

詳細: [docs/design/architecture_unified_v3.md](docs/design/architecture_unified_v3.md)

## v2.1 機能

- **DuoSignals**: スレッドセーフな状態共有
- **NoveltyGuard**: 話題ループ検知・戦略ローテーション
- **SilenceController**: 状況に応じた自然な沈黙
- **VLMAnalyzer**: カメラ画像の解析
- **LivePanel**: リアルタイムGUI監視

## テスト

```bash
# ユニットテスト
pytest tests/ -v

# アーキテクチャ統一テスト
pytest tests/test_architecture_unification.py -v

# ライブ対話テスト（JetRacer接続時）
python scripts/run_jetracer_live.py --frames 5

# コンソール対話テスト
python scripts/run_commentary.py "テスト話題" --turns 4
```

## キャラクター設定

### やな（姉/Edge AI）
- **役割**: 発見役、質問者
- **口調**: カジュアル、「〜じゃない？」「〜かな？」
- **特性**: 直感的、行動優先、感覚表現

### あゆ（妹/Cloud AI）
- **役割**: 補足役、解説者
- **口調**: 敬語、「姉様」呼び
- **特性**: データ重視、分析的、正確性優先

## 主要コンポーネント

| コンポーネント | 説明 |
|---------------|------|
| **UnifiedPipeline** | 統一対話パイプライン（v3.0） |
| **Character** | キャラクター発話生成 |
| **Director** | 対話品質評価・ループ検知 |
| **DuoSignals** | スレッドセーフな状態共有 |
| **PromptBuilder** | 優先度ベースのプロンプト構築 |
| **NoveltyGuard** | 話題ループ検知 |
| **SilenceController** | 状況に応じた沈黙制御 |
| **VisionPipeline** | 画像解析（VLM + Florence-2） |

## GUIサーバー

### 起動方法

```bash
conda activate duo-talk
python server/api_unified.py
# ブラウザで http://localhost:5000 を開く
```

### GUIタブ

| タブ | 機能 |
|------|------|
| Console | コンソール実行 |
| Runs | 過去の実行ログ閲覧 |
| Live | JetRacerリアルタイム実況 |
| Settings | 設定確認 |

### 主要APIエンドポイント

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/unified/narrate` | POST | 対話生成（UnifiedPipeline） |
| `/api/v2/signals` | GET | DuoSignals状態取得 |
| `/api/v2/novelty/status` | GET | NoveltyGuard状態 |
| `/api/v2/jetracer/connect` | POST | JetRacer接続 |
| `/api/v2/jetracer/fetch` | GET | センサーデータ取得 |

## ディレクトリ構成

```
duo-talk/
├── src/                        # コアモジュール
│   ├── unified_pipeline.py     # UnifiedPipeline（v3.0）
│   ├── character.py            # キャラクター
│   ├── director.py             # Director + NoveltyGuard
│   ├── signals.py              # DuoSignals
│   ├── injection.py            # PromptBuilder
│   ├── novelty_guard.py        # NoveltyGuard
│   ├── silence_controller.py   # SilenceController
│   ├── input_source.py         # InputBundle/InputSource
│   ├── input_collector.py      # InputCollector
│   ├── vision_pipeline.py      # VisionPipeline
│   ├── jetracer_client.py      # JetRacer HTTP API
│   └── jetracer_provider.py    # モード別データ取得
├── server/                     # APIサーバー
│   ├── api_unified.py          # 統一API（推奨）
│   ├── api_server.py           # 旧API
│   └── api_v2.py               # v2.1 API
├── scripts/                    # 実行スクリプト
│   ├── run_commentary.py       # コンソール実行（v3.0）
│   └── run_jetracer_live.py    # LIVE実況（v3.0）
├── duo-gui/                    # Reactフロントエンド
│   └── src/components/
├── persona/                    # キャラクター設定
│   ├── char_a/
│   │   ├── prompt.yaml
│   │   ├── prompt_general.yaml
│   │   ├── prompt_jetracer.yaml
│   │   └── deep_values.yaml
│   ├── char_b/
│   └── few_shots/patterns.yaml
├── tests/                      # テスト
│   └── test_architecture_unification.py
└── docs/                       # ドキュメント
    └── design/
        └── architecture_unified_v3.md
```

## バージョン履歴

| バージョン | 日付 | 主な変更 |
|-----------|------|----------|
| v3.0 | 2026-01-07 | UnifiedPipeline統一、speak_unified() |
| v2.2 | 2026-01-06 | VLM統合、モード別prompt.yaml |
| v2.1 | 2026-01-04 | DuoSignals、NoveltyGuard、speak_v2() |
| v1.0 | 2025-12 | 初期リリース |

## ライセンス

MIT License

## 謝辞

- JetRacer by NVIDIA
- Gemma 3 by Google
- Florence-2 by Microsoft
- LivePortrait for avatar animation
