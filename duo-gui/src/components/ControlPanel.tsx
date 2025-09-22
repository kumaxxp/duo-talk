import React, { useState } from 'react'

export default function ControlPanel({ apiBase, onStarted }:{ apiBase: string, onStarted: (rid?:string)=>void }){
  const [topic,setTopic]=useState('')
  const [model,setModel]=useState('')
  const [maxTurns,setMax]=useState(8)
  const [seed,setSeed]=useState<number|''>(42)
  const [noRag,setNoRag]=useState(false)
  const start = async ()=>{
    const body = { topic, model, maxTurns, seed: (seed===''?undefined:seed), noRag }
    const r = await fetch(`${apiBase}/api/run/start`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) })
    const js = await r.json().catch(()=>({}))
    onStarted(js?.run_id)
  }
  return (
    <div className="space-y-2">
      <input className="w-full px-3 py-2 border rounded" placeholder="topic" value={topic} onChange={e=>setTopic(e.target.value)} />
      <input className="w-full px-3 py-2 border rounded" placeholder="model (e.g., gemma3:12b)" value={model} onChange={e=>setModel(e.target.value)} />
      <div className="grid grid-cols-3 gap-2">
        <input className="px-3 py-2 border rounded" type="number" placeholder="maxTurns" value={maxTurns} onChange={e=>setMax(parseInt(e.target.value||'8',10))} />
        <input className="px-3 py-2 border rounded" type="number" placeholder="seed" value={seed} onChange={e=>setSeed(e.target.value===''?'':parseInt(e.target.value,10))} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={noRag} onChange={e=>setNoRag(e.target.checked)} /> noRag</label>
      </div>
      <button className="px-3 py-2 bg-slate-900 text-white rounded hover:bg-slate-800" onClick={start}>Start</button>
    </div>
  )
}

