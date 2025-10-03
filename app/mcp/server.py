#!/usr/bin/env python3
import io
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

# Reuse server logic and RAG/LLM pipeline
from ..ingest.pipeline import process_image, load_config
from ..rag.search import search as rag_search, search_with_debug as rag_search_debug
from ..server.prompts import SYSTEM_PROMPT, compose_rag_context
from ..server.policy import enforce as policy_enforce, should_sayana
from ..server.llm import chat as llm_chat, is_available as llm_available


JST_OFFSET = 9 * 3600


def _now_iso() -> str:
    import datetime as dt

    return dt.datetime.utcnow().isoformat() + "Z"


def _cfg_path() -> str:
    return os.path.join(os.path.dirname(__file__), '..', 'config', 'app.yaml')


SERVER_VERSION = os.environ.get("YANA_SERVER_VERSION", "1.0.0")
POLICY_VERSION = os.environ.get("YANA_POLICY_VERSION", "say-2025-09-23")


# --------- Minimal MCP stdio transport (LSP-style framing) ---------


def _read_headers(stdin: io.BufferedReader) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    line = b""
    while True:
        line = stdin.readline()
        if not line:
            return {}
        if line in (b"\r\n", b"\n"):
            break
        try:
            k, v = line.decode("utf-8").split(":", 1)
            headers[k.strip().lower()] = v.strip()
        except Exception:
            continue
    return headers


def _read_message(stdin: io.BufferedReader) -> Optional[Dict[str, Any]]:
    headers = _read_headers(stdin)
    if not headers:
        return None
    clen = int(headers.get("content-length", "0"))
    if clen <= 0:
        return None
    data = stdin.read(clen)
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def _write_message(stdout: io.BufferedWriter, obj: Dict[str, Any]) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stdout.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    stdout.write(data)
    stdout.flush()


# --------- Tool implementations ---------


def _tool_chat(args: Dict[str, Any]) -> Dict[str, Any]:
    user_text = (args or {}).get("user_text")
    if not isinstance(user_text, str) or not user_text.strip():
        raise ValueError("user_text is required")
    use_rag = bool((args or {}).get("use_rag", True))
    top_k = int((args or {}).get("top_k", 5))
    filters: Dict[str, Any] = (args or {}).get("filters") or {}
    context = (args or {}).get("context") or {}
    run_id = context.get("run_id") or uuid.uuid4().hex[:12]

    t0 = time.perf_counter()
    cfg = load_config(os.path.abspath(_cfg_path()))
    f2: Dict[str, Any] = {}
    for k in ("category", "region", "brewery"):
        v = filters.get(k)
        if v:
            f2[k] = str(v)

    hits: List[Dict[str, Any]] = []
    if use_rag and user_text.strip():
        hits = rag_search(cfg['storage']['jsonl_path'], query_text=user_text, filters=f2, k=top_k)

    turn_ctx = {'sayana_max_per_dialog': cfg.get('policy', {}).get('sayana_max_per_dialog', 1), 'sayana_used': 0}
    reply: str
    used_llm = False
    if should_sayana(user_text, "せやなー", turn_ctx):
        reply = "せやなー"
    elif llm_available():
        try:
            user = compose_rag_context(hits[:top_k], user_text, top_k) if (use_rag and hits) else user_text
            raw = llm_chat(SYSTEM_PROMPT, user)
            reply = policy_enforce(raw, user_text, turn_ctx)
            used_llm = True
        except Exception:
            used_llm = False
    if not used_llm:
        if should_sayana(user_text, "せやなー", turn_ctx):
            reply = "せやなー"
        else:
            if hits:
                parts: List[str] = ["ラベルの話なら任せてだよ！"]
                for h in hits[:min(3, len(hits))]:
                    brand = h.get('brand_name') or '不明'
                    product = h.get('product_name') or ''
                    brw = h.get('brewery') or '蔵不明'
                    reg = h.get('region') or ''
                    summ = h.get('vlm_summary') or ''
                    parts.append(f"{brand} {product}（{brw} / {reg}）。{summ}")
                parts.append("似た雰囲気のもの、もっと探せるかな？")
                reply = " ".join(parts)
            else:
                reply = "今は手元の参考が少ないけど、方向性は教えてほしいかな。"
            reply = policy_enforce(reply, user_text, turn_ctx)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        'reply': (reply or "").strip(),
        'hits': hits[:top_k],
        'llm': 'on' if used_llm else 'off',
        'elapsed_ms': elapsed_ms,
        'rag_hit_count': len(hits[:top_k]),
        'run_id': run_id,
        'trace_id': uuid.uuid4().hex[:12],
        'server_version': SERVER_VERSION,
        'policy_version': POLICY_VERSION,
        'warnings': [],
    }


def _tool_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query_text = (args or {}).get('query_text')
    filters = (args or {}).get('filters') or {}
    k = int((args or {}).get('k', 5))
    cfg = load_config(os.path.abspath(_cfg_path()))
    fil: Dict[str, Any] = {}
    if isinstance(filters, dict):
        for kf in ("category", "region", "brewery"):
            v = filters.get(kf)
            if v:
                fil[kf] = str(v)
    hits = rag_search_debug(cfg['storage']['jsonl_path'], query_text=query_text, filters=fil, k=k)
    return {
        'hits': hits,
        'run_id': uuid.uuid4().hex[:12],
        'trace_id': uuid.uuid4().hex[:12],
        'server_version': SERVER_VERSION,
        'policy_version': POLICY_VERSION,
    }


def _tool_ingest(args: Dict[str, Any]) -> Dict[str, Any]:
    image = (args or {}).get('image')
    category = (args or {}).get('category')
    region = (args or {}).get('region') or ""
    if not image or not category:
        raise ValueError("image and category are required")
    # Support local file path only for now
    if not os.path.exists(image):
        raise ValueError("image must be a local file path")
    rec = process_image(image, category=str(category), region=(str(region) or None), cfg_path=_cfg_path())
    return {
        'id': rec.get('id'),
        'dedup': False,
        'hash_sha1': rec.get('hash_sha1'),
        'phash': rec.get('phash'),
        'run_id': uuid.uuid4().hex[:12],
        'trace_id': uuid.uuid4().hex[:12],
        'server_version': SERVER_VERSION,
        'policy_version': POLICY_VERSION,
    }


def _load_schema(path: str) -> Dict[str, Any]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"type": "object"}


def _tools_list() -> Dict[str, Any]:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'mcp'))
    return {
        "tools": [
            {
                "name": "chat",
                "description": "Sumigaseyana RAG chat",
                "inputSchema": _load_schema(os.path.join(base, 'tools.chat.schema.json')),
            },
            {
                "name": "search",
                "description": "Search RAG store with debug scoring",
                "inputSchema": _load_schema(os.path.join(base, 'tools.search.schema.json')),
            },
            {
                "name": "ingest",
                "description": "Ingest an image into RAG store (local path)",
                "inputSchema": _load_schema(os.path.join(base, 'tools.ingest.schema.json')),
            },
        ]
    }


def _tools_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == 'chat':
        return {"content": [{"type": "text", "text": json.dumps(_tool_chat(arguments), ensure_ascii=False)}]}
    if name == 'search':
        return {"content": [{"type": "text", "text": json.dumps(_tool_search(arguments), ensure_ascii=False)}]}
    if name == 'ingest':
        return {"content": [{"type": "text", "text": json.dumps(_tool_ingest(arguments), ensure_ascii=False)}]}
    raise ValueError(f"unknown tool: {name}")


def main() -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        msg = _read_message(stdin)
        if msg is None:
            break
        msg_id = msg.get("id")
        method = msg.get("method")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-09-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "sumigaseyana-mcp", "version": SERVER_VERSION},
                }
                _write_message(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": result})
            elif method == "tools/list":
                _write_message(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": _tools_list()})
            elif method == "tools/call":
                params = msg.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                result = _tools_call(str(name), dict(arguments))
                _write_message(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": result})
            else:
                _write_message(stdout, {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })
        except Exception as e:
            _write_message(stdout, {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32000, "message": str(e)},
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

