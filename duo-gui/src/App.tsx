import React, { useEffect, useMemo, useState } from 'react'
import ControlPanel from './components/ControlPanel'
import RunList from './components/RunList'
import TurnCard from './components/TurnCard'
import RagPanel from './components/RagPanel'
import CovSpark from './components/CovSpark'
import { useSSE } from './hooks/useSSE'
import { covRate } from './hooks/useCov'
import type { DirectorEvent, RAGEvent, SpeakEvent } from './lib/types'

const API = (import.meta as any).env?.VITE_API_BASE || ''

export default function App(){
  const [runs, setRuns] = useState<{run_id:string, topic?:string|null}[]>([])
  const [rid, setRid] = useState<string|undefined>()
  const [directors, setDirectors] = useState<Record<number, DirectorEvent>>({})
  const [rag, setRag] = useState<Record<number, RAGEvent>>({})
  const [speaks, setSpeaks] = useState<Record<number, SpeakEvent>>({})
  const [selected, setSelected] = useState<number|undefined>()

  const listRuns = async ()=>{
    const r = await fetch(`${API}/api/run/list`)
    const js = await r.json()
    setRuns(js)
    if (!rid && js[0]?.run_id) setRid(js[0].run_id)
  }
  useEffect(()=>{ listRuns(); const id=setInterval(listRuns, 5000); return ()=> clearInterval(id) },[])

  // SSE
  useSSE(rid? `${API}/api/run/stream?run_id=${encodeURIComponent(rid)}` : '', {
    director: (j:DirectorEvent)=> setDirectors(prev=> ({...prev, [j.turn]: j})),
    rag_select: (j:RAGEvent)=> setRag(prev=> ({...prev, [j.turn]: j})),
    speak: (j:SpeakEvent)=> setSpeaks(prev=> ({...prev, [j.turn]: j})),
  })

  const turns = useMemo(()=> Object.keys(speaks).map(n=>parseInt(n,10)).sort((a,b)=>a-b), [speaks])
  const covValues = useMemo(()=> turns.map(t=> {
    const sp = speaks[t]; const rg = rag[t]
    if(!sp) return 0
    return Math.max(
      covRate(rg?.canon?.preview||'', sp.text),
      covRate(rg?.lore?.preview||'', sp.text),
      covRate(rg?.pattern?.preview||'', sp.text),
    )
  }), [turns, speaks, rag])

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">DUO RUNS</h1>
        <nav className="text-sm text-slate-500">Backend UI — <a className="underline" href="/docs">/docs</a></nav>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <section className="space-y-3">
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">New Run</h2>
            <ControlPanel apiBase={API} onStarted={(r)=> r && setRid(r)} />
          </div>
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">Runs</h2>
            <RunList rows={runs} onPick={setRid} />
          </div>
        </section>
        <section className="lg:col-span-2 space-y-3">
          <div className="p-4 bg-white rounded-lg shadow">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-medium">Timeline</h2>
              <CovSpark values={covValues} />
            </div>
            <div className="space-y-3">
              {turns.map(t=> (
                <TurnCard key={t} sp={speaks[t]} rag={rag[t]} beat={directors[t]?.beat} onSelect={()=> setSelected(t)} />
              ))}
            </div>
          </div>
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">RAG Panel</h2>
            <RagPanel rag={selected? rag[selected]: undefined} beat={selected? directors[selected]?.beat: undefined} />
          </div>
        </section>
      </div>
    </div>
  )
}

