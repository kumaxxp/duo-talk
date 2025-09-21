export function covColor(cov: number): string {
  if (cov < 0.10) return 'bg-slate-300'
  if (cov < 0.20) return 'bg-amber-400'
  return 'bg-emerald-500'
}

export function pct(n: number): string {
  return `${Math.round((n || 0) * 100)}%`
}

