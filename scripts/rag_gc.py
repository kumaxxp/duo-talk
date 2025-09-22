#!/usr/bin/env python3
"""
RAG GC candidate generator (dry-run):
Outputs CSV with path, use_count, last_used, dup_rate (max similarity to other docs).
Usage frequency is computed from runs/duo_runs.jsonl rag_select events.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple


def _iter_runs(log: Path):
    if not log.exists():
        return
    with log.open(encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception:
                continue


def _read_docs(root: Path) -> List[Tuple[Path, str]]:
    docs: List[Tuple[Path, str]] = []
    for p in root.rglob("*.md"):
        try:
            docs.append((p, p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return docs


def _similar(a: str, b: str) -> float:
    try:
        from rapidfuzz import fuzz  # type: ignore

        return float(fuzz.token_set_ratio(a or "", b or "")) / 100.0
    except Exception:
        return 1.0 if (a and b and a == b) else 0.0


def compute_gc(root="rag_data", log="runs/duo_runs.jsonl", out_csv="runs/rag_gc_candidates.csv") -> int:
    rootp = Path(root)
    logp = Path(log)
    outp = Path(out_csv)
    docs = _read_docs(rootp)
    # usage
    use: Dict[str, Tuple[int, str]] = {}
    for j in _iter_runs(logp) or []:
        if j.get("event") != "rag_select":
            continue
        for k in ("canon", "lore", "pattern"):
            m = (j.get(k) or {})
            path = m.get("path")
            if not path:
                continue
            cnt, ts = use.get(path, (0, ""))
            use[path] = (cnt + 1, j.get("ts") or ts)

    # duplicate rate: max similarity to any other text
    dup_rate: Dict[str, float] = {}
    for i, (pi, ti) in enumerate(docs):
        mx = 0.0
        for j, (pj, tj) in enumerate(docs):
            if i == j:
                continue
            s = _similar(ti, tj)
            if s > mx:
                mx = s
        dup_rate[str(pi)] = mx

    # write CSV
    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "use_count", "last_used", "dup_rate"])
        for p, _t in docs:
            cnt, ts = use.get(str(p), (0, ""))
            w.writerow([str(p), cnt, ts, f"{dup_rate.get(str(p), 0.0):.2f}"])
    return len(docs)


if __name__ == "__main__":
    n = compute_gc()
    print(f"listed: {n}")

