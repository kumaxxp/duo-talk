import React, { useEffect, useMemo, useState } from 'react'
import ControlPanel from './components/ControlPanel'
import RunList from './components/RunList'
import TurnCard from './components/TurnCard'
import RagPanel from './components/RagPanel'
import CovSpark from './components/CovSpark'
import { useSSE } from './hooks/useSSE'
import { covRate } from './hooks/useCov'
import type { DirectorEvent, RAGEvent, SpeakEvent, PromptDbg } from './lib/types'

const API = (import.meta as any).env?.VITE_API_BASE || ''

export default function App(){
  const [runs, setRuns] = useState<{run_id:string, topic?:string|null}[]>([])
  const [rid, setRid] = useState<string|undefined>()
  const [directors, setDirectors] = useState<Record<number, DirectorEvent>>({})
  const [rag, setRag] = useState<Record<number, RAGEvent>>({})
  const [speaks, setSpeaks] = useState<Record<number, SpeakEvent>>({})
  const [selected, setSelected] = useState<number|undefined>()
  const [selectedSrc, setSelectedSrc] = useState<'live'|'A'|'B'>('live')
  const [prompts, setPrompts] = useState<Record<number, string>>({})
  const [modalTurn, setModalTurn] = useState<number|undefined>()
  const [modalSrc, setModalSrc] = useState<'live'|'A'|'B'>('live')
  // Filters (speaker & beat)
  const [showA, setShowA] = useState(true)
  const [showB, setShowB] = useState(true)
  const [showBAN, setShowBAN] = useState(true)
  const [showPIV, setShowPIV] = useState(true)
  const [showPAY, setShowPAY] = useState(true)
  // Compare states
  const [runA, setRunA] = useState<string|undefined>()
  const [runB, setRunB] = useState<string|undefined>()
  const [cmpA, setCmpA] = useState<{directors:Record<number,DirectorEvent>, rag:Record<number,RAGEvent>, speaks:Record<number,SpeakEvent>, prompts:Record<number,string>}|undefined>()
  const [cmpB, setCmpB] = useState<{directors:Record<number,DirectorEvent>, rag:Record<number,RAGEvent>, speaks:Record<number,SpeakEvent>, prompts:Record<number,string>}|undefined>()

  const listRuns = async ()=>{
    const r = await fetch(`${API}/api/run/list`)
    const js = await r.json()
    setRuns(js)
    if (!rid && js[0]?.run_id) setRid(js[0].run_id)
  }
  useEffect(()=>{ listRuns(); const id=setInterval(listRuns, 5000); return ()=> clearInterval(id) },[])
  // Initialize compare defaults from recent runs
  useEffect(()=>{
    if (!runA && runs[0]?.run_id) setRunA(runs[0].run_id)
    if (!runB && runs[1]?.run_id) setRunB(runs[1].run_id)
  }, [runs])

  // Load events for compare
  const loadRunEvents = async (run_id:string)=>{
    const r = await fetch(`${API}/api/run/events?run_id=${encodeURIComponent(run_id)}`)
    const rows: any[] = await r.json()
    const dd: Record<number, DirectorEvent> = {}
    const rr: Record<number, RAGEvent> = {}
    const ss: Record<number, SpeakEvent> = {}
    const pp: Record<number, string> = {}
    for (const j of rows){
      if (j.event === 'director') dd[j.turn] = j as DirectorEvent
      if (j.event === 'rag_select') rr[j.turn] = j as RAGEvent
      if (j.event === 'speak') ss[j.turn] = j as SpeakEvent
      if (j.event === 'prompt_debug') pp[j.turn] = (j as any).prompt_tail || ''
    }
    return {directors: dd, rag: rr, speaks: ss, prompts: pp}
  }
  useEffect(()=>{ (async()=>{ if(runA){ setCmpA(await loadRunEvents(runA)) } })() }, [runA])
  useEffect(()=>{ (async()=>{ if(runB){ setCmpB(await loadRunEvents(runB)) } })() }, [runB])

  // SSE
  useSSE(rid? `${API}/api/run/stream?run_id=${encodeURIComponent(rid)}` : '', {
    director: (j:DirectorEvent)=> setDirectors(prev=> ({...prev, [j.turn]: j})),
    rag_select: (j:RAGEvent)=> setRag(prev=> ({...prev, [j.turn]: j})),
    speak: (j:SpeakEvent)=> setSpeaks(prev=> ({...prev, [j.turn]: j})),
    prompt_debug: (j:PromptDbg)=> setPrompts(prev=> ({...prev, [j.turn]: j.prompt_tail})),
  })

  const turns = useMemo(()=> Object.keys(speaks).map(n=>parseInt(n,10)).sort((a,b)=>a-b), [speaks])
  const filteredTurns = useMemo(()=> {
    return turns.filter(t => {
      const sp = speaks[t]
      const dt = directors[t]
      if (!sp) return false
      if ((sp.speaker==='A' && !showA) || (sp.speaker==='B' && !showB)) return false
      const beat = dt?.beat
      if ((beat==='BANter' && !showBAN) || (beat==='PIVOT' && !showPIV) || (beat==='PAYOFF' && !showPAY)) return false
      return true
    })
  }, [turns, speaks, directors, showA, showB, showBAN, showPIV, showPAY])
  const covValues = useMemo(()=> filteredTurns.map(t=> {
    const sp = speaks[t]; const rg = rag[t]
    if(!sp) return 0
    return Math.max(
      covRate(rg?.canon?.preview||'', sp.text),
      covRate(rg?.lore?.preview||'', sp.text),
      covRate(rg?.pattern?.preview||'', sp.text),
    )
  }), [filteredTurns, speaks, rag])

  const avg = useMemo(()=> covValues.length? covValues.reduce((a,b)=>a+b,0)/covValues.length : 0, [covValues])
  const payoffValues = useMemo(()=> filteredTurns.filter(t=> directors[t]?.beat==='PAYOFF').map(t=> {
    const sp = speaks[t]
    const rg = rag[t]
    if(!sp) return 0
    return Math.max(
      covRate(rg?.canon?.preview||'', sp.text),
      covRate(rg?.lore?.preview||'', sp.text),
      covRate(rg?.pattern?.preview||'', sp.text),
    )
  }), [filteredTurns, directors, rag, speaks])
  const payoffAvg = useMemo(()=> payoffValues.length? payoffValues.reduce((a,b)=>a+b,0)/payoffValues.length : 0, [payoffValues])
  const maxCov = useMemo(()=> covValues.length? Math.max(...covValues) : 0, [covValues])

  function covBadge(c:number){
    const cls = c<0.10? 'bg-slate-200 text-slate-700' : c<0.20? 'bg-amber-200 text-amber-900' : 'bg-emerald-200 text-emerald-900'
    return <span className={`px-2 py-0.5 rounded text-xs ${cls}`}>{Math.round(c*100)}%</span>
  }

  function extractHints(turn:number){
    const tail = prompts[turn]||''
    const lines = tail.split(/\n/).filter(l=> /\[?内蔵ヒント\]?/.test(l))
    return lines.join('\n') || '(no hints)'
  }

  function highlight(text:string, turn:number, src:'live'|'A'|'B'='live'){
    const hints = src==='A' ? (cmpA?.prompts?.[turn]||'') : src==='B' ? (cmpB?.prompts?.[turn]||'') : extractHints(turn)
    const toks = new Set(hints.match(/[A-Za-z0-9ぁ-んァ-ン一-龯]{2,}/g) || [])
    let out = text.replace(/&/g,'&amp;').replace(/</g,'&lt;')
    Array.from(toks).sort((a,b)=> b.length - a.length).forEach(tok=>{
      const re = new RegExp(tok.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')
      out = out.replace(re, m=> `<mark>${m}</mark>`)
    })
    return out
  }

  return (
    <>
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">DUO RUNS</h1>
        <div className="flex items-center gap-2 text-sm">
          <span>avg</span>{covBadge(avg)}
          <span>payoff</span>{covBadge(payoffAvg)}{payoffAvg>=0.20 && <span className="ml-1 px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">Good</span>}
          <span>max</span>{covBadge(maxCov)}
          <nav className="text-slate-500 ml-2">Backend — <a className="underline" href="/docs">/docs</a></nav>
        </div>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <section className="space-y-3">
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">New Run</h2>
            <ControlPanel apiBase={API} onStarted={(r)=> r && setRid(r)} />
          </div>
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">Runs</h2>
            <div className="max-h-64 overflow-auto md:max-h-80">
              <RunList rows={runs} onPick={setRid} />
            </div>
          </div>
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">Compare</h2>
            <div className="space-y-2 text-sm">
              <label className="block">Run A
                <select className="mt-1 w-full border rounded px-2 py-1" value={runA||''} onChange={e=> setRunA(e.target.value||undefined)}>
                  <option value="">(select)</option>
                  {runs.map(r=> (
                    <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0,8)}… {r.topic||''}</option>
                  ))}
                </select>
              </label>
              <label className="block">Run B
                <select className="mt-1 w-full border rounded px-2 py-1" value={runB||''} onChange={e=> setRunB(e.target.value||undefined)}>
                  <option value="">(select)</option>
                  {runs.map(r=> (
                    <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0,8)}… {r.topic||''}</option>
                  ))}
                </select>
              </label>
              <p className="text-slate-500">Choose two runs to compare side-by-side.</p>
            </div>
          </div>
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">Filters</h2>
            <div className="flex flex-wrap gap-2 text-sm">
              <label className="flex items-center gap-1"><input type="checkbox" checked={showA} onChange={e=>setShowA(e.target.checked)} /> Speaker A</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={showB} onChange={e=>setShowB(e.target.checked)} /> Speaker B</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={showBAN} onChange={e=>setShowBAN(e.target.checked)} /> BANter</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={showPIV} onChange={e=>setShowPIV(e.target.checked)} /> PIVOT</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={showPAY} onChange={e=>setShowPAY(e.target.checked)} /> PAYOFF</label>
            </div>
          </div>
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-2">RAG Panel</h2>
            {(()=>{
              const rsel = selected===undefined ? undefined : (
                selectedSrc==='A' ? cmpA?.rag[selected] : selectedSrc==='B' ? cmpB?.rag[selected] : rag[selected]
              )
              const bsel = selected===undefined ? undefined : (
                selectedSrc==='A' ? cmpA?.directors?.[selected]?.beat : selectedSrc==='B' ? cmpB?.directors?.[selected]?.beat : directors[selected]?.beat
              )
              return <RagPanel rag={rsel} beat={bsel} />
            })()}
          </div>
        </section>
        <section className="lg:col-span-2 space-y-3">
          <div className="p-4 bg-white rounded-lg shadow">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-medium">Timeline</h2>
              <CovSpark values={covValues} />
            </div>
             <div className="space-y-3">
               {filteredTurns.map(t=> (
                 <TurnCard key={t} sp={speaks[t]} rag={rag[t]} beat={directors[t]?.beat}
                   onSelect={()=> { setSelected(t); setSelectedSrc('live') }}
                   onViewPrompts={()=> { setModalTurn(t); setModalSrc('live') }} />
               ))}
             </div>
          </div>
          <div className="p-4 bg-white rounded-lg shadow">
            <h2 className="font-medium mb-3">Compare</h2>
            {(cmpA || cmpB) ? (
              <div className="space-y-3">
                {Array.from(new Set([
                  ...Object.keys(cmpA?.speaks||{}),
                  ...Object.keys(cmpB?.speaks||{}),
                  ...Object.keys(cmpA?.directors||{}),
                  ...Object.keys(cmpB?.directors||{}),
                ].map(n=>parseInt(n,10)))).sort((a,b)=>a-b).map(t=> (
                  <div key={t} className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      {cmpA?.speaks?.[t] ? (
                        <TurnCard sp={cmpA.speaks[t]} rag={cmpA.rag?.[t]} beat={cmpA.directors?.[t]?.beat}
                          onSelect={()=> { setSelected(t); setSelectedSrc('A') }}
                          onViewPrompts={()=> { setModalTurn(t); setModalSrc('A') }} />
                      ) : (
                        <TurnCard sp={{ ts:'', event:'speak', run_id: runA||'', turn: t, speaker: 'A', text: '∅' }} beat={cmpA?.directors?.[t]?.beat}
                          onSelect={()=> { setSelected(t); setSelectedSrc('A') }}
                        />
                      )}
                    </div>
                    <div>
                      {cmpB?.speaks?.[t] ? (
                        <TurnCard sp={cmpB.speaks[t]} rag={cmpB.rag?.[t]} beat={cmpB.directors?.[t]?.beat}
                          onSelect={()=> { setSelected(t); setSelectedSrc('B') }}
                          onViewPrompts={()=> { setModalTurn(t); setModalSrc('B') }} />
                      ) : (
                        <TurnCard sp={{ ts:'', event:'speak', run_id: runB||'', turn: t, speaker: 'A', text: '∅' }} beat={cmpB?.directors?.[t]?.beat}
                          onSelect={()=> { setSelected(t); setSelectedSrc('B') }}
                        />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-500 text-sm">Select Run A and Run B to view side-by-side comparison.</p>
            )}
          </div>
        </section>
      </div>
    </div>
    {modalTurn!==undefined && (
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center" onClick={()=> setModalTurn(undefined)}>
        <div className="bg-white text-slate-900 max-w-4xl w-full rounded shadow p-4" onClick={e=>e.stopPropagation()}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-semibold">Prompts vs Utterance — Turn {modalTurn}</h3>
            <button className="text-sm px-2 py-1 border rounded" onClick={()=> setModalTurn(undefined)}>Close</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <pre className="whitespace-pre-wrap p-2 border rounded bg-slate-50">{
              modalSrc==='A' ? (cmpA?.prompts?.[modalTurn] || '(no hints)') :
              modalSrc==='B' ? (cmpB?.prompts?.[modalTurn] || '(no hints)') :
              extractHints(modalTurn)
            }</pre>
            <div className="p-2 border rounded bg-slate-50" dangerouslySetInnerHTML={{__html:
              modalSrc==='A' ? highlight(cmpA?.speaks?.[modalTurn!]?.text||'', modalTurn!, 'A') :
              modalSrc==='B' ? highlight(cmpB?.speaks?.[modalTurn!]?.text||'', modalTurn!, 'B') :
              highlight(speaks[modalTurn!]?.text||'', modalTurn!, 'live')
            }} />
          </div>
        </div>
      </div>
    )}
    </>
  )
}
