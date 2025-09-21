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


def char_ngrams(s: str, n: int = 3):
    s = re.sub(r"\s+", "", s or "")
    return {s[i : i + n] for i in range(max(0, len(s) - n + 1))}


def topk_words(s, k=12):
    c = collections.Counter(tokens(s))
    return [w for w, _ in c.most_common(k)]


def cov_rate(snippet: str, utter: str, topk: int = 12, mode: str = "mix") -> float:
    """token / chargram / mix の簡易カバレッジ"""
    if not snippet or not utter:
        return 0.0
    # token overlap
    t_hit = 0.0
    if mode in ("token", "mix"):
        t_snip = tokens(snippet)
        if topk and len(t_snip) > topk:
            ctr = collections.Counter(t_snip)
            t_snip = [w for w, _ in ctr.most_common(topk)]
        t_utt = set(tokens(utter))
        if t_snip:
            t_hit = len(set(t_snip) & t_utt) / max(1, len(set(t_snip)))
    # char 3-gram overlap
    c_hit = 0.0
    if mode in ("chargram", "mix"):
        g1 = char_ngrams(snippet, 3)
        g2 = char_ngrams(utter, 3)
        if g1:
            c_hit = len(g1 & g2) / max(1, len(g1))
    if mode == "token":
        return t_hit
    if mode == "chargram":
        return c_hit
    return max(t_hit, c_hit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--run-id", help="対象run_id。未指定なら最新run")
    ap.add_argument("--k", type=int, default=12, help="token上位語の使用数（0=無制限）")
    ap.add_argument("--mode", choices=["token", "chargram", "mix"], default="mix")
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
            return cov_rate(pv, text, topk=args.k, mode=args.mode)

        sc_c, sc_l, sc_p = score("canon"), score("lore"), score("pattern")
        cov = max(sc_c, sc_l, sc_p)
        print(f"{t}\t{beat}\t{sc_c:.2f}\t{sc_l:.2f}\t{sc_p:.2f}\t{cov:.2f}\t {s.get('speaker')}\t {text[:60]}...")


if __name__ == "__main__":
    main()
