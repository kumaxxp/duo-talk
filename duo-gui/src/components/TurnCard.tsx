import React from 'react'
import { covRate } from '../hooks/useCov'
import { covColor, pct } from '../lib/format'
import type { Beat, RAGEvent, SpeakEvent } from '../lib/types'

export default function TurnCard({ sp, rag, beat, onSelect, onViewPrompts }:{ sp: SpeakEvent, rag?: RAGEvent, beat?: Beat, onSelect?: ()=>void, onViewPrompts?: (e: React.MouseEvent<HTMLButtonElement>)=>void }){
  const canon = rag?.canon?.preview||''
  const lore  = rag?.lore?.preview||''
  const patt  = rag?.pattern?.preview||''
  const cCanon = covRate(canon, sp.text)
  const cLore  = covRate(lore, sp.text)
  const cPatt  = covRate(patt, sp.text)
  const cov = Math.max(cCanon, cLore, cPatt)
  const tip = `c=${cCanon.toFixed(2)} l=${cLore.toFixed(2)} p=${cPatt.toFixed(2)}`
  function beatColor(b?: string){
    if (!b) return 'bg-slate-200 text-slate-700'
    if (b==='BANter' || b==='Setup' || b.includes('Theme')) return 'bg-gray-200 text-gray-800'
    if (b==='PIVOT' || b.includes('Midpoint')) return 'bg-blue-200 text-blue-800'
    if (b==='PAYOFF' || b.includes('Finale') || b.includes('Aha')) return 'bg-purple-200 text-purple-800'
    if (b.includes('Fun&Games')) return 'bg-emerald-200 text-emerald-800'
    return 'bg-slate-200 text-slate-700'
  }
  return (
    <div className="border rounded p-3" onClick={onSelect}>
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <span className="font-mono">Turn {sp.turn}</span>
          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-white">{sp.speaker}</span>
          <span className={`px-2 py-0.5 rounded ${beatColor(beat)}`}>{beat||'-'}</span>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="text-xs px-2 py-1 border rounded hover:bg-slate-50"
            onClick={(e)=>{ e.stopPropagation(); onViewPrompts?.(e) }}>View Prompts</button>
        </div>
      </div>
      <div className="mt-2 whitespace-pre-wrap leading-relaxed">{sp.text}</div>
      <div className="mt-3 flex items-center gap-2" title={tip}>
        <div className="w-full bg-slate-100 rounded h-2">
          <div className={`h-2 rounded ${covColor(cov)}`} style={{ width: pct(cov) }} />
        </div>
        <span className="text-xs text-slate-500">{pct(cov)}</span>
      </div>
    </div>
  )
}
