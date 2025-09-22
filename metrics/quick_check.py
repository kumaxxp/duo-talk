import sys, json, re, argparse, pathlib

def load_jsonl(path):
    p = pathlib.Path(path)
    if not p.exists():
        print(f"[ERR] file not found: {p}", file=sys.stderr); sys.exit(1)
    with p.open('r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # 破損行は飛ばす
                continue

SPLIT = re.compile(r"[。．.!！?？]+")

AIZU = re.compile(r"(なるほど|いいね|たしかに)")
def sentence_count(txt: str) -> int:
    if not txt: return 0
    # 末尾句点で数え漏れしないよう正規化
    parts = [s for s in SPLIT.split(txt) if s.strip()]
    return len(parts)

def aizuchi_count(txt: str) -> int:
    return len(AIZU.findall(txt or ""))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", help="runs/duo_runs.jsonl")
    ap.add_argument("--limit-sent", type=int, default=5, help="文数上限（既定=5）")
    ap.add_argument("--limit-aizuchi", type=int, default=1, help="合いの手上限（既定=1）")
    ap.add_argument("--list", action="store_true", help="全発話の文数/合いの手数を表示")
    ap.add_argument("--show-violations", action="store_true", help="違反だけ表示")
    args = ap.parse_args()

    total = speak = long_ng = aizuchi_ng = 0
    rows = []
    for j in load_jsonl(args.jsonl):
        total += 1
        if j.get("event") != "speak": 
            continue
        speak += 1
        who = j.get("speaker", "?")
        text = j.get("text", "")
        ns = sentence_count(text)
        na = aizuchi_count(text)
        rows.append((who, ns, na, text))

    if args.list:
        for who, ns, na, text in rows:
            print(f"{who}\t{ns}文\t{na}回\t{text[:80]}...")

    for who, ns, na, text in rows:
        violated = False
        if ns > args.limit_sent:
            long_ng += 1; violated = True
            if args.show_violations:
                print(f"LONG\t{who}\t{ns}文\t{text[:120]}...")
        if na > args.limit_aizuchi:
            aizuchi_ng += 1; violated = True
            if args.show_violations:
                print(f"AIZUCHI\t{who}\t{na}回\t{text[:120]}...")

    style_ok = 0
    for who, ns, na, text in rows:
        if ns <= args.limit_sent and na <= args.limit_aizuchi:
            style_ok += 1
    style_rate = (style_ok / max(1, len(rows))) if rows else 0.0

    print("--- summary ---")
    print(f"lines(total): {total}")
    print(f"speak:        {speak}")
    print(f"violations:   LONG={long_ng}, AIZUCHI={aizuchi_ng}")
    print(f"style_ok:     {style_ok}/{len(rows)} ({style_rate*100:.1f}%)")
    if long_ng==0 and aizuchi_ng==0:
        print("OK: no violations found (given limits).")

if __name__ == "__main__":
    main()
