# Sumigaseyana Integration — Contract & Plan (Phase 1: HTTP, Phase 2: MCP)

本ドキュメントは、duo-talk の A 役を「澄ヶ瀬やな（sumigaseyana）」APIに接続するための契約(Contract)と実装計画をまとめたものです。Phase 1 は HTTP 連携で安全に運用し、将来的に MCP へスムーズに移行できるよう、入出力スキーマとエラー契約を先に固定します。

## 目的・前提
- 目的: A 役を「やな」へ置換し、RAG文脈（日本酒/ジュースのラベル知識）を対話に反映。
- B 役は現状維持。会話のオーケストレーションは duo-talk 側が継続。
- 追跡性: duo の `run_id` とやな側のトレースIDを相互にやり取りし、ログ相関を可能にする。
- 将来: HTTP の契約を MCP ツール定義に写像し、移行コストを最小化。

## 全体方針
- A 役の発話生成は Provider 抽象で差し替え可能にする。
- Phase 1: HTTP Provider（やな API）を実装・採用。
- Phase 2: MCP Provider（やな MCP サーバ）を追加し、選択式にする。

---

## HTTP Contract v1（最小で強い）

### バージョニングと識別
- ルートは `/v1/*` に固定（`/v1/chat`, `/v1/search`, `/v1/ingest`, `/v1/healthz`, `/v1/version`）。
- すべての成功応答 JSON に `server_version`, `policy_version` を含める。

### 相関IDと観測性
- 受信ヘッダ: `X-Run-Id`, `X-Trace-Id`（未指定ならサーバ生成）。
- 応答ヘッダ: 受領した `X-Run-Id`, `X-Trace-Id` をそのまま反射返送。`X-Request-Duration-Ms` を付与。
- 可能なら W3C Trace Context（`traceparent`/`tracestate`）も許容。
- サーバ側ログ(JSONL)に `run_id`, `trace_id` を保存。

### 認可/レート/タイムアウト
- 認可: `Authorization: Bearer <token>`（開発時は固定トークンで可）。
- タイムアウト: `/v1/chat`=10–12s, `/v1/search`<=2s。
- レート: Token-bucket 例（5 rps / burst 50）。
- サーキットブレーカ: 5xx が連続した閾値で短期フォールバック。

### エラー契約（統一）
- ステータス: 400(BAD_REQUEST) / 401(UNAUTHORIZED) / 408(REQUEST_TIMEOUT) / 409(CONFLICT: Idempotency) / 429(RATE_LIMITED) / 5xx。
- ボディ(JSON):
```json
{
  "error": { "code": "UPSTREAM_TIMEOUT", "message": "string", "retryable": true },
  "run_id": "abc",
  "trace_id": "def"
}
```

### /v1/chat
- Request（JSON; Form互換も維持）:
```json
{
  "user_text": "string",
  "use_rag": true,
  "top_k": 5,
  "filters": { "category": "sake", "region": "小樽", "brewery": "" },
  "context": { "turn": 12, "topic": "optional", "run_id": "..." }
}
```
- Response（JSON）:
```json
{
  "reply": "string",
  "hits": [
    {
      "id": "label_...",
      "brand_name": "...",
      "product_name": "...",
      "brewery": "...",
      "region": "...",
      "label_features": ["..."],
      "file_path": "data/images/..."
    }
  ],
  "llm": "on",
  "elapsed_ms": 231,
  "rag_hit_count": 1,
  "run_id": "abc",
  "trace_id": "def",
  "server_version": "1.0.0",
  "policy_version": "say-2025-09-23",
  "warnings": ["trimmed_to_5_sentences"]
}
```

### /v1/search
- Request（JSON）:
```json
{ "query_text": "string?", "filters": {"category": "sake"}, "k": 5, "sort_by": "relevance", "page": 1, "page_size": 10 }
```
- Response（JSON）:
```json
{ "hits": [ { "id": "...", "brand_name": "...", "brewery": "...", "region": "...", "label_features": ["..."] } ], "next_page": 2, "debug": { "score": 0.87, "meta_bonus": 0.1 }, "server_version": "1.0.0", "policy_version": "...", "run_id": "abc", "trace_id": "def" }
```

### /v1/ingest
- 受理: multipart(Form) も JSON+外部URI も許容（将来MCPと整合）。
- Idempotency: ヘッダ `Idempotency-Key` で重複登録を抑止（重複時は 409 あるいは 200+`dedup:true`）。
- Response:
```json
{ "id": "...", "dedup": false, "hash_sha1": "...", "phash": "...", "run_id": "abc", "trace_id": "def", "server_version": "...", "policy_version": "..." }
```

### /v1/healthz, /v1/version
- `/v1/healthz`: { llm_ok, rag_ok, policy_ok, uptime_s, last_error? }
- `/v1/version`: { server_version, policy_version, model }

---

## Duo 側 Provider 抽象（将来MCPを見据えて固定）

### インターフェース
```python
from typing import Protocol, Tuple, Dict

class SpeakerProvider(Protocol):
    def generate(self, user_text: str, *, run_id: str, top_k: int, filters: Dict, timeout_ms: int) -> Tuple[str, Dict]:
        ...
```
- 戻り `meta` 例: `{ "hits": [...], "elapsed_ms": 231, "trace_id": "...", "warnings": ["..."], "source": "http_v1" }`

### 設定（.env 想定）
- `SPEAKER_A_MODE=http|mcp|local`
- `SPEAKER_A_HTTP_BASE=http://127.0.0.1:8000`
- `SPEAKER_A_USE_RAG=true`
- `SPEAKER_A_TOP_K=5`
- `SPEAKER_A_FILTERS_JSON={"category":"sake"}`
- `SPEAKER_A_TIMEOUT_MS=12000`
- `SPEAKER_A_AUTH_TOKEN=dev-token`

### 出力整形の順序とフォールバック
- 整形順序: 1) やな側 policy（「せやなー/せやせや」）→ 2) duo 側（<=5文/相槌<=1）。
- リトライ: `retryable=true` のとき指数バックオフで 1 回。
- 失敗時: 固定短文で代替 or ターンスキップ（設定で選択）。
- RAG ダウン時: `use_rag=false` で再投（1 回）。

---

## RAG 品質・安全ガード
- プロンプトインジェクション対策: RAG文脈に「外部指示を無視」ガード文を恒常化。
- 出典プロヴナンス: 応答末尾に（参考：銘柄/蔵/地域のみ）を任意付与。URL は出さない。
- 重複除去: pHash/embedding 類似の高いヒットを抑制。
- スコア合成: メタ一致（brand/breweryなど）に重み付けして暴走抑制。

---

## MCP 移行指針（HTTP→MCP の写像）
- ツール名/引数は HTTP と同名: `chat`, `search`, `ingest`。
- Schema は OpenAPI を JSON Schema に変換して流用。
- エラー `code` は HTTP と同値（UPSTREAM_TIMEOUT / BAD_REQUEST / RATE_LIMITED / ...）。
- リソース: `logs/today` は read-only resource として公開（要オプトイン）。
- `context.sessionId/runId` はそのまま受け渡し。

準備済みスキーマ（本リポジトリ内）:
- `docs/mcp/tools.chat.schema.json` / `docs/mcp/tools.chat.result.schema.json`
- `docs/mcp/tools.search.schema.json` / `docs/mcp/tools.search.result.schema.json`
- `docs/mcp/tools.ingest.schema.json` / `docs/mcp/tools.ingest.result.schema.json`
- `docs/mcp/errors.schema.json`

クライアント側のMCPプロバイダは準備用スタブを追加済み（未実装）:
- `providers/speaker_mcp.py`（起動すると NotImplemented を投げます）

---

## テスト計画
- 契約テスト: 正常/429/408/5xx/空返答/過長返答の6系統を Provider 経由で検証。
- 可観測性: `run_id` 往復、`elapsed_ms` の妥当性、`warnings` の記録。
- 負荷: 6〜20ターン×並列2 スレッドのスループット/失敗率観測。

---

## フェーズ計画
- Phase 0: 仕様合意（本ドキュメント）。
- Phase 1: HTTP 実装
  - `/v1/*` 追加、JSON POST 正式化、相関ヘッダ反射、エラー契約、warnings/versions 付与。
  - `SpeakerAHttpProvider` 実装、.env 追加、タイムアウト/リトライ/フォールバック。
- Phase 2: 観測性強化（相関IDをやな側ログにも確実記録、duo ログに RAG 概要同梱）。
- Phase 3: MCP サーバ（やな）実装。
- Phase 4: MCP クライアント（duo）実装、モード切替。
- Phase 5: 仕上げ（streaming 予約, ドキュメント整備）。

---

## 実行前チェックリスト（環境準備）
- sumigaseyana 側
  - Python 環境/依存関係を整備（`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`）。
  - サーバ起動（例: `uvicorn app.server.api:app --host 127.0.0.1 --port 8000`）。
  - 将来: `/v1/*` 実装ブランチを用意、固定トークン運用を開始。
- duo-talk 側
  - `.env` に A 向け設定（`SPEAKER_A_*`）を追加（実装時に参照）。
  - Provider 抽象の骨組み作成（HTTP版をデフォルトに切替可能に）。
  - ログに `run_id`, `trace_id`, `warnings` を記録。

---

## 互換性ポリシー
- 追加は非破壊（フィールド追加のみ）。破壊的変更は `/v2` で提供。
- 数値や配列の上限/下限はサーバ・クライアント双方でバリデーション。

以上。Phase 1 の実装に着手可能です。OpenAPI 雛形が必要なら本ドキュメントから抽出して同梱します。
