# Phase 0実装仕様書：RUNSタブチャット機能

*作成日: 2026年1月8日*
*実装期間: 1-2時間*
*対象コンポーネント: ChatInputPanel.tsx, App.tsx*

---

## 📌 実装の最小構成

### 現在の状態
```
RUNSタブ
├── ControlPanel.tsx   ← 新規実行ボタン
├── RunList.tsx        ← 実行リスト
└── Timeline           ← 対話表示

❌ テキスト入力 UI がない
❌ チャット機能がない
```

### 実装後の状態
```
RUNSタブ
├── ControlPanel.tsx
├── ChatInputPanel.tsx ← 新規作成：テキスト入力チャット
└── RunList.tsx + Timeline
```

---

## API 仕様

### 使用エンドポイント
**POST /api/unified/run/start-sync**

**リクエスト:**
```json
{
  "text": "こんにちは",
  "maxTurns": 2
}
```

**レスポンス:**
```json
{
  "status": "success",
  "run_id": "run_20260108_120000",
  "dialogue": [
    {
      "turn_number": 0,
      "speaker": "A",
      "speaker_name": "やな",
      "text": "やあ、こんにちは！"
    },
    {
      "turn_number": 1,
      "speaker": "B",
      "speaker_name": "あゆ",
      "text": "こんにちは。本日はどのようなご用でしょう？"
    }
  ],
  "error": null
}
```

---

## 修正計画

### Task 1: ChatInputPanel.tsx 新規作成
- **場所:** `duo-gui/src/components/ChatInputPanel.tsx`
- **機能:** テキスト入力 UI + API 呼び出し
- **依存:** なし（React のみ）
- **所要時間:** 30-40分

### Task 2: App.tsx 修正
- **場所:** `duo-gui/src/App.tsx`
- **修正:** ChatInputPanel をインポート、Runs タブに統合
- **所要時間:** 10-15分

### Task 3: 動作確認
- **確認項目:** RUNSタブでテキスト入力 → 応答表示
- **所要時間:** 15-20分

---

## 実装詳細

### ChatInputPanel.tsx の仕様

**入力:**
- テキスト入力フィールド（単一行）
- [Send] ボタン

**出力:**
- チャット履歴表示（ユーザー・やな・あゆ）
- 時刻表示
- エラーメッセージ
- ローディング表示

**動作:**
1. ユーザーがテキスト入力 → [Send] クリック
2. API 呼び出し（POST /api/unified/run/start-sync）
3. 2-5秒待機（inference 処理）
4. レスポンス受け取り → dialogue 配列を展開
5. Yana/Ayu の応答を表示

**スタイル:**
- 既存の ControlPanel.tsx などと統一
- Tailwind CSS 使用
- レスポンシブ対応

---

## 保持すべき既存機能

### Vision Settings タブ
- **理由:** docs の設定設計を尊重
- **機能:** Ollama モデル選択、Vision パラメータ編集、テスト
- **削除範囲:** **なし**（全て保持）

### SettingsPanel.tsx
- **理由:** Ollama 選択機能が必要
- **機能:** `/api/ollama/select` での動的モデル切り替え
- **削除範囲:** **なし**（全て保持）

### Unified タブ / Live タブ
- **理由:** 既存の実行モードを保持
- **削除範囲:** **なし**（全て保持）

---

## 削除対象（Phase 1）

### Provider タブ
- **理由:** ドキュメント上の要件なし
- **削除範囲:** ProviderPanel.tsx, App.tsx のタブ定義から削除
- **実施時期:** Phase 1（現在は保持）

---

## テスト手順

### 事前確認
```bash
# Docker が起動しているか
docker ps | grep duo-talk

# 期待: vllm, florence2 が Running
```

### GUI 起動
```bash
./start_gui.sh

# 期待:
# Frontend: http://localhost:5173
# Backend:  http://localhost:5000
```

### テストシナリオ

**1. 基本テスト**
- [ ] [Runs] タブをクリック
- [ ] 左サイドバーに「💬 Chat Mode」パネルが表示される
- [ ] テキスト入力フィールドが見える

**2. 入力テスト**
- [ ] 「こんにちは」と入力
- [ ] [Send] をクリック
- [ ] ローディング表示「⏳ Waiting for response...」が出現

**3. 応答テスト**
- [ ] 2-5秒後に Yana/Ayu の応答が表示される
- [ ] 時刻が正しく表示される
- [ ] チャット履歴にユーザー入力も表示される

**4. 複数ターンテスト**
- [ ] さらに別のテキストを入力
- [ ] 前の会話履歴が保持されている
- [ ] 新しい応答が追加される

**5. エラーハンドリング**
- [ ] 空文字で [Send] をクリック → ボタンが disabled になる
- [ ] API が失敗（Docker 停止など） → エラーメッセージ表示

---

## 技術仕様

### React コンポーネント構成
```typescript
ChatInputPanel
├── State: input (string)
├── State: messages (ChatMessage[])
├── State: loading (boolean)
├── State: error (string | null)
├── Effect: scrollToBottom
├── Handler: handleSend
├── Handler: handleKeyPress
└── JSX: Input + History + Send Button
```

### ChatMessage インターフェース
```typescript
interface ChatMessage {
  speaker: 'user' | 'yana' | 'ayu'
  text: string
  time: string
}
```

### API 呼び出し形式
```typescript
const response = await fetch(
  `${apiBase}/api/unified/run/start-sync`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: userMessage.text,
      maxTurns: 2
    })
  }
)
```

### レスポンス解析
```typescript
if (result.dialogue && Array.isArray(result.dialogue)) {
  for (const turn of result.dialogue) {
    const speaker: 'yana' | 'ayu' = 
      turn.speaker === 'A' ? 'yana' : 'ayu'
    messages.push({
      speaker,
      text: turn.text,
      time: responseTime
    })
  }
}
```

---

## Tailwind CSS クラス（既存パターンから採用）

```typescript
// コンテナ
className="space-y-3 h-full flex flex-col"

// ボタン
className="px-4 py-2 bg-blue-600 text-white rounded-lg ... disabled:bg-slate-400"

// 入力フィールド
className="flex-1 px-3 py-2 border border-slate-300 rounded-lg ... disabled:bg-slate-200"

// メッセージ表示
className="p-2 rounded text-xs bg-blue-100 text-blue-900"

// ローディング
className="p-2 bg-yellow-100 text-yellow-800 rounded text-xs"

// エラー
className="p-2 bg-red-100 text-red-700 rounded text-xs"
```

---

## デバッグのヒント

### API 呼び出しの確認
```javascript
// ブラウザコンソール (F12 → Console)

console.time('Chat Response')
// [Send] をクリック
console.timeEnd('Chat Response')

// 期待: Chat Response: 2345ms（2-5秒）
```

### ネットワークの確認
```
F12 → Network タブ
[Send] をクリック
↓
POST /api/unified/run/start-sync が表示される
↓
Response に dialogue 配列が含まれているか確認
```

### React DevTools（オプション）
```bash
# Props の確認
ChatInputPanel コンポーネント選択
→ props に apiBase が正しく渡されているか
→ state に messages が更新されているか
```

---

## 完了基準

実装が完了したと見なす条件：

- [ ] `ChatInputPanel.tsx` ファイルが存在する
- [ ] `App.tsx` で ChatInputPanel をインポートしている
- [ ] `App.tsx` の Runs タブに ChatInputPanel が統合されている
- [ ] ブラウザで [Runs] タブをクリックすると Chat Mode パネルが表示される
- [ ] テキストを入力して [Send] をクリック可能
- [ ] 2-5秒後に Yana/Ayu の応答が表示される
- [ ] エラーハンドリングが動作する（空入力で disabled など）

---

## Phase 0 実装完了後の状況

```
✅ RUNSタブでテキスト入力チャットが動作
✅ 既存の Vision Settings は保持
✅ GUI レイアウトは保持（最小限の変更）

次のフェーズ:
→ Phase 1: Provider タブ削除、GUI 整理
→ Phase 2: パフォーマンス最適化
```

---

*実装仕様書完了。以下のタスクを Filesystem で実装してください。*
