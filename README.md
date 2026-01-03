# duo-talk

JetRacerの実況システム。姉妹AIが自律走行車の状態を実況します。

## クイックスタート

```bash
# セットアップ
conda activate duo-talk
pip install -r requirements.txt

# サーバー起動
python server/api_server.py

# ブラウザで開く
open http://localhost:5000
```

## システム構成

```
JetRacer (192.168.1.65:8000)
    ↓ センサー + カメラ
duo-talk Server (Flask)
    ↓ DuoSignals + NoveltyGuard
LLM (Ollama/vLLM)
    ↓ 対話生成
GUI (React) / TTS
```

## v2.1 新機能

- **DuoSignals**: スレッドセーフな状態共有
- **NoveltyGuard**: 話題ループ検知・戦略ローテーション
- **SilenceController**: 状況に応じた自然な沈黙
- **VLMAnalyzer**: カメラ画像の解析
- **LivePanel**: リアルタイムGUI監視

## テスト

```bash
# ユニットテスト
pytest tests/ -v

# ライブ対話テスト（JetRacer接続時）
python scripts/test_live_v2.py --turns 10

# センサーシミュレーション
python scripts/test_sensor_simulation.py

# ループ検知テスト
python scripts/test_loop_detection.py --turns 15
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

## v2.1 機能一覧

| 機能 | 説明 |
|------|------|
| DuoSignals | スレッドセーフな状態共有、イベント履歴 |
| PromptBuilder | 優先度ベースのプロンプト構築 |
| NoveltyGuard | 話題ループ検知、戦略ローテーション |
| SilenceController | 状況に応じた自然な沈黙 |
| speak_v2 | 統合された発話生成メソッド |
| LivePanel | リアルタイムGUI監視 |

## ディレクトリ構成

```
duo-talk/
├── src/                    # コアモジュール
│   ├── signals.py          # DuoSignals
│   ├── injection.py        # PromptBuilder
│   ├── novelty_guard.py    # NoveltyGuard
│   ├── silence_controller.py
│   ├── character.py        # キャラクター
│   ├── vlm_analyzer.py     # VLM解析
│   └── vision_to_signals.py
├── server/                 # APIサーバー
│   ├── api_server.py
│   └── api_v2.py           # v2.1 API
├── duo-gui/                # Reactフロントエンド
│   └── src/components/
│       ├── LivePanel.tsx
│       └── SignalsPanel.tsx
├── persona/                # キャラクター設定
│   ├── char_a/prompt.yaml
│   ├── char_b/prompt.yaml
│   └── world_rules.yaml
├── scripts/                # テストスクリプト
│   ├── test_live_v2.py
│   ├── test_sensor_simulation.py
│   └── test_loop_detection.py
└── docs/                   # ドキュメント
    └── v2_1_guide.md
```

## ライセンス

MIT License

## 謝辞

- JetRacer by NVIDIA
- Qwen 2.5 by Alibaba
- LivePortrait for avatar animation
