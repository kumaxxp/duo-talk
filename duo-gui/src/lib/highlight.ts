// トークンと3-gramの両方で一致を拾い、<mark>で囲う
export function tokenizeJa(s: string): string[] {
  return s?.match(/[A-Za-z0-9ぁ-んァ-ン一-龯]{2,}/g) ?? [];
}

// 3-gram集合
function charNgrams(s: string, n = 3): Set<string> {
  const t = (s || "").replace(/\s+/g, "");
  const out = new Set<string>();
  for (let i = 0; i <= Math.max(0, t.length - n); i++) out.add(t.slice(i, i + n));
  return out;
}

export function buildHitSet(hints: string[]): Set<string> {
  const tokens = hints.flatMap((h) => tokenizeJa(h));
  const set = new Set<string>(tokens);
  // 有効トークンが少ない時だけ3-gramも併用
  if (set.size < 6) {
    hints.forEach((h) =>
      charNgrams(h, 3).forEach((g) => {
        if (g.length >= 3) set.add(g);
      })
    );
  }
  return set;
}

// utter内の一致箇所を<mark>でマーク（単純置換の重複回避）
export function highlightUtter(utter: string, hints: string[]): string {
  let html = utter ?? "";
  const hits = [...buildHitSet(hints)].sort((a, b) => b.length - a.length); // 長い順
  for (const h of hits) {
    if (!h) continue;
    const safe = h.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const isShort = h.length <= 2;
    const re = new RegExp(isShort ? `\\b${safe}\\b` : safe, "g");
    html = html.replace(
      re,
      (m) => `<mark class="bg-yellow-200 dark:bg-yellow-700 underline underline-offset-2">${m}</mark>`
    );
  }
  return html;
}
