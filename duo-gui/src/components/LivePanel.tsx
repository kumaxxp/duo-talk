import React, { useState, useEffect, useRef } from 'react'
import type { SignalsState, LiveDialogue, SilenceInfo } from '../lib/types'

const API = (import.meta as any).env?.VITE_API_BASE || ''

type Props = {
  jetracer_url?: string
}

export default function LivePanel({ jetracer_url = 'http://192.168.1.65:8000' }: Props) {
  const [connected, setConnected] = useState(false)
  const [signals, setSignals] = useState<SignalsState | null>(null)
  const [dialogue, setDialogue] = useState<LiveDialogue[]>([])
  const [silence, setSilence] = useState<SilenceInfo | null>(null)
  const [running, setRunning] = useState(false)
  const [frameDesc, setFrameDesc] = useState('')
  const dialogueEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll dialogue
  useEffect(() => {
    dialogueEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [dialogue])

  const connect = async () => {
    try {
      const resp = await fetch(`${API}/api/v2/jetracer/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: jetracer_url, mode: 'vision' })
      })
      const data = await resp.json()
      if (data.status === 'ok') {
        setConnected(true)
      }
    } catch (e) {
      console.error('Connect error:', e)
    }
  }

  const fetchAndGenerate = async () => {
    if (!connected) return

    try {
      // Fetch JetRacer data
      const fetchResp = await fetch(`${API}/api/v2/jetracer/fetch`)
      const fetchData = await fetchResp.json()

      if (fetchData.status !== 'ok') return

      setFrameDesc(fetchData.frame_description)

      // Get signals state
      const sigResp = await fetch(`${API}/api/v2/signals`)
      const sigData = await sigResp.json()
      if (sigData.status === 'ok') {
        setSignals(sigData.state)
      }

      // Check silence
      const silResp = await fetch(`${API}/api/v2/silence/check`)
      const silData = await silResp.json()

      if (silData.should_silence) {
        setSilence(silData.silence)
        return
      }
      setSilence(null)

      // Generate dialogue
      const dialogueResp = await fetch(`${API}/api/v2/live/dialogue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          frame_description: fetchData.frame_description,
          history: dialogue.slice(-10),
          turns: 2
        })
      })
      const dialogueData = await dialogueResp.json()

      if (dialogueData.type === 'dialogue') {
        setDialogue(prev => [...prev, ...dialogueData.dialogue])
      }
    } catch (e) {
      console.error('Fetch error:', e)
    }
  }

  // Auto-run loop
  useEffect(() => {
    if (!running) return

    const interval = setInterval(fetchAndGenerate, 3000)
    return () => clearInterval(interval)
  }, [running, connected, dialogue])

  return (
    <div className="space-y-4">
      {/* Connection */}
      <div className="flex items-center gap-4">
        <input
          type="text"
          defaultValue={jetracer_url}
          className="flex-1 px-3 py-2 border rounded"
          placeholder="JetRacer URL"
        />
        <button
          onClick={connect}
          disabled={connected}
          className={`px-4 py-2 rounded ${connected ? 'bg-green-500 text-white' : 'bg-blue-500 text-white hover:bg-blue-600'}`}
        >
          {connected ? 'Connected' : 'Connect'}
        </button>
      </div>

      {/* Controls */}
      {connected && (
        <div className="flex items-center gap-4">
          <button
            onClick={() => setRunning(!running)}
            className={`px-4 py-2 rounded ${running ? 'bg-red-500' : 'bg-green-500'} text-white`}
          >
            {running ? 'Stop' : 'Start'}
          </button>
          <button
            onClick={fetchAndGenerate}
            disabled={running}
            className="px-4 py-2 bg-slate-200 rounded hover:bg-slate-300 disabled:opacity-50"
          >
            Single Fetch
          </button>
          <button
            onClick={() => setDialogue([])}
            className="px-4 py-2 bg-slate-200 rounded hover:bg-slate-300"
          >
            Clear
          </button>
        </div>
      )}

      {/* Frame Description */}
      {frameDesc && (
        <div className="p-3 bg-slate-100 rounded text-sm">
          <span className="text-slate-500">Frame: </span>
          {frameDesc}
        </div>
      )}

      {/* Silence Indicator */}
      {silence && (
        <div className="p-3 bg-purple-100 rounded flex items-center gap-2">
          <span className="text-2xl">Silence</span>
          <div>
            <div className="font-medium text-purple-800">Silence: {silence.type}</div>
            <div className="text-sm text-purple-600">Duration: {silence.duration}s</div>
          </div>
        </div>
      )}

      {/* Dialogue */}
      <div className="max-h-96 overflow-y-auto space-y-2 p-4 bg-white rounded-lg shadow">
        {dialogue.map((d, i) => (
          <div key={i} className={`p-2 rounded ${d.speaker === 'やな' ? 'bg-pink-50' : 'bg-blue-50'}`}>
            <div className="flex items-center gap-2">
              <span className="font-medium">{d.speaker}</span>
              {d.debug?.loop_detected && (
                <span className="px-1 text-xs bg-orange-200 text-orange-800 rounded">
                  Loop: {d.debug.strategy}
                </span>
              )}
              {d.debug?.few_shot_used && (
                <span className="px-1 text-xs bg-green-200 text-green-800 rounded">
                  Few-shot
                </span>
              )}
            </div>
            <p className="mt-1">{d.content}</p>
          </div>
        ))}
        <div ref={dialogueEndRef} />
      </div>

      {/* Signals State */}
      {signals && (
        <div className="p-3 bg-slate-50 rounded text-xs">
          <div className="flex flex-wrap gap-2">
            <span>Mode: {signals.jetracer_mode}</span>
            <span>Speed: {signals.current_speed.toFixed(2)}</span>
            <span>Turn: #{signals.turn_count}</span>
            <span>TopicDepth: {signals.topic_depth}</span>
            {signals.is_stale && <span className="text-yellow-600">Stale</span>}
          </div>
        </div>
      )}
    </div>
  )
}
