import { useEffect, useMemo, useRef, useState } from 'react'
import RunList from './components/RunList'
import TurnCard from './components/TurnCard'
import RagPanel from './components/RagPanel'
import CovSpark from './components/CovSpark'
import SettingsPanel from './components/SettingsPanel'
import ProviderPanel from './components/ProviderPanel'
import { covRate } from './hooks/useCov'
import type { DirectorEvent, RAGEvent, SpeakEvent, ThoughtEvent, UnifiedSSEEvent } from './lib/types'
import PromptModal from './components/PromptModal'
import LogTerminal from './components/LogTerminal'
import UnifiedInputPanel from './components/UnifiedInputPanel'
import ThoughtLogItem from './components/ThoughtLogItem'

const API = (import.meta as any).env?.VITE_API_BASE || ''

type TabType = 'runs' | 'settings' | 'provider'

export default function App() {
  const [activeTab, setActiveTab] = useState<TabType>('runs')
  const [runs, setRuns] = useState<{ run_id: string, topic?: string | null | undefined }[]>([])
  const [rid, setRid] = useState<string | undefined>()
  const [directors, setDirectors] = useState<Record<number, DirectorEvent>>({})
  const [rag, setRag] = useState<Record<number, RAGEvent>>({})
  const [speaks, setSpeaks] = useState<Record<number, SpeakEvent>>({})
  const [selected, setSelected] = useState<number | undefined>()
  const [prompts, setPrompts] = useState<Record<number, string>>({})
  const [thoughtLog, setThoughtLog] = useState<ThoughtEvent[]>([])
  const [modalTurn, setModalTurn] = useState<number | undefined>()
  const lastFocusRef = useRef<HTMLElement | null>(null)
  const logEndRef = useRef<HTMLDivElement | null>(null)

  const turns = useMemo(() => Object.keys(speaks).map(n => parseInt(n, 10)).sort((a, b) => a - b), [speaks])
  // Filters removed as per request
  const filteredTurns = turns // Show all turns

  // Offline eval + style metrics
  const [ragScore, setRagScore] = useState<{ f1?: number, cite?: number } | undefined>()
  const [styleRate, setStyleRate] = useState<number | undefined>()
  const autoPicked = useRef(false)
  // Intervention state (shared between LivePanel and OwnerControlPanel)
  const [interventionPaused, setInterventionPaused] = useState(false)

  // Clear state when run_id changes
  useEffect(() => {
    setDirectors({})
    setRag({})
    setSpeaks({})
    setPrompts({})
    setThoughtLog([])
    // Selected removed
  }, [rid])



  const listRuns = async () => {
    const r = await fetch(`${API}/api/run/list`)
    const js = await r.json()
    setRuns(js)
    if (!autoPicked.current && !rid && js[0]?.run_id) {
      setRid(js[0].run_id)
      autoPicked.current = true
    }
  }
  useEffect(() => { listRuns(); const id = setInterval(listRuns, 5000); return () => clearInterval(id) }, [])

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
        const newThoughts: ThoughtEvent[] = []

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
          } else if (ev.event === 'thought') {
            newThoughts.push(ev as ThoughtEvent)
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

        // Sort thoughts by timestamp and set
        newThoughts.sort((a, b) => (a.ts && b.ts ? a.ts.localeCompare(b.ts) : 0))
        // Only update if length changed to optimize
        setThoughtLog(prev => {
          if (prev.length !== newThoughts.length) return newThoughts
          // Check last element
          if (prev.length > 0 && newThoughts.length > 0 && prev[prev.length - 1].ts !== newThoughts[newThoughts.length - 1].ts) return newThoughts
          return prev
        })

      } catch (e) {
        console.error('Polling error:', e)
      }
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => { stop = true; clearInterval(id) }
  }, [rid])

  // Fetch RAG Score (offline eval results) with light polling
  useEffect(() => {
    let stop = false
    const pull = async () => {
      try {
        const r = await fetch(`${API}/api/rag/score`)
        const js = await r.json()
        if (!stop) setRagScore({ f1: js?.f1 ?? 0, cite: js?.citation_rate ?? 0 })
      } catch { }
    }
    pull()
    const id = setInterval(pull, 10000)
    return () => { stop = true; clearInterval(id) }
  }, [])

  // Fetch style adherence for current run
  useEffect(() => {
    (async () => {
      if (!rid) return
      try {
        const r = await fetch(`${API}/api/run/style?run_id=${encodeURIComponent(rid)}`)
        const js = await r.json()
        setStyleRate(js?.style_ok_rate ?? undefined)
      } catch { }
    })()
  }, [rid, directors, speaks])



  // Metrics calculation (simplified)
  const covValues = useMemo(() => turns.map(t => {
    const sp = speaks[t]; const rg = rag[t]
    if (!sp) return 0
    return Math.max(
      covRate(rg?.canon?.preview || '', sp.text),
      covRate(rg?.lore?.preview || '', sp.text),
      covRate(rg?.pattern?.preview || '', sp.text),
    )
  }), [turns, speaks, rag])

  const avg = useMemo(() => covValues.length ? covValues.reduce((a, b) => a + b, 0) / covValues.length : 0, [covValues])
  const payoffValues = useMemo(() => turns.filter(t => directors[t]?.beat === 'PAYOFF').map(t => {
    // reuse simple calc logic if needed or simplify
    return 0 // Simplified for now as requested visualization wasn't focused on metrics
  }), [turns, directors])
  const payoffAvg = 0
  const maxCov = useMemo(() => covValues.length ? Math.max(...covValues) : 0, [covValues])

  function covBadge(c: number) {
    const cls = c < 0.10 ? 'bg-slate-200 text-slate-700' : c < 0.20 ? 'bg-amber-200 text-amber-900' : 'bg-emerald-200 text-emerald-900'
    return <span className={`px-2 py-0.5 rounded text-xs ${cls}`}>{Math.round(c * 100)}%</span>
  }

  // Prompt modal composing helper
  const modalTurnData = useMemo(() => {
    if (modalTurn === undefined) return undefined
    const sp = speaks[modalTurn]
    const dir = directors[modalTurn]
    return sp ? {
      turn: modalTurn,
      speaker: sp.speaker,
      beat: dir?.beat,
      rag: rag[modalTurn],
      prompt_tail: prompts[modalTurn],
      text: sp.text,
      // Director情報
      directorStatus: dir?.status,
      directorReason: dir?.reason,
      directorSuggestion: dir?.cut_cue ? dir.cut_cue : undefined,
      directorGuidance: dir?.guidance ? dir.guidance : undefined,  // 次ターンへの指示
    } : undefined
  }, [modalTurn, speaks, rag, directors, prompts])

  return (
    <>
      <div className="h-screen w-full flex flex-col bg-gray-100 overflow-hidden">
        <header className="flex-none flex items-center justify-between p-3 bg-white border-b shadow-sm z-10">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold text-slate-800">DUO-TALK</h1>
            {/* Tab Navigation */}
            <nav className="flex gap-1 bg-slate-100 p-1 rounded-lg">
              <button
                onClick={() => setActiveTab('runs')}
                className={`px-3 py-1 rounded text-xs font-semibold transition-colors ${activeTab === 'runs' ? 'bg-white shadow text-slate-900' : 'text-slate-500 hover:text-slate-900'
                  }`}
              >
                Runs
              </button>
              <button
                onClick={() => setActiveTab('settings')}
                className={`px-3 py-1 rounded text-xs font-semibold transition-colors ${activeTab === 'settings' ? 'bg-white shadow text-slate-900' : 'text-slate-500 hover:text-slate-900'
                  }`}
              >
                Settings
              </button>
              <button
                onClick={() => setActiveTab('provider')}
                className={`px-3 py-1 rounded text-xs font-semibold transition-colors ${activeTab === 'provider' ? 'bg-white shadow text-slate-900' : 'text-slate-500 hover:text-slate-900'
                  }`}
              >
                Provider
              </button>
            </nav>
          </div>
          {activeTab === 'runs' && (
            <div className="flex items-center gap-2 text-xs text-slate-600">
              {ragScore && <span className="px-2 py-1 rounded bg-slate-50 border">RAG F1 {(ragScore.f1! * 100 | 0)}%</span>}
              {styleRate !== undefined && <span className="px-2 py-1 rounded bg-slate-50 border">Style {(styleRate * 100 | 0)}%</span>}
              <span>Avg Coverage</span>{covBadge(avg)}
            </div>
          )}
        </header>

        {/* Mian Content Area */}
        <div className="flex-1 min-h-0 overflow-hidden">
          {activeTab === 'runs' && (
            <div className="h-full flex flex-col lg:flex-row overflow-hidden">
              {/* Left Column: Run List (History) */}
              <section className="flex-none w-full lg:w-80 h-full bg-slate-50 flex flex-col border-r border-gray-200 overflow-hidden">
                <div className="p-4 bg-white shadow-sm border-b z-10">
                  <h2 className="text-xs font-bold text-slate-400 uppercase">Run History</h2>
                </div>
                <div className="flex-1 overflow-y-auto min-h-0 p-2">
                  <RunList rows={runs} onPick={(r) => { autoPicked.current = true; setRid(r) }} />
                </div>
              </section>

              {/* Right Column: Timeline & Logs */}
              <section className="flex-1 flex flex-col h-full bg-white relative min-w-0 overflow-hidden">
                {/* Timeline Area (Scrollable) */}
                <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 scroll-smooth">
                  {/* Header/Sparkline */}
                  <div className="sticky top-0 bg-white/90 backdrop-blur z-10 py-2 border-b flex justify-between items-center mb-4">
                    <h2 className="font-bold text-lg text-slate-800">Timeline</h2>
                    <CovSpark values={covValues} />
                  </div>

                  {/* Merged Timeline: Thoughts + Turns */}
                  <div className="space-y-6 pb-4">
                    {turns.length === 0 && <div className="text-center text-gray-400 py-10">Waiting for events...</div>}

                    {turns.map(t => {
                      // Filter thoughts for this turn
                      const turnThoughts = thoughtLog.filter(th => th.turn === t);

                      return (
                        <div key={t} className="space-y-2 relative">
                          {/* Turn Number Indicator */}
                          <div className="absolute -left-3 top-0 bottom-0 border-l-2 border-slate-100"></div>

                          {/* Thoughts for this turn */}
                          {turnThoughts.length > 0 && (
                            <div className="ml-2 space-y-2 mb-2">
                              {turnThoughts.map((log, i) => (
                                <ThoughtLogItem key={`${t}-thought-${i}`} log={log} />
                              ))}
                            </div>
                          )}

                          {/* The Actual Turn Card */}
                          <TurnCard
                            sp={speaks[t]}
                            rag={rag[t]}
                            beat={directors[t]?.beat}
                            directorStatus={directors[t]?.status}
                            directorReason={directors[t]?.reason}
                            directorGuidance={directors[t]?.guidance || undefined}
                            onViewPrompts={(e) => { lastFocusRef.current = e.currentTarget as HTMLElement; setModalTurn(t) }}
                          />
                        </div>
                      )
                    })}
                    <div ref={logEndRef} />
                  </div>
                </div>

                {/* Unified Input Panel */}
                <UnifiedInputPanel
                  apiBase={API}
                  runId={rid}
                  onRunStarted={(id) => { setRid(id); autoPicked.current = true; }}
                  onPauseChange={setInterventionPaused}
                />

                {/* Granular Log Terminal (Fixed at Bottom, Collapsed by default? or Small?) */}
                <div className="flex-none p-2 border-t bg-[#1e1e1e]">
                  <LogTerminal />
                </div>
              </section>
            </div>
          )}

          {/* Settings Tab Content */}
          {activeTab === 'settings' && (
            <div className="p-6 h-full overflow-y-auto">
              <div className="max-w-3xl mx-auto bg-white rounded-xl shadow-lg border p-6">
                <SettingsPanel apiBase={API} />
              </div>
            </div>
          )}

          {/* Provider Tab Content */}
          {activeTab === 'provider' && (
            <div className="p-6 h-full overflow-y-auto">
              <div className="max-w-4xl mx-auto">
                <ProviderPanel apiBase={API} />
              </div>
            </div>
          )}
        </div>
      </div>
      <PromptModal open={modalTurn !== undefined} onClose={() => { setModalTurn(undefined); lastFocusRef.current?.focus() }} turn={modalTurnData} />
    </>
  )
}
