# GUI技術スタック設計指示書

AIに同様のGUIアプリケーション実装を指示する際のテンプレート。

---

## 推奨技術スタック

### フロントエンド

| 技術 | バージョン | 用途 |
|------|-----------|------|
| React | 18.x | UIライブラリ |
| TypeScript | 5.x | 型安全な開発 |
| Vite | 5.x | ビルドツール・開発サーバー |
| Tailwind CSS | 3.x | ユーティリティファーストCSS |
| lucide-react | 最新 | アイコンライブラリ |

### バックエンド

| 技術 | バージョン | 用途 |
|------|-----------|------|
| Python | 3.12+ | サーバーサイド言語 |
| Flask | 3.x | REST APIフレームワーク |
| flask-cors | 4.x | CORS対応 |
| httpx | 最新 | 非同期HTTPクライアント |
| PyYAML | 6.x | 設定ファイル読み込み |

### 設定管理

| 形式 | 用途 |
|------|------|
| .env | 環境変数（APIキー、URL等） |
| YAML | アプリケーション設定 |

---

## AIへの指示テンプレート

```markdown
# プロジェクト: [プロジェクト名]

## 技術スタック（必須）
- フロントエンド: React 18 + TypeScript + Vite + Tailwind CSS
- バックエンド: Python 3.12 + Flask REST API
- アイコン: lucide-react
- 通信: fetch API でJSON

## ディレクトリ構成

project/
├── frontend/              # React アプリケーション
│   ├── src/
│   │   ├── components/    # UIコンポーネント
│   │   ├── lib/           # ユーティリティ・型定義
│   │   └── App.tsx        # メインコンポーネント
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   └── vite.config.ts
├── server/                # Flask API
│   └── api_server.py      # APIエンドポイント
├── src/                   # Pythonビジネスロジック
│   └── config.py          # 設定読み込み
├── config/                # 設定ファイル
│   └── settings.yaml
├── .env                   # 環境変数
├── requirements.txt       # Python依存関係
└── start.sh               # 起動スクリプト

## コーディング規約

### TypeScript
- `any` 型は使用禁止
- `unknown` 型も極力避ける
- インターフェースで型を明示的に定義

### Python
- `class` は極力使わない（関数ベースで実装）
- 型ヒントを必ず付ける
- ハードコードを避け、設定ファイルで管理

### 共通
- コンポーネント・関数は機能単位で分割
- 1ファイル300行以内を目安

## API設計

### エンドポイント命名規則
- RESTful: GET/POST/PUT/DELETE
- パス: `/api/v[バージョン]/[リソース]/[アクション]`

### レスポンス形式
```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

### エラーレスポンス
```json
{
  "success": false,
  "data": null,
  "error": "エラーメッセージ"
}
```

## UIコンポーネント設計

### 基本構造
- ヘッダー: タイトル + 更新ボタン
- メインコンテンツ: カード形式で機能を分割
- ステータス表示: アイコン + テキスト
- アクションボタン: 明確なラベル

### Tailwind CSS クラス例
```tsx
// カード
<div className="p-4 bg-white border rounded-lg shadow">

// ボタン（プライマリ）
<button className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">

// ステータスインジケーター
<span className="w-2 h-2 rounded-full bg-green-500" />
```

## 起動スクリプト (start.sh)

```bash
#!/bin/bash
set -e

# バックエンド起動
python3 server/api_server.py &
BACKEND_PID=$!

# フロントエンド起動
cd frontend && npm run dev &
FRONTEND_PID=$!

# 終了処理
trap "kill $BACKEND_PID $FRONTEND_PID" EXIT
wait
```
```

---

## 技術選定の理由

| 技術 | 選定理由 |
|------|----------|
| **Vite** | Create React Appより高速、設定がシンプル、HMRが優秀 |
| **Tailwind CSS** | クラス名だけでスタイル完結、AIが生成しやすい、一貫性が保てる |
| **Flask** | 軽量、学習コスト低、Pythonエコシステムと相性良い |
| **YAML設定** | JSONより読みやすい、コメントが書ける |
| **lucide-react** | アイコン名が直感的、AIが提案しやすい、軽量 |
| **TypeScript** | 型エラーを事前に検出、リファクタリングが安全 |

---

## package.json テンプレート

```json
{
  "name": "project-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "lucide-react": "^0.460.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.10",
    "typescript": "^5.6.2",
    "vite": "^5.4.3"
  }
}
```

---

## requirements.txt テンプレート

```
# Core
python-dotenv>=1.0.1,<2
pydantic>=2.5,<3

# Web Framework
flask>=3.0,<4
flask-cors>=4.0,<5

# HTTP Client
httpx>=0.25.0

# Config
PyYAML>=6.0
```

---

## 注意事項

1. **AIへの指示時のコツ**
   - 具体的なディレクトリ構成を示す
   - 型定義を先に作らせる
   - 小さな機能単位で実装を依頼する

2. **避けるべき構成**
   - Create React App（遅い、設定が複雑）
   - CSS-in-JS（AIが混乱しやすい）
   - 複雑な状態管理ライブラリ（Redux等は小規模では過剰）

3. **推奨する進め方**
   - 1. プロジェクト初期化
   - 2. 型定義（interfaces）
   - 3. APIエンドポイント
   - 4. UIコンポーネント
   - 5. 結合・動作確認

---

*このドキュメントはduo-talkプロジェクトの実装経験に基づいて作成*
