import json
import asyncio
import subprocess
from pathlib import Path
from typing import AsyncIterator, Dict, List, Iterable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


LOG = Path("runs/duo_runs.jsonl")
RAG_EVAL_SUMMARY = Path("runs/rag_eval_summary.json")
app = FastAPI(title="Duo Talk Backend", version="0.1.0")

# Allow local dev frontends (vite default port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/run/start")
async def start_run(p: Dict):
    """Start a new entertain run as a subprocess.

    Body example: {"topic": str, "model": str, "maxTurns": int, "seed": int, "noRag": bool}
    """
    cmd = ["python", "duo_chat_entertain.py", "--max-turns", str(p.get("maxTurns", 8))]
    if (m := p.get("model")):
        cmd += ["--model", str(m)]
    if (t := p.get("topic")):
        cmd += ["--topic", str(t)]
    if (s := p.get("seed")) is not None:
        cmd += ["--seed", str(s)]
    if p.get("noRag"):
        cmd += ["--no-rag"]

    # Launch detached (silence child output to keep server logs clean)
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # Best-effort: return latest run_id if it appears quickly
    rid = None
    try:
        for _ in range(10):  # ~2s
            await asyncio.sleep(0.2)
            rows = await _list_runs()
            if rows:
                rid = rows[0].get("run_id")
                break
    except Exception:
        pass
    return JSONResponse({"ok": True, "run_id": rid})


def _iter_jsonl_all() -> Iterable[Dict]:
    if LOG.exists():
        with LOG.open(encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except Exception:
                    continue


async def _tail_jsonl(run_id: str) -> AsyncIterator[Dict]:
    """Async tail of LOG file yielding parsed JSON lines for a run_id.

    This is a simple polling tail; sufficient for local dev.
    """
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.touch(exist_ok=True)
    # Replay existing history first
    for j in _iter_jsonl_all():
        if j.get("run_id") == run_id:
            yield j
    # Then tail from end
    with LOG.open(encoding="utf-8") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                await asyncio.sleep(0.2)
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("run_id") != run_id:
                continue
            yield j


@app.get("/api/run/stream")
async def stream(run_id: str):
    async def gen():
        async for j in _tail_jsonl(run_id):
            ev = j.get("event", "message")
            yield f"event: {ev}\n"
            yield f"data: {json.dumps(j, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/run/list")
async def run_list():
    rows = await _list_runs()
    return JSONResponse(rows)


async def _list_runs() -> List[Dict]:
    found: Dict[str, Dict] = {}
    for j in _iter_jsonl_all():
        rid = j.get("run_id")
        if not rid:
            continue
        if j.get("event") == "run_start":
            found[rid] = {
                "run_id": rid,
                "topic": j.get("topic"),
                "model": j.get("model"),
                "startedAt": j.get("ts"),
            }
        if rid not in found:
            found[rid] = {"run_id": rid}
        found[rid]["lastEventAt"] = j.get("ts")
    rows: List[Dict] = sorted(found.values(), key=lambda x: x.get("lastEventAt") or "", reverse=True)[:20]
    return rows


@app.get("/api/run/events")
async def run_events(run_id: str):
    """Return all events for a given run_id in order."""
    events: List[Dict] = []
    for j in _iter_jsonl_all():
        if j.get("run_id") == run_id:
            events.append(j)
    return JSONResponse(events)


@app.get("/api/run/style")
async def style_rate(run_id: str):
    """Compute style adherence rate for a run: sentences<=5 and aizuchi<=1.

    Very lightweight proxy for persona style conformance.
    """
    import re
    sent_split = re.compile(r"[。．.!?！？]+")
    aizuchi_words = ["うん","へぇ","へえ","なるほど","そうそう","ふむ","ええ","はい","そっか","そうか","たしかに","なる"]
    def sentence_count(txt: str) -> int:
        parts = [s for s in sent_split.split(txt or "") if s.strip()]
        return len(parts)
    def aizuchi_count(txt: str) -> int:
        t = txt or ""
        return sum(t.count(w) for w in aizuchi_words)
    speaks = [j for j in _iter_jsonl_all() if j.get("run_id") == run_id and j.get("event")=="speak"]
    if not speaks:
        return JSONResponse({"style_ok_rate": 0.0})
    ok = 0
    for j in speaks:
        ns = sentence_count(j.get("text",""))
        na = aizuchi_count(j.get("text",""))
        if ns <= 5 and na <= 1:
            ok += 1
    rate = ok / max(1, len(speaks))
    return JSONResponse({"style_ok_rate": rate, "count": len(speaks)})


@app.get("/api/rag/score")
async def rag_score():
    """Return latest offline RAG eval summary if present.

    Expected JSON: {"f1": float, "citation_rate": float, "n": int}
    """
    if RAG_EVAL_SUMMARY.exists():
        try:
            js = json.loads(RAG_EVAL_SUMMARY.read_text(encoding="utf-8"))
            return JSONResponse(js)
        except Exception:
            pass
    return JSONResponse({"f1": 0.0, "citation_rate": 0.0, "n": 0})


@app.get("/", include_in_schema=False)
async def index():
    return HTMLResponse(
        """
        <!doctype html>
        <html>
          <head><meta charset="utf-8"><title>Duo Talk Backend</title></head>
          <body style="font-family:system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, 'Noto Sans JP', 'Hiragino Kaku Gothic ProN', 'Yu Gothic UI', sans-serif; padding:24px;">
            <h1>Duo Talk Backend</h1>
            <p>API is running. See <a href="/docs">/docs</a> for OpenAPI UI, or open the <a href="/ui">/ui</a> quick viewer.</p>
            <ul>
              <li>POST <code>/api/run/start</code></li>
              <li>GET <code>/api/run/list</code></li>
              <li>GET <code>/api/run/stream?run_id=...</code> (SSE)</li>
            </ul>
          </body>
        </html>
        """
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return PlainTextResponse("", status_code=204)

# Minimal static GUI at /ui (no build step required)
app.mount("/ui", StaticFiles(directory="server/static", html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5179)
