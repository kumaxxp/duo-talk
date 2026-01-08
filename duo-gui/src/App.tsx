import { useEffect, useMemo, useRef, useState } from 'react'
import ControlPanel from './components/ControlPanel'
import RunList from './components/RunList'
import TurnCard from './components/TurnCard'
import RagPanel from './components/RagPanel'
import CovSpark from './components/CovSpark'
import SettingsPanel from './components/SettingsPanel'
import LivePanel from './components/LivePanel'
import OwnerControlPanel from './components/OwnerControlPanel'
import ProviderPanel from './components/ProviderPanel'
import UnifiedRunPanel from './components/UnifiedRunPanel'
import ChatInputPanel from './components/ChatInputPanel'
import { covRate } from './hooks/useCov'
import type { DirectorEvent, RAGEvent, SpeakEvent } from './lib/types'
import PromptModal from './components/PromptModal'

const API = (import.meta as any).env?.VITE_API_BASE || ''

type TabType = 'unified' | 'runs' | 'settings' | 'live' | 'provider'

export default function App(){
  const [activeTab, setActiveTab] = useState<TabType>('runs')
  const [runs, setRuns] = useState<{run_id:string, topic?:string|null}[]>([])
  const [rid, setRid] = useState<string|undefined>()
  const [directors, setDirectors] = useState<Record<number, DirectorEvent>>({})
  const [rag, setRag] = useState<Record<number, RAGEvent>>({})
  const [speaks, setSpeaks] = useState<Record<number, SpeakEvent>>({})
  const [selected, setSelected] = useState<number|undefined>()
  const [prompts, setPrompts] = useState<Record<number, string>>({})
  const [modalTurn, setModalTurn] = useState<number|undefined>()
  const lastFocusRef = useRef<HTMLElement|null>(null)
  // Filters (speaker & beat)
  const [showA, setShowA] = useState(true)
  const [showB, setShowB] = useState(true)
  const [showBAN, setShowBAN] = useState(true)
  const [showPIV, setShowPIV] = useState(true)
  const [showPAY, setShowPAY] = useState(true)
  // Offline eval + style metrics
  const [ragScore, setRagScore] = useState<{f1?:number, cite?:number}|undefined>()
  const [styleRate, setStyleRate] = useState<number|undefined>()
  const autoPicked = useRef(false)
  // Intervention state (shared between LivePanel and OwnerControlPanel)
  const [interventionPaused, setInterventionPaused] = useState(false)

  // Clear state when run_id changes
  useEffect(() => {
    setDirectors({})
    setRag({})
    setSpeaks({})
    setPrompts({})
    setSelected(undefined)
  }, [rid])

  const listRuns = async ()=>{
    const r = await fetch(`${API}/api/run/list`)
    const js = await r.json()
    setRuns(js)
    if (!autoPicked.current && !rid && js[0]?.run_id){
      setRid(js[0].run_id)
      autoPicked.current = true
    }
  }
  useEffect(()=>{ listRuns(); const id=setInterval(listRuns, 5000); return ()=> clearInterval(id) },[])

  // Polling fallback (SSE has issues over network)
  useEffect(() => {
    if (!rid) return
    let stop = false
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/run/events?run_id=${encodeURIComponent(rid)}`)
        const events = await r.json()

        // Debug: Log polling results
        console.log(`[Poll] run_id=${rid}, events=${Array.isArray(events) ? events.length : 'N/A'}`)

        if (stop || !Array.isArray(events)) return

        const newDirectors: Record<number, DirectorEvent> = {}
        const newRag: Record<number, RAGEvent> = {}
        const newSpeaks: Record<number, SpeakEvent> = {}
        const newPrompts: Record<number, string> = {}

        for (const ev of events) {
          if (ev.event === 'director' && ev.turn !== undefined) {
            newDirectors[ev.turn] = ev
          } else if (ev.event === 'rag_select' && ev.turn !== undefined) {
            newRag[ev.turn] = ev
          } else if (ev.event === 'speak' && ev.turn !== undefined) {
            // beatが存在するイベントを優先（二重記録対策）
            const existing = newSpeaks[ev.turn]
            if (!existing || (ev.beat && !existing.beat)) {
              newSpeaks[ev.turn] = ev
            }
          } else if (ev.event === 'prompt_debug' && ev.turn !== undefined) {
            newPrompts[ev.turn] = ev.prompt_tail
          }
        }

        // Debug: Log parsed events
        const speakCount = Object.keys(newSpeaks).length
        if (speakCount > 0) {
          console.log(`[Poll] Parsed: speaks=${speakCount}, directors=${Object.keys(newDirectors).length}`)
        }

        setDirectors(newDirectors)
        setRag(newRag)
        setSpeaks(newSpeaks)
        setPrompts(newPrompts)
      } catch (e) {
        console.error('Polling error:', e)
      }
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => { stop = true; clearInterval(id) }
  }, [rid])

  // Fetch RAG Score (offline eval results) with light polling
  useEffect(()=>{
    let stop=false
    const pull = async ()=>{
      try{
        const r = await fetch(`${API}/api/rag/score`)
        const js = await r.json()
        if(!stop) setRagScore({ f1: js?.f1 ?? 0, cite: js?.citation_rate ?? 0 })
      }catch{}
    }
    pull()
    const id = setInterval(pull, 10000)
    return ()=> { stop=true; clearInterval(id) }
  }, [])

  // Fetch style adherence for current run
  useEffect(()=>{ (async()=>{
    if(!rid) return
    try{
      const r = await fetch(`${API}/api/run/style?run_id=${encodeURIComponent(rid)}`)
      const js = await r.json()
      setStyleRate(js?.style_ok_rate ?? undefined)
    }catch{}
  })() }, [rid, directors, speaks])

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

  // Prompt modal composing helper
  const modalTurnData = useMemo(()=>{
    if (modalTurn===undefined) return undefined
    const sp = speaks[modalTurn]
    const dir = directors[modalTurn]
    return sp? {
      turn: modalTurn,
      speaker: sp.speaker,
      beat: dir?.beat,
      rag: rag[modalTurn],
      prompt_tail: prompts[modalTurn],
      text: sp.text,
      // Director情報
      directorStatus: dir?.status,
      directorReason: dir?.reason,
      directorSuggestion: dir?.cut_cue,
      directorGuidance: dir?.guidance,  // 次ターンへの指示
    } : undefined
  }, [modalTurn, speaks, rag, directors, prompts])

  return (
    <>
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-semibold">DUO-TALK</h1>
          {/* Tab Navigation */}
          <nav className="flex gap-1 bg-slate-100 p-1 rounded-lg">
            <button
              onClick={() => setActiveTab('unified')}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'unified' ? 'bg-white shadow text-blue-600' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Unified
            </button>
            <button
              onClick={() => setActiveTab('runs')}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'runs' ? 'bg-white shadow text-slate-900' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Runs
            </button>
            <button
              onClick={() => setActiveTab('settings')}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'settings' ? 'bg-white shadow text-slate-900' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Vision Settings
            </button>
            <button
              onClick={() => setActiveTab('live')}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'live' ? 'bg-white shadow text-slate-900' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Live
            </button>
            <button
              onClick={() => setActiveTab('provider')}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'provider' ? 'bg-white shadow text-slate-900' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Provider
            </button>
          </nav>
        </div>
        {activeTab === 'runs' && (
          <div className="flex items-center gap-2 text-sm">
            {ragScore && <span className="px-2 py-0.5 rounded bg-slate-100">RAG Score F1 {(ragScore.f1!*100|0)}% / Cite {(ragScore.cite!*100|0)}%</span>}
            {styleRate!==undefined && <span className="px-2 py-0.5 rounded bg-slate-100">style遵守 {(styleRate*100|0)}%</span>}
            <span>avg</span>{covBadge(avg)}
            <span>payoff</span>{covBadge(payoffAvg)}{payoffAvg>=0.20 && <span className="ml-1 px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">Good</span>}
            <span>max</span>{covBadge(maxCov)}
            <nav className="text-slate-500 ml-2">Backend — <a className="underline" href="/docs">/docs</a></nav>
          </div>
        )}
      </header>

      {/* Unified Tab Content */}
      {activeTab === 'unified' && (
        <UnifiedRunPanel
          onRunComplete={(result) => {
            console.log('Run completed:', result.run_id, result.status)
          }}
        />
      )}

      {/* Runs Tab Content */}
      {activeTab === 'runs' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <section className="lg:col-span-1 space-y-3">
            <div className="p-4 bg-white rounded-lg shadow">
              <h2 className="font-medium mb-2">New Run</h2>
              <ControlPanel apiBase={API} onStarted={(r)=> { if(r){ autoPicked.current = true; setRid(r) } }} />
            </div>
            {/* Chat Input Panel */}
            <div className="p-4 bg-white rounded-lg shadow">
              <ChatInputPanel apiBase={API} onSendComplete={() => { console.log('Chat sent') }} />
            </div>
            {/* Owner Intervention Control */}
            <OwnerControlPanel
              apiBase={API}
              runId={rid}
              onPauseChange={setInterventionPaused}
            />
            <div className="p-4 bg-white rounded-lg shadow">
              <h2 className="font-medium mb-2">Runs</h2>
              <div className="max-h-64 overflow-auto md:max-h-80">
                <RunList rows={runs} onPick={(r)=> { autoPicked.current = true; setRid(r) }} />
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
              <div id={selected!==undefined? `rag-${selected}`: undefined}>
                <RagPanel rag={selected!==undefined ? rag[selected] : undefined} beat={selected!==undefined ? directors[selected]?.beat : undefined} />
              </div>
            </div>
          </section>
          <section className="lg:col-span-3 space-y-3">
            <div className="p-4 bg-white rounded-lg shadow">
              <div className="flex items-center justify-between mb-2">
                <h2 className="font-medium">Timeline</h2>
                <CovSpark values={covValues} />
              </div>
              <div className="space-y-3">
                {filteredTurns.map(t=> (
                  <TurnCard key={t} sp={speaks[t]} rag={rag[t]} beat={directors[t]?.beat}
                    directorStatus={directors[t]?.status} directorReason={directors[t]?.reason}
                    directorGuidance={directors[t]?.guidance}
                    onSelect={()=> { setSelected(t); requestAnimationFrame(()=>{ const el=document.getElementById(`rag-${t}`); el?.scrollIntoView({block:'center', behavior:'smooth'}) }) }}
                    onViewPrompts={(e)=> { lastFocusRef.current = e.currentTarget as HTMLElement; setModalTurn(t) }} />
                ))}
              </div>
            </div>
          </section>
        </div>
      )}

      {/* Settings Tab Content */}
      {activeTab === 'settings' && (
        <div className="p-4 bg-white rounded-lg shadow">
          <SettingsPanel apiBase={API} />
        </div>
      )}

      {/* Live Tab Content */}
      {activeTab === 'live' && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="lg:col-span-3 p-4 bg-white rounded-lg shadow">
            <h2 className="text-lg font-medium mb-4">Live Commentary - JetRacer</h2>
            <LivePanel
              jetracer_url="http://192.168.1.65:8000"
              externalPaused={interventionPaused}
            />
          </div>
          <div className="lg:col-span-1">
            <OwnerControlPanel
              apiBase={API}
              runId={rid}
              onPauseChange={setInterventionPaused}
            />
          </div>
        </div>
      )}

      {/* Provider Tab Content */}
      {activeTab === 'provider' && (
        <ProviderPanel apiBase={API} />
      )}
    </div>
    <PromptModal open={modalTurn!==undefined} onClose={()=> { setModalTurn(undefined); lastFocusRef.current?.focus() }} turn={modalTurnData} />
    </>
  )
}
