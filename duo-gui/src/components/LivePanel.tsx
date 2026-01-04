import React, { useState, useEffect, useRef, useCallback } from 'react'
import type { SignalsState, LiveDialogue, SilenceInfo, InterventionState } from '../lib/types'

const API = (import.meta as any).env?.VITE_API_BASE || ''

type Props = {
  jetracer_url?: string
  onInterventionStateChange?: (state: InterventionState) => void
  externalPaused?: boolean
}

export default function LivePanel({ jetracer_url = 'http://192.168.1.65:8000', onInterventionStateChange, externalPaused = false }: Props) {
  const [connected, setConnected] = useState(false)
  const [signals, setSignals] = useState<SignalsState | null>(null)
  const [dialogue, setDialogue] = useState<LiveDialogue[]>([])
  const [silence, setSilence] = useState<SilenceInfo | null>(null)
  const [running, setRunning] = useState(false)
  const [frameDesc, setFrameDesc] = useState('')
  const [interventionState, setInterventionState] = useState<InterventionState>('running')
  const dialogueEndRef = useRef<HTMLDivElement>(null)

  // Ref to track current running state for async operations
  const runningRef = useRef(running)
  useEffect(() => {
    runningRef.current = running
  }, [running])

  // Check intervention status
  const checkInterventionStatus = useCallback(async (): Promise<boolean> => {
    try {
      const resp = await fetch(`${API}/api/v2/intervention/status`)
      const data = await resp.json()
      if (data.status === 'ok') {
        const state = data.intervention.state as InterventionState
        setInterventionState(state)
        onInterventionStateChange?.(state)
        return state === 'running'
      }
    } catch (e) {
      console.error('Intervention check error:', e)
    }
    return true // Default to running if check fails
  }, [onInterventionStateChange])

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
    if (!connected) {
      console.log('fetchAndGenerate: not connected')
      return
    }

    // Check if still running (may have been stopped while waiting)
    if (!runningRef.current) {
      console.log('fetchAndGenerate: stopped by user, aborting')
      return
    }

    try {
      // Check intervention status first
      console.log('fetchAndGenerate: checking intervention status...')
      const canRun = await checkInterventionStatus()
      console.log('fetchAndGenerate: canRun =', canRun, 'interventionState =', interventionState)
      if (!canRun) {
        console.log('Dialogue generation paused by intervention')
        return
      }

      // Re-check running state after intervention check
      if (!runningRef.current) {
        console.log('fetchAndGenerate: stopped during intervention check, aborting')
        return
      }

      // Fetch JetRacer data
      const fetchResp = await fetch(`${API}/api/v2/jetracer/fetch`)
      const fetchData = await fetchResp.json()

      if (fetchData.status !== 'ok') return

      // Check if stopped during JetRacer fetch
      if (!runningRef.current) {
        console.log('fetchAndGenerate: stopped after JetRacer fetch, aborting')
        return
      }

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

      // Check if stopped while waiting for dialogue API response
      if (!runningRef.current) {
        console.log('fetchAndGenerate: stopped during dialogue generation, discarding result')
        return
      }

      const dialogueData = await dialogueResp.json()
      console.log('Dialogue API response:', dialogueData.type, dialogueData)

      if (dialogueData.type === 'dialogue') {
        // Final check before adding dialogue
        if (!runningRef.current) {
          console.log('fetchAndGenerate: stopped, not adding dialogue')
          return
        }
        console.log('Adding dialogue:', dialogueData.dialogue.length, 'turns')
        setDialogue(prev => [...prev, ...dialogueData.dialogue])
      } else if (dialogueData.type === 'paused') {
        console.log('Dialogue generation blocked by server: paused')
      }
    } catch (e) {
      console.error('Fetch error:', e)
    }
  }

  // Combined pause state: external (from OwnerControlPanel) OR internal (from polling)
  // RESUMING state allows dialogue generation (instruction is being applied)
  const isPaused = externalPaused || !['running', 'resuming'].includes(interventionState)

  // Auto-run loop - only run when running AND NOT paused
  useEffect(() => {
    if (!running) return
    if (isPaused) {
      console.log('Interval paused: externalPaused=', externalPaused, 'interventionState=', interventionState)
      return
    }

    console.log('Starting dialogue interval')
    const interval = setInterval(fetchAndGenerate, 3000)
    return () => {
      console.log('Stopping dialogue interval')
      clearInterval(interval)
    }
  }, [running, connected, dialogue, isPaused, externalPaused, interventionState])

  // Periodic intervention status check (even when not running dialogue)
  useEffect(() => {
    const checkInterval = setInterval(checkInterventionStatus, 1000)
    return () => clearInterval(checkInterval)
  }, [checkInterventionStatus])

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
            disabled={running || isPaused}
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
          {/* Intervention Status Indicator */}
          {isPaused && (
            <span className="px-3 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm font-medium">
              {interventionState === 'paused' ? 'PAUSED' :
               interventionState === 'processing' ? 'PROCESSING' :
               interventionState === 'query_back' ? 'QUERY BACK' :
               externalPaused ? 'PAUSED' :
               interventionState.toUpperCase()}
            </span>
          )}
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
      <div className="max-h-96 overflow-y-auto space-y-2 p-4 bg-white rounded-lg shadow relative">
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
        {/* Intervention Overlay */}
        {running && isPaused && (
          <div className="sticky bottom-0 left-0 right-0 p-3 bg-yellow-50 border-t border-yellow-200 text-center">
            <span className="text-yellow-800 font-medium">
              Dialogue paused - Use Owner Control to send instructions
            </span>
          </div>
        )}
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
