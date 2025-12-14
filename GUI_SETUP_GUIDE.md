# 🎨 DUO-TALK GUI 使用ガイド

## 📋 目次

1. [システム要件](#システム要件)
2. [インストール](#インストール)
3. [起動方法](#起動方法)
4. [GUI 機能](#gui-機能)
5. [使用例](#使用例)
6. [トラブルシューティング](#トラブルシューティング)

---

## システム要件

### ハードウェア
- **CPU**: 4コア以上推奨
- **メモリ**: 8GB 以上
- **ディスク**: 10GB 以上の空き容量

### ソフトウェア
- **Node.js**: 18.0.0 以上
- **npm**: 9.0.0 以上
- **Python**: 3.9 以上
- **Ollama**: 実行中（ローカル LLM）

---

## インストール

### 1. 前提条件の確認

```bash
# Node.js と npm のインストール確認
node --version   # v18.0.0 以上
npm --version    # 9.0.0 以上

# Python のインストール確認
python3 --version  # 3.9.0 以上
```

### 2. 依存パッケージのインストール

```bash
cd /home/user/duo-talk

# Python 依存パッケージ
pip install -r requirements.txt
pip install flask flask-cors

# Node.js 依存パッケージ（自動で以下で処理される）
# npm install --prefix duo-gui
```

### 3. Ollama の起動確認

```bash
# Ollama サーバーが起動していることを確認
curl http://localhost:11434/api/tags

# 必要なモデルが存在することを確認
# - qwen3:8b（Vision）
# - qwen2.5:7b-instruct-q4_K_M（Character）
# - gemma3:12b（Director）
```

---

## 起動方法

### ワンステップ起動（推奨）

```bash
cd /home/user/duo-talk
./start_gui.sh
```

このスクリプトは以下を自動的に実行します：
- ✅ 前提条件チェック
- ✅ Node.js 依存パッケージのインストール
- ✅ Flask サーバーの起動
- ✅ Vite 開発サーバーの起動

### 手動起動

#### ターミナル 1：バックエンド API サーバー

```bash
cd /home/user/duo-talk
export FLASK_PORT=5000
python3 server/api_server.py
```

出力例：
```
🚀 DUO-TALK Backend API Server
Starting API server on http://localhost:5000
```

#### ターミナル 2：フロントエンド

```bash
cd /home/user/duo-talk/duo-gui
VITE_API_BASE=http://localhost:5000 npm run dev
```

出力例：
```
  ➜  Local:   http://localhost:5173/
  ➜  press h to show help
```

### アクセス

ブラウザで以下にアクセス：
```
http://localhost:5173
```

---

## GUI 機能

### 【1】Run 管理パネル（左側）

**RunList コンポーネント**
- ✅ 全ナレーション実行の履歴表示
- ✅ 各 Run の状態表示（running, completed, failed）
- ✅ タイムスタンプと説明文

**ControlPanel コンポーネント**
- ✅ 新規ナレーション実行ボタン
- ✅ 画像ファイルの選択
- ✅ シーン説明の入力
- ✅ 実行の開始/停止制御

### 【2】リアルタイム監視（中央）

**TurnCard コンポーネント**
- ✅ 各ターンの詳細表示
- ✅ キャラクター（やな/あゆ）の発言表示
- ✅ Director 評価の表示（PASS/RETRY/MODIFY）

**RagPanel コンポーネント**
- ✅ RAG 検索結果の可視化
- ✅ 使用されたドメイン情報
- ✅ 検索スコア表示

### 【3】分析・フィードバック（右側）

**CovSpark コンポーネント**
- ✅ キャラクター別のカバレッジ（A/B）
- ✅ ビートタイプ別の分析（BAN, PIV, PAY）
- ✅ リアルタイム更新グラフ

**PromptModal**
- ✅ プロンプトデバッグ情報の表示
- ✅ RAG 入力/出力の確認
- ✅ 完全なシステムプロンプト表示

### 【4】フィードバック記録

Run 画面から：
1. 問題のあるターンをクリック
2. 「Report Issue」をクリック
3. 問題タイプを選択（tone_drift, knowledge_overstep など）
4. 説明と改善案を入力
5. 「Submit」をクリック

---

## 使用例

### シナリオ 1：新しいナレーション実行

```
1. 「New Narration」ボタンをクリック
2. 画像ファイルを選択
   例：/home/user/duo-talk/tests/images/temple_sample.jpg
3. シーン説明を入力
   例：「古い寺院の境内。参拝客が少なく、静かな時間帯のようです。」
4. 「Start」をクリック
5. リアルタイムで以下を監視：
   - Vision 分析の進行状況
   - やなの発言生成
   - あゆの応答生成
   - Director 評価結果
```

### シナリオ 2：品質問題のフィードバック

```
1. 実行履歴から Run を選択
2. 問題のあるターンを確認
3. 「Report Issue」をクリック
4. 問題の詳細を記入：
   - Issue Type:「tone_drift」
   - Description: 「やなの感情マーカーが少ない」
   - Suggested Fix: 「もっと『わ！』を使う」
5. 記録されたフィードバックは HITL ループで分析される
```

### シナリオ 3：複数 Run の比較

```
1. 左側で Run A を選択 → 詳細表示
2. 「Compare」ボタンをクリック
3. Run B を選択
4. 並列表示で以下を比較：
   - Director 評価の違い
   - RAG 検索結果の差異
   - キャラクターの応答品質
   - スタイル遵守率
```

---

## トラブルシューティング

### 1. ポート競合エラー

```
Error: listen EADDRINUSE :::5173
```

**解決策**：
```bash
# ポートが使用中かどうか確認
lsof -i :5173
lsof -i :5000

# プロセスを終了
kill -9 <PID>

# または別のポートを指定
VITE_PORT=5174 npm run dev
FLASK_PORT=5001 python3 server/api_server.py
```

### 2. CORS エラー

```
Access to XMLHttpRequest at 'http://localhost:5000/...' has been blocked by CORS policy
```

**解決策**：
- API サーバーは CORS が有効に設定されています
- `VITE_API_BASE` 環境変数が正しく設定されているか確認：
  ```bash
  VITE_API_BASE=http://localhost:5000 npm run dev
  ```

### 3. Ollama 接続エラー

```
Failed to connect to Ollama
```

**解決策**：
```bash
# Ollama サーバーが起動しているか確認
curl http://localhost:11434/api/tags

# 起動していない場合
ollama serve

# または A5000 で実行
ssh user@a5000
ollama serve
```

### 4. API エンドポイント 404 エラー

**解決策**：
- Flask サーバーが起動しているか確認
- ログで詳細なエラーメッセージを確認
- API ペイロードが正しいことを確認（POST リクエスト）

### 5. フロントエンド が読み込まれない

```bash
# Vite 開発サーバーのログを確認
npm run dev --debug

# Node.js のメモリ問題の場合
export NODE_OPTIONS=--max-old-space-size=4096
npm run dev
```

---

## API リファレンス

### Run 管理

```
GET /api/run/list
  レスポンス: [{"run_id": "...", "scene": "...", "timestamp": "...", "status": "..."}]

GET /api/run/events?run_id=xxx
  レスポンス: [{"event": "turn", "run_id": "xxx", ...}]

GET /api/run/stream?run_id=xxx
  レスポンス: SSE ストリーム（ライブ監視）

POST /api/narration/start
  リクエスト: {"image_path": "...", "scene_description": "..."}
  レスポンス: {"run_id": "...", "status": "completed"}
```

### フィードバック

```
POST /api/feedback/record
  リクエスト: {
    "run_id": "...",
    "turn_num": 1,
    "speaker": "A",
    "issue_type": "tone_drift",
    "description": "...",
    "suggested_fix": "..."
  }
  レスポンス: {"status": "recorded"}

GET /api/feedback/trends
  レスポンス: {"trends": {...}, "by_character": {...}}
```

### システム情報

```
GET /api/system/status
  レスポンス: {"status": "running", "components": {...}}

GET /health
  レスポンス: {"status": "ok"}
```

---

## パフォーマンス最適化

### フロントエンド

```bash
# 本番ビルド
npm run build

# プレビュー
npm run preview
```

### バックエンド

```python
# 環境変数でログレベル設定
export LOG_LEVEL=INFO
python3 server/api_server.py
```

---

## セキュリティ推奨事項

### ローカル開発環境（現在）
- ✅ すべてのエンドポイントに認証なし（開発用）

### 本番環境へのデプロイ時
- ⚠️ 認証機構の追加（JWT など）
- ⚠️ HTTPS の有効化
- ⚠️ CORS ポリシーの制限
- ⚠️ レート制限の設定
- ⚠️ ログレベルの調整（デバッグ情報を隠す）

---

## 次のステップ

### 短期（1 日）
- [ ] GUI で複数の画像をナレーション
- [ ] フィードバックを記録
- [ ] リアルタイム監視の確認

### 中期（1 週間）
- [ ] HITL ループで改善を実施
- [ ] パフォーマンスメトリクスの監視
- [ ] キャラクター応答品質の改善

### 長期（継続）
- [ ] 本番環境へのデプロイ準備
- [ ] 認証・セキュリティの強化
- [ ] スケーラビリティの最適化

---

## サポート

### ログファイルの確認

```bash
# Flask ログ
tail -f /path/to/logs/flask.log

# React ブラウザコンソール
F12 キー → Console タブ

# イベントログ
cat /home/user/duo-talk/runs/commentary_runs.jsonl
```

### デバッグモード

```bash
# Python デバッグ
export DEBUG=1
python3 server/api_server.py

# React デバッグ
npm run dev -- --debug
```

---

**2025-12-14 作成**
DUO-TALK GUI セットアップガイド v1.0
