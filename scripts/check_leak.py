#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def latest_run_id(path: Path) -> str | None:
    rid = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("event") == "run_start":
                rid = j.get("run_id", rid)
    return rid


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect leak of beat names or direction notes in speak texts")
    ap.add_argument("logfile", type=str, help="Path to runs JSONL file (e.g., runs/duo_runs.jsonl)")
    ap.add_argument("--run-id", type=str, default=None, help="Filter to a specific run_id (defaults to latest)")
    args = ap.parse_args()

    p = Path(args.logfile)
    if not p.exists():
        print("log file not found", p)
        return 1
    rid = args.run_id or latest_run_id(p)
    if not rid:
        print("no run_id found")
        return 1

    pat = re.compile(r"\b(BANter|PIVOT|PAYOFF|HOOK|演出ノート)\b", re.IGNORECASE)
    leaked = False
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("event") == "speak" and j.get("run_id") == rid:
                t = (j.get("text") or "")
                if pat.search(t):
                    leaked = True
                    turn = j.get("turn")
                    print(f"[LEAK] turn={turn} {t[:100]}...")
    if not leaked:
        print("OK: no leaks detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

