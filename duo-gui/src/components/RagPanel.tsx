import React from 'react'
import type { Beat, RAGEvent } from '../lib/types'

export default function RagPanel({ rag, beat }:{ rag?: RAGEvent, beat?: Beat }){
  if (!rag) return <div className="text-slate-400">ターンを選択</div>
  const rows: Array<[string, {path?:string, preview?:string|null} | null | undefined]> = [
    ['pattern', rag.pattern],
    ['canon', rag.canon],
    ['lore', rag.lore],
  ]
  const ordered = (()=>{
    if (!beat) return [['canon', rag.canon], ['lore', rag.lore], ['pattern', rag.pattern]] as typeof rows
    if (beat==='PAYOFF' || beat.includes('Finale')) return rows
    if (beat==='Fun&Games') return [['lore', rag.lore], ['canon', rag.canon], ['pattern', rag.pattern]] as typeof rows
    return [['canon', rag.canon], ['lore', rag.lore], ['pattern', rag.pattern]] as typeof rows
  })()
  return (
    <div>
      <h3 className="text-sm font-semibold mb-2">RAG Hints</h3>
      {ordered.map(([k,v])=>{
        const hi = (beat==='PAYOFF' || (beat||'').includes('Finale')) && k==='pattern'
        return (
          <div key={k} className={`p-2 rounded border mb-2 ${hi?'ring-2 ring-violet-400 bg-violet-50':''}`}>
            <span className="text-xs font-medium mr-2">{k}</span>
            <span className="text-sm" title={v?.path||''}>{v?.preview ?? '-'}</span>
          </div>
        )
      })}
    </div>
  )
}
