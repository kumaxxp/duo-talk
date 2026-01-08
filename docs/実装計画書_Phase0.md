# 修正実装計画書

*作成日: 2026年1月8日*
*実装開始日: 2026年1月8日*
*期間見積: 1-2時間*

---

## 実装ロードマップ

### Task 1: ChatInputPanel.tsx 実装（40分）
- **ファイル:** duo-gui/src/components/ChatInputPanel.tsx
- **内容:** React コンポーネント新規作成
- **担当:** Filesystem:write_file

### Task 2: App.tsx 修正（15分）
- **ファイル:** duo-gui/src/App.tsx
- **内容:** ChatInputPanel インポート + Runs タブ統合
- **担当:** Filesystem:edit_file

### Task 3: 動作確認（20分）
- **方法:** ブラウザで GUI 起動
- **確認:** RUNSタブ チャット機能 → Claude Code でテスト

---

## Task 1 詳細：ChatInputPanel.tsx 実装

### ファイル情報
- **作成先:** C:\work\duo-talk\duo-gui\src\components\ChatInputPanel.tsx
- **ベースとなるコンポーネント:** SettingsPanel.tsx, ControlPanel.tsx（スタイル参考）
- **依存:** React, lucide-react（アイコン）

### 実装内容
完全な React コンポーネント実装

**主な機能:**
1. テキスト入力フィールド + [Send] ボタン
2. チャット履歴表示
3. API 呼び出し（POST /api/unified/run/start-sync）
4. エラーハンドリング
5. ローディング表示

---

## Task 2 詳細：App.tsx 修正

### 修正内容

#### 2-1. ChatInputPanel のインポート追加
```typescript
// 既存のインポート後に以下を追加
import ChatInputPanel from './components/ChatInputPanel'
```

#### 2-2. Runs タブのレイアウト修正

**現在のコード（例）:**
```typescript
{activeTab === 'runs' && (
  <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
    <section className="md:col-span-1 space-y-3">
      {/* ControlPanel など既存コンポーネント */}
    </section>
    <section className="md:col-span-3">
      {/* Timeline など */}
    </section>
  </div>
)}
```

**修正後のコード（イメージ）:**
```typescript
{activeTab === 'runs' && (
  <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
    <section className="md:col-span-1 space-y-3">
      {/* 既存: New Run */}
      <div className="p-4 bg-white rounded-lg shadow">
        <h2 className="font-medium mb-2">New Run</h2>
        <ControlPanel apiBase={API} onStarted={...} />
      </div>

      {/* 新規: Chat Mode */}
      <div className="p-4 bg-white rounded-lg shadow">
        <ChatInputPanel apiBase={API} onSendComplete={() => {}} />
      </div>

      {/* 既존: RunList など他のコンポーネント */}
      {/* ... */}
    </section>
    <section className="md:col-span-3">
      {/* Timeline など */}
    </section>
  </div>
)}
```

---

## Task 3 詳細：動作確認

### 事前準備
```bash
# 1. Docker が起動しているか確認
docker ps | grep duo-talk

# 期待: duo-talk-vllm と duo-talk-florence2 が Running

# 2. GUI を起動
./start_gui.sh

# 期待:
# 🔧 Starting Backend API Server...
# 🎨 Starting Frontend (Vite)...
# 📌 Frontend: http://localhost:5173
```

### 確認手順

| 番号 | 項目 | 期待結果 |
|------|------|--------|
| 1 | ブラウザで http://localhost:5173 にアクセス | GUI が表示される |
| 2 | [Runs] タブをクリック | Runs タブが開く |
| 3 | 左サイドバーを確認 | 「💬 Chat Mode」パネルが見える |
| 4 | テキスト入力フィールドに「こんにちは」と入力 | テキストが入力される |
| 5 | [Send] ボタンをクリック | ローディング表示が出現 |
| 6 | 2-5秒待機 | API が実行される |
| 7 | 応答を確認 | Yana/Ayu の応答が表示される |
| 8 | チャット履歴を確認 | ユーザー入力 + 応答が保存されている |

### 失敗時の対応

| エラー | 原因 | 対策 |
|--------|------|------|
| 404 API not found | /api/unified/run/start-sync が見つからない | api_unified.py が登録されているか確認 |
| 502 Bad Gateway | vLLM/Florence-2 が起動していない | `docker ps` で確認、再起動 |
| チャット履歴が表示されない | React コンポーネント エラー | ブラウザコンソール (F12) を確認 |
| API が 200 だが応答が空 | UnifiedPipeline エラー | Flask ログを確認 |

---

## 実装スケジュール

```
時間      実装内容                 所要時間
────────────────────────────────────────
10:00    Task 1: ChatInputPanel       40分
         実装開始
         
10:40    Task 2: App.tsx 修正        15分
         実装開始
         
10:55    Task 3: 動作確認           20分
         ブラウザテスト開始
         
11:15    完了予定
```

---

## 実装時の注意事項

### コーディング規約
- **言語:** TypeScript
- **スタイル:** Tailwind CSS（既存パターン採用）
- **ネーミング:** キャメルケース（JavaScript 標準）
- **型定義:** interface を使用

### 既存コンポーネントとの整合性
- SettingsPanel.tsx のスタイルを参考
- Tailwind クラスは既存パターンから採用
- lucide-react アイコン を使用（既存と統一）

### API 呼び出し
- エラーハンドリング必須
- try/catch で例外キャッチ
- エラーメッセージは日本語

### パフォーマンス
- useRef で無限ループ回避
- useCallback で関数をメモ化（必要に応じて）
- スクロール自動化（messagesEndRef）

---

## 完了チェックリスト

### Task 1 完了基準
- [ ] ChatInputPanel.tsx ファイルが作成されている
- [ ] React.FC<ChatInputPanelProps> として定義
- [ ] handleSend 関数が実装されている
- [ ] API 呼び出しが実装されている
- [ ] JSX レンダーが実装されている

### Task 2 完了基準
- [ ] ChatInputPanel をインポート
- [ ] Runs タブ内に ChatInputPanel コンポーネント配置
- [ ] API プロップスが正しく渡されている
- [ ] onSendComplete コールバック設定

### Task 3 完了基準
- [ ] ブラウザで [Runs] タブに Chat Mode パネルが表示される
- [ ] テキスト入力で [Send] が有効になる
- [ ] [Send] クリック後に API が呼ばれる
- [ ] 応答が表示される
- [ ] エラーハンドリングが動作する

---

## 次のステップ（Phase 0 完了後）

### Phase 1: GUI タブ整理（30分）
```
- Provider タブ削除
- Navigation を 4タブに整理
- その他レイアウト調整
```

### Phase 2: パフォーマンス最適化（2-3時間）
```
- テキスト入力時の VLM/Florence スキップ
- 並列化実装
- ストリーミング化
```

---

*実装計画書完成。以下は Filesystem で実装します。*
