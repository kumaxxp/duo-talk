#!/usr/bin/env python3
"""
Offline RAG evaluation.

Input: eval/qa.jsonl with {q, ref_answer, must_cite: bool}
Process: Retrieve -> Generate -> compute char 3-gram F1 and citation rate
Output: CSV per-question and summary JSON at runs/rag_eval_summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import os
from rag.rag_min import build as rag_build, retrieve as rag_retrieve
from duo_chat_mvp import call


def _load_qa(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _ngram(s: str, n: int = 3) -> List[str]:
    s = re.sub(r"\s+", "", s or "")
    if len(s) < n:
        return []
    return [s[i : i + n] for i in range(len(s) - n + 1)]


def _f1(ref: str, pred: str) -> float:
    R = set(_ngram(ref, 3))
    P = set(_ngram(pred, 3))
    if not R and not P:
        return 1.0
    if not R or not P:
        return 0.0
    inter = len(R & P)
    prec = inter / max(1, len(P))
    rec = inter / max(1, len(R))
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def _f1_relaxed(ref: str, pred: str) -> float:
    """Fallback F1 using 2-gram for very short references."""
    def ngram(s: str, n: int) -> List[str]:
        s = re.sub(r"\s+", "", s or "")
        if len(s) < n:
            return []
        return [s[i : i + n] for i in range(len(s) - n + 1)]
    R = set(ngram(ref, 2))
    P = set(ngram(pred, 2))
    if not R and not P:
        return 1.0
    if not R or not P:
        return 0.0
    inter = len(R & P)
    prec = inter / max(1, len(P))
    rec = inter / max(1, len(R))
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def _compose(system_hint: str, q: str, previews: List[str], must_cite: bool) -> Tuple[str, str]:
    system = system_hint
    user = []
    user.append(f"質問: {q}")
    if previews:
        for p in previews[:3]:
            user.append(f"［参考ヒント］{p}（台詞に出さない）")
    if must_cite:
        user.append("必ずヒント文から短い一節をコピペして《》で1箇所引用して根拠を示して。")
    user.append("日本語で2〜4文。前置きや箇条書きは不要。")
    return system, "\n".join(user)


def evaluate(qa_path: str = "eval/qa.jsonl", out_csv: str = "runs/rag_eval.csv", out_summary: str = "runs/rag_eval_summary.json", *, model: str | None = None) -> Tuple[float, float, int]:
    rag_build()
    rows = _load_qa(Path(qa_path))
    out_rows: List[Tuple[str, str, float, int]] = []  # (q, ans, f1, cite)
    for item in rows:
        q = item.get("q", "")
        ref = item.get("ref_answer", "")
        must_cite = bool(item.get("must_cite", False))
        hints = rag_retrieve(q, {"category": "canon"}) + rag_retrieve(q, {"category": "lore"}) + rag_retrieve(q, {"category": "pattern"})
        previews = []
        for text, meta in hints[:3]:
            pv = (meta or {}).get("preview") or (text.splitlines()[0][:120] if text else "")
            pv = re.sub(r"[。！!？?、,.\s]+$", "", pv)
            if pv and pv not in previews:
                previews.append(pv)
        system, user = _compose("あなたは博識なアシスタント。正確に、簡潔に答える。", q, previews, must_cite)
        try:
            mdl = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
            ans = call(model=mdl, system=system, user=user, temperature=0.0, max_tokens=256)
        except Exception:
            ans = ""
        f1 = _f1(ref, ans) or _f1_relaxed(ref, ans)
        # citation: either 《》 span or (fuzzy) any preview substring appears
        cite = 0
        if "《" in ans and "》" in ans:
            cite = 1
        else:
            try:
                from rapidfuzz import fuzz  # type: ignore

                for p in previews:
                    if fuzz.partial_ratio(p, ans) >= 70:
                        cite = 1
                        break
            except Exception:
                if any(p in ans for p in previews):
                    cite = 1
        out_rows.append((q, ans, f1, cite))
    # write CSV
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with Path(out_csv).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["q", "ans", "f1", "cite"])
        for q, ans, f1, cite in out_rows:
            w.writerow([q, ans, f1, cite])
    # summary
    n = max(1, len(out_rows))
    avg_f1 = sum(r[2] for r in out_rows) / n
    cite_rate = sum(r[3] for r in out_rows) / n
    summ = {"f1": avg_f1, "citation_rate": cite_rate, "n": len(out_rows)}
    Path(out_summary).write_text(json.dumps(summ, ensure_ascii=False, indent=2), encoding="utf-8")
    return avg_f1, cite_rate, len(out_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", default="eval/qa.jsonl")
    ap.add_argument("--out-csv", default="runs/rag_eval.csv")
    ap.add_argument("--out-summary", default="runs/rag_eval_summary.json")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    f1, cite, n = evaluate(args.qa, args.out_csv, args.out_summary, model=args.model)
    print(json.dumps({"f1": f1, "citation_rate": cite, "n": n}, ensure_ascii=False))


if __name__ == "__main__":
    main()
