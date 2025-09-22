# duo-talk

二人の AI キャラクターの掛け合いを演出する最小〜拡張システム。
MVP → 演出 → RAG → 評価 の順に小さく積み上げ、ログとGUIで“効き”を見える化します。

**主な機能**

- A/B が交互に会話（最大ターンで終了）。制約の強制: 最大5文・合いの手最大1回
- ディレクター機能: ビート配布（3ビート or 短縮7ビート）、カット合図（TAG）
- 役作りの隠しステップ（role_prep）＋ 軽量リフレクト（reflect）を毎ターン実行
- RAG（canon/lore/pattern）を各ターン最大1件ずつ注入。ビート別で注入順を切替
- ログ: JSONL（run_id 付き）。`director`/`rag_select`/`prompt_debug`/`reflect` を出力
- GUI: ラン開始、タイムライン、RAG パネル、影響度（cov%）、RAG Score(F1/Cite)、style遵守率


**ディレクトリ**

- `duo_chat_mvp.py` … 最小の交互会話＋制約
- `duo_chat_entertain.py` … ビート／RAG 注入、役作り、リフレクト、ログ拡張
- `persona/char_a.system.txt` / `persona/char_b.system.txt` … コア/スタイル/境界の短文化（三項目）
- `policy/beats_short.yaml` … 7ビート（短縮版）の定義（任意）
- `rag_data/**` … RAGデータ（canon/lore/pattern）。`scripts/ingest.py` で投入
- `rag/rag_min.py` … 依存最小のRAG（rapidfuzzベースのスコアリング）
- `scripts/ingest.py` / `scripts/rag_gc.py` … 取り込み＆GC候補出し
- `scripts/rag_eval.py` … オフライン評価（F1/Citation）。`runs/rag_eval_summary.json` を出力
- `metrics/quick_check.py` … 文数/合いの手から style遵守率を算出
- `server/main.py` … FastAPI（SSE配信＋API）。`/ui` に最小ビュー
- `duo-gui/**` … React製の開発用GUI（ヘッダにRAG Scoreとstyle遵守率）


**インストール**

```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements-dev.txt
```


**.env（例）**

`.env.example` をコピーして編集:

```
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=not-needed
OPENAI_MODEL=gemma3:12b
MAX_TURNS=8
```

Ollama/LM Studio/OpenAI などの実環境に合わせて `OPENAI_MODEL` / `OPENAI_BASE_URL` を調整してください。


**Step1: MVP の使い方**

```
python duo_chat_mvp.py --max-turns 8 --model gemma3:12b --topic "駅前イベントの小型自走車"
```

公開API（テスト・再利用用）:

- `too_many_sentences(text, limit=5) -> bool`
- `too_many_aizuchi(text, limit=1) -> bool`
- `is_loop(prev, curr) -> bool`
- `call(model, system, user, temperature=0.7, max_tokens=400) -> str`
- `enforce(text, system, user, model, ...) -> str`（再生成で制約矯正）
- `hard_enforce(text, sent_limit=5, aizuchi_limit=1) -> str`（最終トリム）
- `sanitize(text) -> str`（演出ノート/危険表現の緩和）


**Step2: Entertainment（ビート/カット/役作り/リフレクト）**

```
python duo_chat_entertain.py --max-turns 8 --model gemma3:12b --topic "駅前イベントの小型自走車" --seed 42
```

- `beats/beat_policy.yaml`（3ビート） or `policy/beats_short.yaml`（7ビート）があれば使用
- 3ビート: 3ターンごとPIVOT・6ターン以降PAYOFF・最終TAG
- 7ビート: Setup → Theme Stated → Fun&Games → Midpoint(PIVOT) → BadTurns → Aha(PAYOFF準備) → Finale(TAG)
- 役作り（role_prep）を毎ターンの直前に1行生成（台詞には出さない）。軽量リフレクト（reflect）も生成
- 合意/総括ワードの検出→一回だけ再生成→残れば弱め表現に置換
- ループ検知（先頭一致＋8-gram重複率）→ 脱出の一行を追記
- すべての出力は `hard_enforce()` → `sanitize()`（［演出ノート］/［内蔵ヒント］/［役作り］/［リフレクト］は除去）

公開API（テスト用）:

- `load_policy(path="beats/beat_policy.yaml") -> dict`
- `pick_beat(turn, policy=None) -> str`
- `pick_cut(turn, max_turns=8, policy=None) -> str|None`
- `need_finish(text) -> bool`


**Step3: RAG（canon/lore/pattern）**

- 各ターンで `rag/rag_min.py` の `retrieve()` を用い、以下を最大1件ずつ注入:
  - canon（A/B優先）/ lore / pattern（PAYOFFでは pattern を先頭に）
- ビート別注入順: Fun&Games は `lore → canon → pattern`、Finale/PAYOFF は `pattern` 最優先
- ヒントはプロンプト末尾に `［内蔵ヒント］…（台詞に出さない）` として注入（sanitizeで除去）
- `rag_select` イベントで選定結果（path/preview）をログ

`rag/rag_min.py`:

- `build(data_dir="rag_data", force=False)` … データ読み込み＋軽量インデックス構築
- `retrieve(query, filters=None, top_k=8) -> list[(text, meta)]`
- `clean_preview()` … フロントマター剥がし＋最初の非空行をプレビューに採用


**ログ（JSONL, runs/duo_runs.jsonl）**

- すべてのイベントに `run_id` を付与。
- 主なイベント:
  - `run_start` / `run_end` … モード・topic・model を含む
  - `director` … `{"turn": n, "beat": "PIVOT", "cut_cue": null}`
  - `rag_select` … `canon/lore/pattern` の `path/preview`
  - `reflect` / `review` … リフレクトと遅延レビュー（レビューはダミー）
  - `prompt_debug` … LLM 呼び直前のプロンプト末尾（500字）
  - `speak` … `speaker(A/B), turn, beat(optional), text`
  - `llm_call` / `llm_response` / `error`

抜粋表示の例:

```
RID=$(tac runs/duo_runs.jsonl | jq -r 'select(.event=="run_start")|.run_id' | head -1)
jq -r --arg RID "$RID" '
  if .run_id==$RID and .event=="rag_select" then
    "[R] t=\(.turn) " + ([(.canon.path//"-"), (.lore.path//"-"), (.pattern.path//"-")] | join(" | ")) + " :: " +
    ([(.canon.preview//"-"), (.lore.preview//"-"), (.pattern.preview//"-")] | join(" | "))
  elif .run_id==$RID and .event=="director" then
    "[D] t=\(.turn) beat=\(.beat) cut=\(.cut_cue//"-")"
  elif .run_id==$RID and .event=="speak" then
    "[S] \(.speaker) t=\(.turn) " + (.text|gsub("\n";" ")|.[0:80]) + "…"
  elif .run_id==$RID and .event=="prompt_debug" then
    "[P] " + (.prompt_tail|gsub("\n";" ")|.[-180:])
  else empty end' runs/duo_runs.jsonl
```


**GUI**

FastAPI + SSE + 静的HTMLで、ランの起動とライブ可視化が可能です。

```
uvicorn server.main:app --host 127.0.0.1 --port 5179 --reload
# または: python server/main.py

# ブラウザ
http://127.0.0.1:5179/    # API インデックス
http://127.0.0.1:5179/ui  # 簡易GUI（Start / Runs / Timeline / RAG Panel / cov%）
```

API:

- `POST /api/run/start` … 本体プロセス起動（body: topic/model/maxTurns/seed/noRag）
- `GET /api/run/list` … 直近の run 一覧
- `GET /api/run/events?run_id=...` … 指定 run の全イベント
- `GET /api/run/stream?run_id=...` … SSE（履歴→tail）
- `GET /api/run/style?run_id=...` … style遵守率（文数/合いの手）
- `GET /api/rag/score` … オフライン評価のサマリ（F1/CitationRate）


**スクリプト**

- 取り込み（RAG ingest）:

```
python scripts/ingest.py --in raw_docs --out rag_data
```

- GC候補リスト（CSV; dry-run）:

```
python scripts/rag_gc.py  # -> runs/rag_gc_candidates.csv
```

- RAG評価（F1/Citation; サマリは GUI ヘッダに反映）:

```
python scripts/rag_eval.py --qa eval/qa.jsonl  # -> runs/rag_eval_summary.json
```


**テスト**

```
pytest -q
```


**トラブルシュート**

- RAG Score が 0% のまま: `scripts/rag_eval.py` を実行し、`runs/rag_eval_summary.json` を生成。GUI は10秒ごとに再取得
- grep でイベントが見つからない: JSONは `"event": "xxx"` のようにコロン後にスペース。`grep -E '"event":\s*"rag_select"'` を使用
- モデル未検出: `.env` の `OPENAI_MODEL` が実モデル名（Ollama の `ollama list` 等と一致）か確認
- 5文を超える: `enforce()` + `hard_enforce()` で最終トリム。`OPENAI_TEMPERATURE` を少し下げると安定
- Timeline が空: `/api/run/stream` は履歴→tail。Run選択/フィルタ設定/ログ更新を確認
- ルートが 404: `uvicorn server.main:app --reload` での起動を推奨（`python server/main.py` でも `/` と `/ui` が動作）


**ライセンス**

本リポジトリ内ファイルのライセンスは各ファイルヘッダや同梱 LICENSE に従います（未記載の場合は私的利用の範囲で扱ってください）。
