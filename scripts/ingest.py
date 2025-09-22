#!/usr/bin/env python3
"""
Minimal offline RAG ingestion.

Input:  raw_docs/** (md/pdf/html -> normalized md)
Chunks: per heading (md). Otherwise paragraph blocks. Adds ~15% overlap.
Dedup:  rapidfuzz token_set_ratio >= 92% considered duplicate and skipped.
Output: rag_data/{canon|lore|pattern}/ with front-matter: source/path/tags.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
from typing import Iterable, List, Tuple


def _read_text(fp: Path) -> str:
    ext = fp.suffix.lower()
    try:
        if ext in {".md", ".txt"}:
            return fp.read_text(encoding="utf-8", errors="replace")
        if ext in {".html", ".htm"}:
            try:
                from bs4 import BeautifulSoup  # type: ignore

                html = fp.read_text(encoding="utf-8", errors="replace")
                soup = BeautifulSoup(html, "html.parser")
                return soup.get_text("\n")
            except Exception:
                # fallback: strip tags crudely
                txt = re.sub(r"<[^>]+>", "\n", fp.read_text(encoding="utf-8", errors="replace"))
                return re.sub(r"\n{3,}", "\n\n", txt)
        if ext == ".pdf":
            try:
                from pdfminer.high_level import extract_text  # type: ignore

                return extract_text(str(fp))
            except Exception:
                return ""
    except Exception:
        return ""
    return ""


H1 = re.compile(r"^# +")
H = re.compile(r"^(#+) +")


def _chunk_md(text: str) -> List[str]:
    lines = text.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    cur_head = ""
    cur_buf: List[str] = []
    for ln in lines:
        m = H.match(ln)
        if m:
            if cur_buf:
                sections.append((cur_head, cur_buf))
            cur_head = ln.strip()
            cur_buf = []
        else:
            cur_buf.append(ln)
    if cur_buf:
        sections.append((cur_head, cur_buf))
    chunks: List[str] = []
    for head, buf in sections:
        body = "\n".join([ln for ln in buf]).strip()
        if not body:
            continue
        chunks.append((head + "\n" + body).strip())
    # add 15% line overlap
    if not chunks:
        return []
    out: List[str] = []
    for i, ch in enumerate(chunks):
        out.append(ch)
        if i + 1 < len(chunks):
            prev_lines = ch.splitlines()
            k = max(1, int(len(prev_lines) * 0.15))
            overlap = "\n".join(prev_lines[-k:])
            out[-1] = (out[-1] + "\n" + overlap).strip()
    return out


def _chunk_plain(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paras:
        return []
    out: List[str] = []
    for i, p in enumerate(paras):
        ch = p
        if i + 1 < len(paras):
            k = max(1, int(len(p.splitlines()) * 0.15))
            tail = "\n".join(p.splitlines()[-k:])
            ch = (ch + "\n" + tail).strip()
        out.append(ch)
    return out


def _similar(a: str, b: str) -> float:
    try:
        from rapidfuzz import fuzz  # type: ignore

        return float(fuzz.token_set_ratio(a or "", b or "")) / 100.0
    except Exception:
        return 1.0 if (a and b and a == b) else 0.0


def _category_from_path(p: Path) -> str:
    s = "/".join([x.lower() for x in p.parts])
    if "canon" in s:
        return "canon"
    if "lore" in s:
        return "lore"
    if "pattern" in s:
        return "pattern"
    return "lore"


def _front_matter(source: Path, out_path: Path, tags: list[str]) -> str:
    import yaml  # type: ignore

    fm = {
        "source": str(source),
        "path": str(out_path),
        "tags": tags,
    }
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip() + "\n---\n"


def ingest(root_in: Path, root_out: Path, *, threshold: float = 0.92) -> int:
    kept = 0
    seen: List[str] = []
    for fp in root_in.rglob("*"):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in {".md", ".txt", ".html", ".htm", ".pdf"}:
            continue
        text = _read_text(fp)
        if not text:
            continue
        chunks = _chunk_md(text) if fp.suffix.lower() == ".md" else _chunk_plain(text)
        cat = _category_from_path(fp)
        (root_out / cat).mkdir(parents=True, exist_ok=True)
        tag_guess = [cat, fp.stem[:24]]
        for ch in chunks:
            # dedup against seen
            if any(_similar(ch, s) >= threshold for s in seen):
                continue
            seen.append(ch)
            h = hashlib.sha1(ch.encode("utf-8")).hexdigest()[:12]
            outp = root_out / cat / f"ing_{h}.md"
            fm = _front_matter(fp, outp, tag_guess)
            outp.write_text(fm + ch.strip() + "\n", encoding="utf-8")
            kept += 1
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="raw_docs")
    ap.add_argument("--out", dest="out", default="rag_data")
    ap.add_argument("--threshold", type=float, default=0.92)
    args = ap.parse_args()
    root_in = Path(args.inp)
    root_out = Path(args.out)
    root_out.mkdir(parents=True, exist_ok=True)
    kept = ingest(root_in, root_out, threshold=args.threshold)
    print(f"ingested: {kept}")


if __name__ == "__main__":
    main()

