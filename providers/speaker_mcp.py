import os
import json
import shlex
import time
import uuid
import subprocess
import select
from typing import Any, Dict, Tuple, Optional

from .speaker_provider import SpeakerProvider


class SpeakerAMcpProvider(SpeakerProvider):
    """MCP stdio client for A-side.

    Spawns an MCP server (stdio transport) and performs JSON-RPC with
    LSP-style Content-Length framing. Calls `tools/call` for `chat`.
    """

    def __init__(self) -> None:
        self.transport = (os.getenv("SPEAKER_A_MCP_TRANSPORT") or "stdio").strip()
        if self.transport != "stdio":
            raise NotImplementedError("Only stdio transport is supported currently")
        self.command = os.getenv("SPEAKER_A_MCP_COMMAND") or "python"
        self.args = os.getenv("SPEAKER_A_MCP_ARGS") or ""
        self.cwd = os.getenv("SPEAKER_A_MCP_CWD") or None
        self.token = os.getenv("SPEAKER_A_AUTH_TOKEN") or None

        cmd = [self.command] + (shlex.split(self.args) if self.args else [])
        if not cmd:
            raise ValueError("SPEAKER_A_MCP_COMMAND is required for MCP stdio provider")

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.cwd or None,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start MCP server: {e}")

        if not self.proc.stdin or not self.proc.stdout:
            raise RuntimeError("Failed to open stdio pipes to MCP server")

        self._stdin = self.proc.stdin
        self._stdout = self.proc.stdout
        self._id = 0
        # initialize session
        self._rpc_call("initialize", {"clientInfo": {"name": "duo-talk", "version": "0"}}, timeout_ms=5000)
        # optionally check tools/list
        self._rpc_call("tools/list", {}, timeout_ms=5000)

    # --------------- Public API ---------------
    def generate(
        self,
        user_text: str,
        *,
        run_id: str,
        top_k: int,
        filters: Dict[str, Any],
        timeout_ms: int,
    ) -> Tuple[str, Dict[str, Any]]:
        args = {
            "user_text": user_text,
            "use_rag": True,
            "top_k": int(top_k),
            "filters": {k: v for k, v in (filters or {}).items() if k in {"category", "region", "brewery"}},
            "context": {"run_id": run_id, "disable_sayana": True},
        }
        res = self._rpc_call("tools/call", {"name": "chat", "arguments": args}, timeout_ms=timeout_ms)
        # Expected shape: {result: {content: [{type: "text", text: "{...json...}"}]}}
        if not isinstance(res, dict):
            raise RuntimeError("Invalid MCP response: not a dict")
        content = (res.get("content") or []) if isinstance(res, dict) else []
        text_json = None
        if content and isinstance(content[0], dict):
            text_json = content[0].get("text")
        if not text_json:
            raise RuntimeError("MCP chat returned empty content")
        try:
            js = json.loads(text_json)
        except Exception:
            # If server already returned structured content later, try to use it
            raise RuntimeError("MCP chat content is not valid JSON text")

        reply = (js.get("reply") or "").strip()
        meta: Dict[str, Any] = {
            "hits": js.get("hits") or [],
            "elapsed_ms": js.get("elapsed_ms"),
            "trace_id": js.get("trace_id") or uuid.uuid4().hex[:12],
            "warnings": js.get("warnings") or [],
            "llm": js.get("llm"),
            "server_version": js.get("server_version"),
            "policy_version": js.get("policy_version"),
            "rag_hit_count": js.get("rag_hit_count", len(js.get("hits") or [])),
            "source": "mcp_stdio",
        }
        return reply, meta

    # --------------- Internal JSON-RPC framing ---------------
    def _rpc_call(self, method: str, params: Optional[dict], *, timeout_ms: int) -> Any:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            req["params"] = params
        self._write_message(req)
        deadline = time.time() + max(0.5, timeout_ms / 1000.0)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"MCP call timeout: {method}")
            rlist, _, _ = select.select([self._stdout], [], [], remaining)
            if not rlist:
                continue
            msg = self._read_message()
            if not msg:
                continue
            if msg.get("id") == self._id:
                if "error" in msg and msg["error"] is not None:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg.get("result")

    def _write_message(self, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        self._stdin.write(header)
        self._stdin.write(data)
        self._stdin.flush()

    def _read_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        # readline-compatible over binary stream
        def _readline() -> bytes:
            buf = bytearray()
            while True:
                ch = self._stdout.read(1)
                if not ch:
                    break
                buf += ch
                if buf.endswith(b"\r\n"):
                    break
            return bytes(buf)

        while True:
            line = _readline()
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

    def _read_message(self) -> Optional[dict]:
        headers = self._read_headers()
        if not headers:
            return None
        clen = int(headers.get("content-length", "0"))
        if clen <= 0:
            return None
        data = self._stdout.read(clen)
        if not data:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except Exception:
            return None


__all__ = ["SpeakerAMcpProvider"]
