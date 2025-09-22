import React from 'react'

type Row = { run_id: string, topic?: string|null }

export default function RunList({ rows, onPick }:{ rows: Row[], onPick:(rid:string)=>void }){
  return (
    <div className="space-y-1 text-sm">
      {rows.map(r=> (
        <button key={r.run_id} className="w-full text-left px-2 py-1 rounded hover:bg-slate-100" onClick={()=>onPick(r.run_id)}>
          {r.run_id.slice(0,8)}… {r.topic||''}
        </button>
      ))}
    </div>
  )
}

