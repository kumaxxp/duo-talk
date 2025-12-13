# Tourism AI Commentary System

ローカルLLMを使用した、観光地やドローン映像の対話実況システムです。
姉（行動的）と妹（クール）の2人のAIキャラクターが、ディレクターLLMの監督のもと、自然で面白い対話を生成します。

## システム概要

```
Input: Frame Description / Image
  ↓
[Director LLM] - 監視: 進行度・参加度・知識領域
  ↓
[Character A (Elder Sister)] + [Character B (Younger Sister)]
  ↓
[Validation] - 言語チェック・口調チェック
  ↓
Output: Dialogue JSON / Text
```

## 特徴

- **ディレクターLLM**: 2人のキャラクターの対話品質を監視
  - 進行度: フレームへの対応度
  - 参加度: 両者のバランス
  - 知識領域: キャラクター固有の知識の適切な使用

- **キャラクター分化**: 知識領域を分離
  - 姉: 観光・行動・現象
  - 妹: 地理・歴史・建築

- **自然な対話生成**: RAGによる知識提供

## インストール

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## セットアップ

### 1. 環境変数

`.env.example` をコピーして `.env` を作成:

```bash
cp .env.example .env
```

中身を編集（Ollama/LM Studio の設定を合わせます）:

```env
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=not-needed
OPENAI_MODEL=mistral
```

### 2. Ollama の起動

```bash
ollama serve
# 別のターミナル
ollama pull mistral
```

または LM Studio を起動して同等の設定にします。

## 使い方

### 基本的な実行

```bash
python scripts/run_commentary.py "最初のフレーム説明" "2番目のフレーム説明" "3番目のフレーム説明"
```

例：
```bash
python scripts/run_commentary.py \
  "富士山の頂上がクローズアップされている。雪が積もっている。" \
  "ドローンが富士山を回りながら麓の町を映す。" \
  "富士山の影が地面に映っている。夕方の光が当たっている。"
```

### オプション

```bash
python scripts/run_commentary.py --help

# より多くの対話ターンを生成
python scripts/run_commentary.py --max-turns-per-frame 3 "フレーム1" "フレーム2"
```

## ログとデバッグ

すべてのイベントは `runs/commentary_runs.jsonl` に記録されます（JSONL形式）。

```bash
# 最新のrun_idを取得
RID=$(tac runs/commentary_runs.jsonl | jq -r 'select(.event=="run_start")|.run_id' | head -1)

# そのrunのすべてのイベントを表示
jq -r --arg RID "$RID" 'select(.run_id==$RID)' runs/commentary_runs.jsonl

# ターンのみを表示
jq -r --arg RID "$RID" 'select(.run_id==$RID and .event=="turn")' runs/commentary_runs.jsonl
```

## ディレクトリ構造

```
duo-talk/
├── src/
│   ├── __init__.py
│   ├── config.py              # 設定管理
│   ├── types.py               # 型定義
│   ├── llm_client.py          # LLM API呼び出し
│   ├── rag.py                 # 知識検索（RAG）
│   ├── director.py            # ディレクターLLM
│   ├── character.py           # キャラクター実装
│   ├── validator.py           # バリデーション
│   └── logger.py              # JSONL ロギング
│
├── persona/
│   ├── char_a.prompt.txt      # 姉のシステムプロンプト
│   ├── char_b.prompt.txt      # 妹のシステムプロンプト
│   └── director.prompt.txt    # ディレクターのプロンプト
│
├── rag_data/
│   ├── char_a_domain/         # 姉の知識領域
│   │   ├── tourism.md
│   │   ├── action.md
│   │   └── phenomena.md
│   │
│   └── char_b_domain/         # 妹の知識領域
│       ├── geography.md
│       ├── history.md
│       └── architecture.md
│
├── scripts/
│   └── run_commentary.py      # メイン実行スクリプト
│
├── runs/
│   └── commentary_runs.jsonl  # ログファイル（自動生成）
│
├── requirements.txt
├── .env.example
└── README.md
```

## キャラクター設定

### 姉 (Character A)

- **性格**: 行動的、直感的、感情豊か
- **話し方**: 「〜ね」「〜だよ」「へ？」「わ！」
- **知識領域**: 観光、行動、現象
- **役割**: 反応と質問でリード

### 妹 (Character B)

- **性格**: クール、ロジカル、思慮深い
- **話し方**: 「〜な」「ちょっと待て」「なるほど」
- **知識領域**: 地理、歴史、建築
- **役割**: 説明と補足

## RAG（知識検索）について

各キャラクターは自分の知識領域内から関連情報を自動検索します。

```
rag_data/char_a_domain/       ← 姉の知識ベース
rag_data/char_b_domain/       ← 妹の知識ベース
```

知識を追加する場合は、対応するフォルダに `.md` ファイルを追加してください。

## トラブルシューティング

### LLM が応答しない

```
✓ Ollama が起動しているか確認: ollama serve
✓ .env の OPENAI_BASE_URL が正しいか確認
✓ モデルがダウンロード済みか確認: ollama list
```

### ダイアログが面白くない

- `persona/*.prompt.txt` を調整
- `rag_data/` の知識を追加・改善
- `Director.py` の評価ロジックを調整

### 言語が混ざる

- `Validator.py` の日本語チェックが機能
- LoRA fine-tuning で日本語能力を向上させることを検討

## 今後の拡張

- [ ] TTS（音声合成）統合
- [ ] 画像入力対応（Vision API）
- [ ] キャラクター数を増やす
- [ ] GUI（リアルタイム可視化）
- [ ] キャラクター一貫性スコア
- [ ] 自動評価メトリクス

## ライセンス

MIT License

## 参考

このシステムはゆっくり実況（霊夢と魔理沙）のような対話スタイルを目指しています。
