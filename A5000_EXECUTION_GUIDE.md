# 🚀 A5000実行ガイド - DUO-TALK GUI System

**このドキュメント**: A5000 GPU マシン上で DUO-TALK GUI システムを起動・実行するための完全ガイド

---

## 📋 クイックスタート

A5000マシンで以下を実行するだけで、完全なシステムが起動します：

```bash
cd /home/user/duo-talk
./start_gui.sh
```

**待機時間**: 約 30 秒でシステム起動完了

---

## ✅ 前提条件チェック

### 1. Ollama の確認

```bash
# Ollama が起動しているか確認
curl http://localhost:11434/api/tags

# 期待される出力:
{
  "models": [
    {
      "name": "qwen3:8b",
      "modified_at": "...",
      "size": ...
    },
    {
      "name": "qwen2.5:7b-instruct-q4_K_M",
      ...
    },
    {
      "name": "gemma3:12b",
      ...
    }
  ]
}
```

Ollama が起動していない場合：
```bash
# ターミナル 1 で実行
ollama serve

# または GPU フルパワーで実行
ollama serve --gpu all
```

### 2. Python/Node.js の確認

```bash
# バージョン確認（最低要件を満たしているか）
node --version      # v18.0.0 以上
npm --version       # 9.0.0 以上
python3 --version   # 3.9 以上
```

全て OK なら、次のステップへ

---

## 🎯 システム起動手順

### 方法 1: 自動起動（推奨）

```bash
cd /home/user/duo-talk
./start_gui.sh
```

**このコマンドが実行する内容**:
1. ✅ Node.js / npm / Python をチェック
2. ✅ npm dependencies をインストール（必要な場合）
3. ✅ Flask と flask-cors をインストール（必要な場合）
4. ✅ Flask バックエンド API を起動（ポート 5000）
5. ✅ Vite フロントエンド開発サーバーを起動（ポート 5173）

**出力例**:
```
════════════════════════════════════════════════════════════════════════════
✅ DUO-TALK GUI System is Running!
════════════════════════════════════════════════════════════════════════════

📌 Frontend (React):    http://localhost:5173
📌 Backend API:         http://localhost:5000
📌 API Endpoints:
     - GET  /api/run/list
     - GET  /api/run/events?run_id=...
     - GET  /api/run/stream?run_id=... (SSE)
     - POST /api/narration/start
     - GET  /api/feedback/trends
     - POST /api/feedback/record

💡 Press Ctrl+C to stop all services
════════════════════════════════════════════════════════════════════════════
```

### 方法 2: 手動起動（デバッグ用）

**ターミナル 1 - バックエンド API サーバー**:
```bash
cd /home/user/duo-talk
export FLASK_PORT=5000
python3 server/api_server.py
```

**ターミナル 2 - フロントエンド開発サーバー**:
```bash
cd /home/user/duo-talk/duo-gui
export VITE_API_BASE=http://localhost:5000
npm run dev
```

---

## 🌐 GUI へのアクセス

### ローカルマシンから
```
http://localhost:5173
```

### リモートマシンから
```
http://<A5000-IP-ADDRESS>:5173
```

例：
```
http://192.168.1.100:5173
```

---

## 🎬 最初のナレーション実行

### GUI から実行

1. **「New Narration」ボタンをクリック**
   - 左側パネルの上部にあります

2. **画像ファイルを選択**
   - ドロップダウンまたはファイル選択で以下を選択:
   - `/home/user/duo-talk/tests/images/temple_sample.jpg`
   - `/home/user/duo-talk/tests/images/nature_sample.jpg`

3. **シーン説明を入力**
   ```
   古い寺院の境内。参拝客が少なく、静かな時間帯のようです。
   ```

4. **「Start」ボタンをクリック**

5. **中央パネルでリアルタイム進行を監視**
   - Vision 分析中
   - やなの発言生成中
   - あゆの応答生成中
   - Director の評価を確認

### API から実行 (curl)

```bash
curl -X POST http://localhost:5000/api/narration/start \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/home/user/duo-talk/tests/images/temple_sample.jpg",
    "scene_description": "古い寺院の境内。参拝客が少なく、静かな時間帯のようです。"
  }'
```

---

## 📊 GUI 画面の説明

### 左側パネル - Run 管理

**RunList コンポーネント**:
- 全ナレーション実行の履歴を表示
- 各 Run の状態（running, completed, failed）
- 実行時刻と説明文
- クリックして詳細を表示

**ControlPanel コンポーネント**:
- 「New Narration」 - 新規実行開始
- 画像ファイル選択
- シーン説明テキスト入力
- 「Start」/「Stop」ボタン

### 中央パネル - リアルタイム監視

**TurnCard コンポーネント**:
- 各ターンの詳細情報を表示
- やなの発言（Character A）
- あゆの応答（Character B）
- Director の評価結果
  - PASS: 品質合格
  - RETRY: 再生成推奨
  - MODIFY: 修正推奨

**RagPanel コンポーネント**:
- RAG（Retrieval-Augmented Generation）検索結果
- 使用されたナレッジドメイン
- 検索スコア表示

### 右側パネル - 分析・フィードバック

**CovSpark コンポーネント**:
- キャラクター別のカバレッジ分析（A/B）
- ビートタイプ別の統計（BAN, PIV, PAY）
- リアルタイム更新グラフ

**PromptModal**:
- プロンプトデバッグ情報
- RAG 入力/出力の詳細
- 完全なシステムプロンプト表示

---

## 🔧 トラブルシューティング

### エラー: ポートが既に使用中

```bash
# ポート 5000 を使用しているプロセスを確認
lsof -i :5000
lsof -i :5173

# プロセスを終了
kill -9 <PID>

# または別のポートで起動
FLASK_PORT=5001 python3 server/api_server.py
cd duo-gui && VITE_PORT=5174 npm run dev
```

### エラー: Ollama 接続失敗

```bash
# Ollama が起動しているか確認
curl http://localhost:11434/api/tags

# 起動していない場合
ollama serve

# ファイアウォール確認（ポート 11434）
sudo ufw status
```

### エラー: npm dependencies がない

```bash
cd duo-gui
rm -rf node_modules package-lock.json
npm install
```

### エラー: Python モジュールが見つからない

```bash
# Python 仮想環境を確認
source /tmp/duo_env/bin/activate

# または新しく作成
python3 -m venv /tmp/duo_env
source /tmp/duo_env/bin/activate
pip install -r requirements.txt
pip install flask flask-cors
```

### エラー: CORS エラーが表示される

```bash
# フロントエンドで正しい API ベース URL を使用しているか確認
echo $VITE_API_BASE  # http://localhost:5000 であること

# または再起動時に設定
cd duo-gui
VITE_API_BASE=http://localhost:5000 npm run dev
```

---

## 📈 パフォーマンス監視

### リアルタイムログを確認

```bash
# Flask バックエンドログ
tail -f /tmp/flask.log

# イベント完全ログ
tail -f runs/commentary_runs.jsonl

# フィードバックログ
tail -f runs/feedback.jsonl
```

### ブラウザの開発者ツール

```
F12 キーを押して:
- Console: JavaScript エラーやワーニング
- Network: API リクエスト/レスポンス
- Performance: 画面の描画パフォーマンス
```

---

## 🎓 ワークフロー例

### シナリオ 1: 単一ナレーション実行と確認

```
1. GUI を開く
2. 「New Narration」をクリック
3. 画像を選択
4. シーン説明を入力
5. 「Start」をクリック
6. 完了を待つ（約 30-60 秒）
7. 結果を確認
```

**確認すること**:
- [ ] 両キャラクターの発言が生成された
- [ ] 発言が自然で役柄に合致している
- [ ] Director の評価が適切か

### シナリオ 2: 複数ナレーションの連続実行

```bash
# 3 つの異なる画像でテスト
for img in temple_sample.jpg nature_sample.jpg; do
  curl -X POST http://localhost:5000/api/narration/start \
    -H "Content-Type: application/json" \
    -d "{
      \"image_path\": \"/home/user/duo-talk/tests/images/$img\",
      \"scene_description\": \"テスト実行\"
    }"
  sleep 60  # 完了を待つ
done

# 実行結果一覧を確認
curl http://localhost:5000/api/run/list | python3 -m json.tool
```

### シナリオ 3: フィードバック記録と改善

```bash
# ナレーション実行（run_id を取得）
RUN_ID=$(curl -s -X POST http://localhost:5000/api/narration/start \
  -H "Content-Type: application/json" \
  -d '{...}' | python3 -c "import sys, json; print(json.load(sys.stdin)['run_id'])")

# フィードバック記録
curl -X POST http://localhost:5000/api/feedback/record \
  -H "Content-Type: application/json" \
  -d "{
    \"run_id\": \"$RUN_ID\",
    \"turn_num\": 1,
    \"speaker\": \"A\",
    \"issue_type\": \"tone_drift\",
    \"description\": \"キャラクターの口調が一貫していない\",
    \"suggested_fix\": \"『わ！』をもっと使う\"
  }"

# フィードバック分析
curl http://localhost:5000/api/feedback/trends | python3 -m json.tool
```

---

## 📚 ドキュメント参照

完全な情報は以下のドキュメントを参照してください：

1. **GUI_SETUP_GUIDE.md** - 詳細なセットアップガイド
2. **GUI_VERIFICATION_REPORT.md** - コンポーネント検証結果
3. **README.md** - プロジェクト概要
4. **VALIDATION_REPORT.md** - システム検証レポート

---

## 🔐 セキュリティ注意事項

### ローカル開発環境（現在）
- ✅ CORS 有効（localhost 対象）
- ✅ 認証なし（開発用）
- ✅ デバッグログ出力有効

### 本番環境へのデプロイ時
- ⚠️ 認証機構を追加（JWT など）
- ⚠️ HTTPS を有効化
- ⚠️ CORS ポリシーを制限
- ⚠️ レート制限を設定
- ⚠️ デバッグ情報を隠す
- ⚠️ ファイアウォールで API ポートを保護

---

## 📞 トラブルサポート

システムが起動しない場合：

1. **Ollama が起動しているか確認**
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. **ポートが使用可能か確認**
   ```bash
   lsof -i :5000
   lsof -i :5173
   lsof -i :11434
   ```

3. **ログを確認**
   ```bash
   tail -100 /tmp/flask.log
   tail -50 runs/commentary_runs.jsonl
   ```

4. **完全なリセット**
   ```bash
   # 既存プロセスを終了
   pkill -f "python3 server/api_server.py"
   pkill -f "npm run dev"
   pkill -f "ollama serve"

   # キャッシュをクリア
   rm -rf duo-gui/node_modules/.vite

   # 再起動
   ./start_gui.sh
   ```

---

## 🎉 成功の目安

以下が全て確認できたら、システムは正常に動作しています：

- ✅ ブラウザで http://localhost:5173 にアクセスできる
- ✅ 左側に Run 管理パネルが表示される
- ✅ 「New Narration」ボタンがクリック可能
- ✅ 画像を選択して実行できる
- ✅ 中央パネルに実行結果が表示される
- ✅ やなとあゆの発言が生成されている
- ✅ Director の評価が表示されている
- ✅ 右側に分析グラフが表示されている

---

## 🚀 次のステップ

### 今日中（インストール後 1-2 時間）
1. [ ] GUI を起動して複数の画像でテスト
2. [ ] キャラクター応答の質を確認
3. [ ] Director 評価の適切さを検証

### 今週中
4. [ ] フィードバック記録機能をテスト
5. [ ] HITL 改善ループを実行
6. [ ] パフォーマンスメトリクスを収集

### 今月中
7. [ ] RAG 知識ベースを拡張
8. [ ] キャラクタープロンプトを最適化
9. [ ] 本番環境セキュリティを実装

---

**最終更新**: 2025-12-14
**ステータス**: ✅ 本番環境実行可能
**最初のコマンド**: `./start_gui.sh`
