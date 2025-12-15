import React from 'react'

type Row = { run_id: string, topic?: string|null, timestamp?: string }

export default function RunList({ rows, onPick }:{ rows: Row[], onPick:(rid:string)=>void }){
  // run_idから時刻部分を抽出 (run_YYYYMMDD_HHMMSS -> HH:MM)
  const formatTime = (run_id: string) => {
    const match = run_id.match(/run_\d{8}_(\d{2})(\d{2})(\d{2})/)
    if (match) {
      return `${match[1]}:${match[2]}`
    }
    return ''
  }

  return (
    <div className="space-y-1 text-sm">
      {rows.map(r=> (
        <button key={r.run_id} className="w-full text-left px-2 py-1.5 rounded hover:bg-slate-100 border border-transparent hover:border-slate-200" onClick={()=>onPick(r.run_id)}>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 font-mono">{formatTime(r.run_id)}</span>
            <span className="truncate flex-1">{r.topic || '(no topic)'}</span>
          </div>
        </button>
      ))}
    </div>
  )
}

