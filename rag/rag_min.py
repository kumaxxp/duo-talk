from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import re
import os


# Minimal, offline-friendly RAG. Tries Chroma + e5-small; falls back to a
# lightweight in-memory index using rapidfuzz if deps are missing.


@dataclass
class Doc:
    id: str
    text: str
    meta: Dict[str, Any]


_BUILT = False
_DOCS: List[Doc] = []


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".md", ".txt"}:
            yield p


def _category_from_path(p: Path) -> str:
    parts = [x.lower() for x in p.parts]
    if "canon" in parts:
        return "canon"
    if "lore" in parts:
        return "lore"
    if "episodic" in parts or "pattern" in parts:
        return "pattern"
    return "misc"


def _char_from_path(p: Path) -> Optional[str]:
    # try to infer char id from filename (e.g., style_a.md -> A)
    s = p.stem.lower()
    if "_a" in s or s.endswith("a"):
        return "A"
    if "_b" in s or s.endswith("b"):
        return "B"
    return None


# --- Preview helpers --------------------------------------------------------
FM = re.compile(r"^---\s*.*?---\s*", re.S)


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _fallback_keywords(meta: dict) -> str:
    path = (meta or {}).get("path", "")
    base = os.path.splitext(os.path.basename(path))[0]
    tags = meta.get("tags") if isinstance(meta, dict) else None
    parts = [p for p in ([base] + (tags or [])) if p]
    return ("・" + "・".join(parts[:4])) if parts else ""


def clean_preview(text: str, meta: dict | None = None, limit: int = 120) -> str:
    if not text:
        return _fallback_keywords(meta or {})
    t = FM.sub("", text).strip()
    one = _first_nonempty_line(t)
    if not one:
        one = _fallback_keywords(meta or {})
    return one[:limit]


def build(data_dir: str | Path = "rag_data", *, force: bool = False) -> None:
    global _BUILT, _DOCS
    root = Path(data_dir)
    if force:
        _BUILT = False
    _DOCS = []
    if not root.exists():
        _BUILT = True
        return

    for fp in _iter_files(root):
        try:
            text = fp.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        meta = {
            "path": str(fp),
            "category": _category_from_path(fp),
            "char": _char_from_path(fp),
            "filename": fp.name,
        }
        # attach cleaned preview
        meta["preview"] = clean_preview(text, meta)
        _DOCS.append(Doc(id=str(len(_DOCS)), text=text, meta=meta))

    _BUILT = True


def _ensure_built() -> None:
    if not _BUILT:
        build()


def _score(query: str, text: str) -> float:
    # Lightweight similarity using rapidfuzz if available; otherwise substring bonus
    try:
        from rapidfuzz import fuzz  # type: ignore

        return float(fuzz.token_set_ratio(query, text)) / 100.0
    except Exception:
        q = query.strip()
        if not q:
            return 0.0
        return 1.0 if q in text else 0.2


def retrieve(
    query: str,
    filters: Dict[str, Any] | None = None,
    top_k: int = 8,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Return list of (text, meta) sorted by relevance.

    Filters example: {"category": "canon"} or {"char": "A"}
    """
    _ensure_built()
    flt = filters or {}
    cand: List[Doc] = []
    for d in _DOCS:
        ok = True
        for k, v in flt.items():
            if d.meta.get(k) != v:
                ok = False
                break
        if ok:
            cand.append(d)

    scored = [(d, _score(query, d.text)) for d in cand]
    scored.sort(key=lambda x: x[1], reverse=True)
    out: List[Tuple[str, Dict[str, Any]]] = []
    for d, s in scored[: max(1, top_k)]:
        m = dict(d.meta)
        m["score"] = s
        out.append((d.text, m))
    return out
