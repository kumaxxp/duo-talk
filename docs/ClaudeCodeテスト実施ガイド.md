# Claude Code テスト実施ガイド
## Phase 0 RUNSタブチャット機能の動作確認

*作成日: 2026年1月9日*
*テスト実施者: Claude Code*
*テスト内容: GUI 起動 → RUNSタブ Chat Mode 動作確認*

---

## 📋 テスト概要

### テスト対象
- **コンポーネント:** ChatInputPanel.tsx（新規）
- **修正ファイル:** App.tsx（インポート + 統合）
- **API エンドポイント:** POST /api/unified/run/start-sync

### テスト期間
- **期間:** 約20-30分
- **タイミング:** 実装直後の動作確認

### テスト成功基準
1. ✅ GUI が起動する（ポート 5173）
2. ✅ [Runs] タブに切り替わる
3. ✅ 「💬 Chat Mode」パネルが表示される
4. ✅ テキスト入力が可能
5. ✅ [送信] ボタンが有効
6. ✅ 2-5秒後に Yana/Ayu の応答が表示される
7. ✅ エラーハンドリングが動作する

---

## 🚀 テスト実行手順

### ステップ 1: 環境確認（5分）

#### 1-1: Docker が起動しているか確認
```bash
docker ps | grep duo-talk
```

**期待出力:**
```
CONTAINER ID    IMAGE                   STATUS
xxxxxxxx        duo-talk-vllm           Up 2 hours
yyyyyyyy        duo-talk-florence2      Up 2 hours
```

**対応方法:**
- もしコンテナが停止していたら:
```bash
# vLLM コンテナ起動
docker compose -f docker/docker-compose.florence2.yml up -d

# または
./docker/scripts/start-vllm.sh gemma3-12b-int8
```

#### 1-2: API サーバーが応答しているか確認
```bash
curl -s http://localhost:5000/health | jq .
```

**期待出力:**
```json
{
  "status": "ok"
}
```

**対応方法:**
- もし 503 エラーが出たら、Flask サーバーが停止している
- `./start_gui.sh` で再起動

---

### ステップ 2: GUI 起動（5分）

#### 2-1: GUI 起動スクリプト実行
```bash
cd /work/duo-talk
./start_gui.sh
```

**期待出力（ターミナル）:**
```
✅ Activated conda environment 'duo-talk'
🔧 Starting Backend API Server (Flask)... PID: XXXXX
🎨 Starting Frontend (Vite)... PID: YYYYY
📡 Backend API running at http://localhost:5000
📌 Frontend (React) running at http://localhost:5173
```

**所要時間:** 5-10秒

**トラブル対応:**
- Node.js に問題がある場合:
```bash
cd duo-gui
npm install
npm run dev
```

#### 2-2: ブラウザで GUI にアクセス
```
ブラウザを開く
URL: http://localhost:5173
```

**期待画面:**
- DUO-TALK ロゴが表示される
- タブ: Unified / Runs / Vision Settings / Live / Provider
- Runs タブが初期選択されている可能性あり

---

### ステップ 3: RUNSタブで Chat Mode を確認（10分）

#### 3-1: [Runs] タブをクリック（既に選択されていれば OK）
```
画面左の「Runs」ボタンをクリック
```

**期待画面:**
- 左サイドバーに複数のパネルが表示される
  - New Run
  - **💬 Chat Mode** ← ★ ここが新規追加
  - Owner Intervention Control
  - Runs リスト
  - Filters
  - RAG Panel
- 右メインパネル: Timeline

#### 3-2: Chat Mode パネルの確認
```
左サイドバーの「💬 Chat Mode」パネルを見る
```

**期待要素:**
```
┌─────────────────────────┐
│ 💬 Chat Mode           │
├─────────────────────────┤
│ [メッセージ履歴エリア]   │
│  (最初は空)              │
│                         │
│ ┌───────────────────┐   │
│ │メッセージ入力     │   │
│ ├───────────────────┤   │
│ │ [テキスト入力フィ] [送信] │
│ ├───────────────────┤   │
│ │💡 ヒント表示      │   │
│ └───────────────────┘   │
└─────────────────────────┘
```

#### 3-3: テキスト入力テスト
```
1. テキスト入力フィールドをクリック
2. テキストを入力
   例: "こんにちは"
3. [送信] ボタンをクリック（または Enter キーを押す）
```

**期待動作:**
- テキスト入力フィールドが空になる
- 入力したテキストがチャット履歴に表示される
- 「⏳ 応答を待機中... (処理時間: 2-5秒)」表示が出現
- [送信] ボタンが disabled 状態になる

#### 3-4: API 呼び出し確認（ブラウザ DevTools）
```
F12 キーを押してブラウザ DevTools を開く
```

**確認箇所:**
- **Network タブ**
  - [送信] 後に新しいリクエストが表示される
  - リクエスト: POST /api/unified/run/start-sync
  - Status: 200
  - Request body: { "text": "こんにちは", "maxTurns": 2 }
  - Response: { "status": "success", "dialogue": [...] }

**スクリーンショット確認:**
```
Network タブの Request Headers:
  POST /api/unified/run/start-sync HTTP/1.1
  Host: localhost:5000
  Content-Type: application/json

Request Payload:
  {
    "text": "こんにちは",
    "maxTurns": 2
  }

Response:
  {
    "status": "success",
    "run_id": "run_20260109_XXXXXX",
    "dialogue": [
      {
        "turn_number": 0,
        "speaker": "A",
        "speaker_name": "やな",
        "text": "やあ、こんにちは！..."
      },
      {
        "turn_number": 1,
        "speaker": "B",
        "speaker_name": "あゆ",
        "text": "こんにちは。..."
      }
    ]
  }
```

#### 3-5: 応答表示確認
```
2-5秒待機
```

**期待動作:**
- ローディング表示が消える
- Yana の応答がチャット履歴に表示される（緑色）
- Ayu の応答がチャット履歴に表示される（紫色）
- 時刻が表示される

**チャット履歴の例:**
```
┌─ You (Blue) ────────────┐
│ こんにちは               │
│ 00:15                  │
└──────────────────────────┘

┌─ Yana (Green) ───────────┐
│ やあ、こんにちは！...     │
│ 00:16                   │
└──────────────────────────┘

┌─ Ayu (Purple) ───────────┐
│ こんにちは。...          │
│ 00:16                   │
└──────────────────────────┘
```

---

### ステップ 4: 複数ターンテスト（5分）

#### 4-1: 2番目のメッセージを送信
```
1. テキスト入力フィールドに別のテキストを入力
   例: "今日の天気は？"
2. [送信] ボタンをクリック
```

**期待動作:**
- 前のメッセージ履歴が保持されている
- 新しいメッセージがチャット履歴に追加される
- Yana/Ayu の新しい応答が追加される

**チャット履歴の結果:**
```
[前のメッセージ 3 件]
↓
┌─ You ────────────────────┐
│ 今日の天気は？            │
│ 00:20                   │
└──────────────────────────┘

┌─ Yana ─────────────────────┐
│ えっと、そういった話は...   │
│ 00:21                    │
└──────────────────────────┘

┌─ Ayu ──────────────────────┐
│ 申し訳ございませんが...     │
│ 00:21                    │
└──────────────────────────┘
```

---

### ステップ 5: エラーハンドリングテスト（5分）

#### 5-1: 空入力テスト
```
テキスト入力フィールドを空のままにして [送信] をクリック
```

**期待動作:**
- [送信] ボタンが disabled（薄いグレー）
- クリックできない
- メッセージが送信されない

#### 5-2: Docker 停止による API エラーテスト（オプション）
```bash
# vLLM を停止
docker stop duo-talk-vllm

# ブラウザで [送信] をクリック
```

**期待動作:**
- ローディング表示が出現（2秒）
- エラーメッセージが表示される
  ```
  ❌ エラー: HTTP 502
  ```

**復旧方法:**
```bash
docker start duo-talk-vllm
# または
./docker/scripts/start-vllm.sh gemma3-12b-int8
```

---

## ✅ テスト結果記録

### テスト実行日時
- **日付:** 2026 年 1 月 9 日
- **時刻:** HH:MM
- **実行者:** Claude Code

### チェックリスト

#### 環境確認
- [ ] Docker (vLLM) が起動している
- [ ] Docker (Florence-2) が起動している
- [ ] Flask API が応答している
- [ ] ブラウザで http://localhost:5173 にアクセス可能

#### GUI 動作確認
- [ ] GUI が起動する（ポート 5173）
- [ ] [Runs] タブに切り替わる
- [ ] 左サイドバーに Chat Mode パネルが表示される

#### Chat Mode 機能確認
- [ ] テキスト入力フィールドが見える
- [ ] [送信] ボタンが見える
- [ ] テキスト入力が可能
- [ ] Enter キーで送信可能
- [ ] 空入力で [送信] ボタンが disabled

#### API 統合確認
- [ ] テキスト送信後、API が呼ばれる（DevTools で確認）
- [ ] API リクエスト: POST /api/unified/run/start-sync
- [ ] API レスポンス: 200 OK（成功）
- [ ] レスポンスに dialogue 配列が含まれている

#### 応答表示確認
- [ ] 2-5秒後に Yana の応答が表示される（緑色）
- [ ] Ayu の応答も表示される（紫色）
- [ ] 時刻が正しく表示される
- [ ] チャット履歴が保持される

#### 複数ターン確認
- [ ] 2 回目のメッセージ送信が可能
- [ ] 前のメッセージ履歴が保持される
- [ ] 新しい応答が追加される

#### エラーハンドリング
- [ ] 空入力で [送信] ボタンが disabled
- [ ] API エラー時にエラーメッセージが表示される

---

## 📊 テスト結果

### 全テスト完了時の記入欄

| テスト項目 | 結果 | 詳細 |
|----------|------|------|
| 環境確認 | ✅/⚠️/❌ | - |
| GUI 起動 | ✅/⚠️/❌ | - |
| Chat Mode 表示 | ✅/⚠️/❌ | - |
| テキスト入力 | ✅/⚠️/❌ | - |
| API 呼び出し | ✅/⚠️/❌ | - |
| 応答表示 | ✅/⚠️/❌ | - |
| 複数ターン | ✅/⚠️/❌ | - |
| エラー処理 | ✅/⚠️/❌ | - |
| **総合評価** | **✅/⚠️/❌** | - |

---

## 🐛 トラブルシューティング

### Issue 1: Chat Mode パネルが表示されない

**原因:** ChatInputPanel.tsx のインポートがない

**確認:**
```bash
grep "import ChatInputPanel" duo-gui/src/App.tsx
```

**対応:**
- App.tsx が正しく修正されているか確認
- ブラウザのキャッシュをクリア (Ctrl+Shift+Delete)
- `npm run dev` で Vite サーバーを再起動

### Issue 2: [送信] ボタンをクリックしても何も起こらない

**原因:** API が応答していない

**確認:**
```bash
curl -X POST http://localhost:5000/api/unified/run/start-sync \
  -H "Content-Type: application/json" \
  -d '{"text": "テスト", "maxTurns": 2}'
```

**期待出力:**
```json
{
  "status": "success",
  "dialogue": [...]
}
```

**対応:**
- Flask API が起動しているか確認: `docker ps`
- vLLM が起動しているか確認: `curl http://localhost:8000/v1/models`
- Flask ログを確認: `tail -f logs/api_server.log`

### Issue 3: チャット履歴が表示されるが、応答がない

**原因:** LLM の推論が失敗している（Claude/Gemini が応答していない）

**確認:**
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RedHatAI/gemma-3-12b-it-quantized.w8a8",
    "messages": [{"role": "user", "content": "こんにちは"}],
    "max_tokens": 100
  }'
```

**対応:**
- vLLM ログを確認: `docker logs duo-talk-vllm | tail -50`
- GPU メモリ不足の可能性: `nvidia-smi`
- vLLM を再起動:
```bash
docker restart duo-talk-vllm
```

### Issue 4: エラーメッセージが表示される（「❌ エラー: HTTP 502」など）

**原因:** バックエンド（Flask または vLLM）が一時的に停止している

**対応:**
```bash
# 1. Docker コンテナの状態確認
docker ps

# 2. 必要に応じて再起動
docker restart duo-talk-vllm
docker restart duo-talk-florence2

# 3. Flask サーバー再起動
./start_gui.sh
```

---

## 📝 テスト実施チェックリスト（最終確認）

テスト実施前の準備確認：

- [ ] docs/ に 4 つの日本語仕様書がある
  - [ ] 検証完了報告書_アーキテクチャ整合性確認.md
  - [ ] Phase0実装仕様書_RUNSタブチャット機能.md
  - [ ] 実装計画書_Phase0.md
  - [ ] 実装完了報告書_Phase0.md

- [ ] ChatInputPanel.tsx が作成されている
  - [ ] ファイル: `duo-gui/src/components/ChatInputPanel.tsx`
  - [ ] 行数: 約150行
  - [ ] 型定義: ChatMessage, ChatInputPanelProps

- [ ] App.tsx が修正されている
  - [ ] 行 12: ChatInputPanel のインポート
  - [ ] 約293行: Chat Mode パネルの統合

- [ ] API エンドポイントが実装されている
  - [ ] エンドポイント: POST /api/unified/run/start-sync
  - [ ] ファイル: server/api_unified.py
  - [ ] 状態: 既存実装（新規作成不要）

---

## 完了後

### テスト結果が全て ✅ の場合
```
Phase 0 実装完全成功 🎉

次のステップ:
→ Phase 1: Provider タブ削除（30分）
→ Phase 2: パフォーマンス最適化（2-3時間）
```

### テスト結果に ⚠️ や ❌ がある場合
```
該当する Issue を確認 → トラブルシューティング実施
デバッグ情報を収集 → 修正実施
```

---

*テストガイド完成。Claude Code での実施をお願いします。*
