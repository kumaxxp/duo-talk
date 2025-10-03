import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from .speaker_provider import SpeakerProvider


class SpeakerAHttpProvider(SpeakerProvider):
    """HTTP provider for Sumigaseyana A-side character.

    Tries /v1/chat JSON endpoint; falls back to legacy /chat Form endpoint.
    Only constructs requests; no retries here (leave to caller/policy).
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        default_use_rag: Optional[bool] = None,
        default_top_k: Optional[int] = None,
        default_filters_json: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("SPEAKER_A_HTTP_BASE") or "").rstrip("/")
        self.auth_token = auth_token or os.getenv("SPEAKER_A_AUTH_TOKEN") or None
        self.default_use_rag = (
            default_use_rag if default_use_rag is not None else _env_bool("SPEAKER_A_USE_RAG", True)
        )
        self.default_top_k = int(
            default_top_k if default_top_k is not None else os.getenv("SPEAKER_A_TOP_K", "5")
        )
        self.default_filters = _parse_json_obj(os.getenv("SPEAKER_A_FILTERS_JSON"))

        if not self.base_url:
            raise ValueError("SPEAKER_A_HTTP_BASE is required for SpeakerAHttpProvider")

        # Lazy import to avoid hard dep if unused
        try:
            import requests  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("'requests' package is required for SpeakerAHttpProvider") from e

    def _headers(self, *, run_id: str) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "duo-talk/ProviderAHttp",
            "X-Run-Id": run_id,
        }
        if self.auth_token:
            h["Authorization"] = f"Bearer {self.auth_token}"
        return h

    def generate(
        self,
        user_text: str,
        *,
        run_id: str,
        top_k: int,
        filters: Dict[str, Any],
        timeout_ms: int,
    ) -> Tuple[str, Dict[str, Any]]:
        import requests  # type: ignore

        use_rag = self.default_use_rag
        if "use_rag" in filters:
            # do not let a stray key hijack; keep bool-only
            try:
                use_rag = bool(filters.get("use_rag"))
            except Exception:
                pass

        eff_filters = {**(self.default_filters or {}), **{k: v for k, v in (filters or {}).items() if k in {"category", "region", "brewery"}}}
        eff_top_k = top_k or self.default_top_k

        t0 = time.perf_counter()

        # Prefer /v1/chat JSON
        url_v1 = f"{self.base_url}/v1/chat"
        payload = {
            "user_text": user_text,
            "use_rag": bool(use_rag),
            "top_k": int(eff_top_k),
            "filters": eff_filters,
            "context": {"run_id": run_id, "disable_sayana": True},
        }
        headers = self._headers(run_id=run_id)

        try:
            r = requests.post(
                url_v1,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", **headers},
                timeout=max(1, int(timeout_ms) / 1000.0),
            )
            if r.status_code == 404:
                # Fall back to legacy /chat Form endpoint
                return self._call_legacy(user_text, run_id=run_id, top_k=eff_top_k, filters=eff_filters, timeout_ms=timeout_ms)
            if r.status_code >= 400:
                meta = _build_meta_from_error(r, t0)
                _raise_http_error("/v1/chat", r, meta)
            js = r.json()
        except requests.exceptions.RequestException as e:
            # Surface as runtime error for caller to decide retry
            raise RuntimeError(f"AHttpProvider request failed: {e}") from e

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        reply = (js.get("reply") or "").strip()
        meta: Dict[str, Any] = {
            "hits": js.get("hits") or [],
            "elapsed_ms": js.get("elapsed_ms", elapsed_ms),
            "trace_id": js.get("trace_id"),
            "warnings": js.get("warnings") or [],
            "llm": js.get("llm"),
            "server_version": js.get("server_version"),
            "policy_version": js.get("policy_version"),
            "rag_hit_count": js.get("rag_hit_count", len(js.get("hits") or [])),
            "source": "http_v1",
        }
        return reply, meta

    def _call_legacy(
        self,
        user_text: str,
        *,
        run_id: str,
        top_k: int,
        filters: Dict[str, Any],
        timeout_ms: int,
    ) -> Tuple[str, Dict[str, Any]]:
        import requests  # type: ignore

        url = f"{self.base_url}/chat"
        data = {
            "user_text": user_text,
            "use_rag": str(self.default_use_rag).lower(),
            "top_k": str(int(top_k or self.default_top_k)),
        }
        if filters.get("category"):
            data["category"] = str(filters["category"])
        if filters.get("region"):
            data["region"] = str(filters["region"])
        headers = self._headers(run_id=run_id)
        t0 = time.perf_counter()
        try:
            r = requests.post(url, data=data, headers=headers, timeout=max(1, int(timeout_ms) / 1000.0))
            if r.status_code >= 400:
                meta = _build_meta_from_error(r, t0)
                _raise_http_error("/chat", r, meta)
            js = r.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"AHttpProvider legacy request failed: {e}") from e

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        reply = (js.get("reply") or "").strip()
        meta: Dict[str, Any] = {
            "hits": js.get("hits") or [],
            "elapsed_ms": js.get("elapsed_ms", elapsed_ms),
            "trace_id": js.get("trace_id"),
            "warnings": js.get("warnings") or [],
            "llm": js.get("llm"),
            "server_version": js.get("server_version"),
            "policy_version": js.get("policy_version"),
            "rag_hit_count": len(js.get("hits") or []),
            "source": "http_legacy",
        }
        return reply, meta


def _env_bool(name: str, default: bool) -> bool:
    s = os.getenv(name)
    if s is None:
        return default
    return str(s).lower() in {"1", "true", "yes", "on"}


def _parse_json_obj(s: Optional[str]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _build_meta_from_error(resp: Any, t0: float) -> Dict[str, Any]:
    try:
        js = resp.json()
    except Exception:
        js = {}
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": getattr(resp, "status_code", None),
        "body": js,
        "elapsed_ms": elapsed_ms,
    }


def _raise_http_error(endpoint: str, resp: Any, meta: Dict[str, Any]) -> None:
    code = None
    msg = None
    retryable = None
    if isinstance(meta.get("body"), dict):
        err = meta["body"].get("error") or {}
        code = err.get("code")
        msg = err.get("message")
        retryable = err.get("retryable")
    detail = f"HTTP {getattr(resp, 'status_code', '?')} at {endpoint}"
    if code:
        detail += f" code={code}"
    if retryable is not None:
        detail += f" retryable={retryable}"
    if msg:
        detail += f" msg={msg}"
    raise RuntimeError(detail)


__all__ = ["SpeakerAHttpProvider"]
