export function tokens(s: string): string[] {
  return s.match(/[A-Za-z0-9ぁ-んァ-ン一-龯]{2,}/g) ?? []
}

function grams(s: string, n = 3): Set<string> {
  const c = (s || '').replace(/\s+/g, '')
  const out: string[] = []
  for (let i = 0; i <= Math.max(0, c.length - n); i++) out.push(c.slice(i, i + n))
  return new Set(out)
}

export function covRate(snippet: string, utter: string, mode: 'token' | 'chargram' | 'mix' = 'mix', topk = 12): number {
  if (!snippet || !utter) return 0
  let tHit = 0
  if (mode === 'token' || mode === 'mix') {
    let t = tokens(snippet)
    if (topk && t.length > topk) {
      const counts = new Map<string, number>()
      t.forEach(w => counts.set(w, (counts.get(w) ?? 0) + 1))
      t = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, topk).map(e => e[0])
    }
    const u = new Set(tokens(utter))
    const a = new Set(t)
    tHit = a.size ? [...a].filter(x => u.has(x)).length / a.size : 0
  }
  let cHit = 0
  if (mode === 'chargram' || mode === 'mix') {
    const g1 = grams(snippet, 3), g2 = grams(utter, 3)
    cHit = g1.size ? [...g1].filter(x => g2.has(x)).length / g1.size : 0
  }
  return mode === 'token' ? tHit : mode === 'chargram' ? cHit : Math.max(tHit, cHit)
}

