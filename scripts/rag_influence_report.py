#!/usr/bin/env python3
import json, re, sys, argparse, collections


def load_jsonl(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except Exception:
                    pass


# ゆるいトークナイズ（ひらがな/カタカナ/漢字/英数の連続を単語とみなす）
TOK = re.compile(r"[A-Za-z0-9ぁ-んァ-ン一-龯]{2,}")
STOP = set(list("これはそれそしてしかしだからまたでもつまりようするにですますでしたます。…"))


def tokens(s: str):
    return [w for w in TOK.findall(s or "") if w not in STOP]


def topk_words(s, k=12):
    c = collections.Counter(tokens(s))
    return [w for w, _ in c.most_common(k)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--run-id", help="対象run_id。未指定なら最新run")
    ap.add_argument("--k", type=int, default=12, help="スニペの上位語を何個使うか")
    args = ap.parse_args()

    rows = list(load_jsonl(args.jsonl))
    # 最新 run_id を自動選択
    rid = args.run_id
    if not rid:
        for j in reversed(rows):
            if j.get("event") == "run_start":
                rid = j.get("run_id")
                break
    if not rid:
        print("run_id not found", file=sys.stderr)
        sys.exit(1)

    # turn→スニペ＆台詞を収集
    rag, spoke = {}, {}
    for j in rows:
        if j.get("run_id") != rid:
            continue
        if j.get("event") == "rag_select":
            rag[j["turn"]] = j
        elif j.get("event") == "speak":
            spoke[j.get("turn")] = j

    print(f"# run_id: {rid}")
    print("turn\tbeat\tcanon_hit\tlore_hit\tpattern_hit\tcov% \t speaker \t preview")
    for t in sorted(spoke):
        s = spoke[t]
        text = s.get("text", "")
        beat = s.get("beat", "-")
        r = rag.get(t, {})

        def score(sn):
            pv = (r.get(sn) or {}).get("preview") or ""
            kws = set(topk_words(pv, args.k))
            if not kws:
                return 0.0
            used = set(tokens(text))
            inter = len(kws & used)
            return inter / max(1, len(kws))

        sc_c, sc_l, sc_p = score("canon"), score("lore"), score("pattern")
        cov = max(sc_c, sc_l, sc_p)
        print(f"{t}\t{beat}\t{sc_c:.2f}\t{sc_l:.2f}\t{sc_p:.2f}\t{cov:.2f}\t {s.get('speaker')}\t {text[:60]}...")


if __name__ == "__main__":
    main()

