# duo-talk

二人の AI キャラクターの掛け合いを演出する最小〜拡張システム。
Step1(MVP) → Step2(演出) → Step3(RAG) の順に段階実装し、ログと簡易GUIで“効き”を見える化します。

**主な機能**

- A/B 二人の AI キャラが交互に会話（最大ターンで終了）
- 制約の強制: 5文以内・合いの手最大1回（再生成＋最終トリム）
- Step2: ビート配布（BANter/PIVOT/PAYOFF）、カット合図（TAG）
- Step3: RAG（canon/lore/pattern）を各ターン最大1件ずつ注入
- ログ: JSONL（run_id 付き）。検証用の選定ログ・プロンプト末尾も出力
- 簡易GUI: ラン開始、タイムライン、RAG パネル、影響度（cov%）


**ディレクトリ**

- `duo_chat_mvp.py` … Step1: 最小の交互会話＋制約
- `duo_chat_entertain.py` … Step2/3: ビート配布、RAG 注入、ログ拡張
- `persona/char_a.system.txt` / `persona/char_b.system.txt` … キャラのSystemプロンプト
- `rag_data/**` … RAGの元データ（canon/lore/pattern）
- `server/main.py` / `server/static/index.html` … FastAPI + 簡易GUI（/ui）
- `scripts/check_leak.py` … 演出ノート/ヒント漏れ検出
- `scripts/rag_influence_report.py` … RAGの“効き”の簡易スコア
- `tests/` … ステップ別の最小テスト


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


**Step2: Entertainment（ビート/カット）**

```
python duo_chat_entertain.py --max-turns 8 --model gemma3:12b --topic "駅前イベントの小型自走車" --seed 42
```

- `beats/beat_policy.yaml` を読み込み（無ければ安全デフォルト）
- 3ターンごと `PIVOT`、6ターン以降 `PAYOFF`、最終 `TAG`
- 合意/総括ワードの検出→一回だけ再生成→残れば弱め表現に置換
- ループ検知（先頭一致＋8-gram重複率）→ 脱出の一行を追記
- すべての出力は `hard_enforce()` → `sanitize()` 

公開API（テスト用）:

- `load_policy(path="beats/beat_policy.yaml") -> dict`
- `pick_beat(turn, policy=None) -> str`
- `pick_cut(turn, max_turns=8, policy=None) -> str|None`
- `need_finish(text) -> bool`


**Step3: RAG（canon/lore/pattern）**

- 各ターンで `rag/rag_min.py` の `retrieve()` を用い、以下を最大1件ずつ注入:
  - canon（A/B優先）/ lore / pattern（PAYOFFでは pattern を先頭に）
- ヒントはプロンプト末尾に `［内蔵ヒント］…（台詞に出さない）` で注入（台詞への漏れは `sanitize()` が除去）
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


**簡易GUI（最小版）**

FastAPI + SSE + 静的HTMLで、ランの起動とライブ可視化が可能です。

```
uvicorn server.main:app --host 127.0.0.1 --port 5179 --reload
# または: python server/main.py

# ブラウザ
http://127.0.0.1:5179/    # API インデックス
http://127.0.0.1:5179/ui  # 簡易GUI（Start / Runs / Timeline / RAG Panel / cov%）
```

API:

- `POST /api/run/start` … 本体プロセス起動（body: topic/model/maxTurns/seed/noRag）。best-effort で `run_id` を返却
- `GET /api/run/list` … 直近の run 一覧
- `GET /api/run/stream?run_id=...` … SSE（履歴を最初に再生→tail で追従）


**スクリプト**

- 演出ノート/ヒント漏れ検出:

```
python scripts/check_leak.py runs/duo_runs.jsonl
```

- 影響度（cov）レポート（token/chargram/mix）:

```
python scripts/rag_influence_report.py runs/duo_runs.jsonl --mode mix
```


**テスト**

```
pytest -q
```


**トラブルシュート**

- モデル未検出: `.env` の `OPENAI_MODEL` が実モデル名（Ollama の `ollama list` と一致）か確認
- 5文を超える: enforce() + hard_enforce() で最終的にトリムします。`OPENAI_TEMPERATURE` を少し下げると安定
- Timeline が空: `/api/run/stream` は履歴再生→tailに対応。Run選択/フィルタ設定/ログ更新を確認
- ルートが 404: `uvicorn server.main:app --reload` での起動を推奨。`python server/main.py` でも `/` と `/ui` が動作


**ライセンス**

本リポジトリ内ファイルのライセンスは各ファイルヘッダや同梱 LICENSE に従います（未記載の場合は私的利用の範囲で扱ってください）。
