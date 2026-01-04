import React, { useState, useEffect, useCallback } from 'react'
import type {
  InterventionState,
  InterventionStatus,
  InterventionResult,
  InterventionLogEntry,
  QueryBack
} from '../lib/types'

interface OwnerControlPanelProps {
  apiBase: string
  runId?: string
}

export default function OwnerControlPanel({ apiBase, runId }: OwnerControlPanelProps) {
  const [status, setStatus] = useState<InterventionStatus | null>(null)
  const [log, setLog] = useState<InterventionLogEntry[]>([])
  const [message, setMessage] = useState('')
  const [queryBack, setQueryBack] = useState<QueryBack | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch intervention status
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/v2/intervention/status`)
      const data = await res.json()
      if (data.status === 'ok') {
        setStatus(data.intervention)
      }
    } catch (e) {
      console.error('Failed to fetch intervention status:', e)
    }
  }, [apiBase])

  // Fetch intervention log
  const fetchLog = useCallback(async () => {
    try {
      const url = runId
        ? `${apiBase}/api/v2/intervention/log?run_id=${runId}`
        : `${apiBase}/api/v2/intervention/log`
      const res = await fetch(url)
      const data = await res.json()
      if (data.status === 'ok') {
        setLog(data.log)
      }
    } catch (e) {
      console.error('Failed to fetch intervention log:', e)
    }
  }, [apiBase, runId])

  // Poll status and log
  useEffect(() => {
    fetchStatus()
    fetchLog()
    const interval = setInterval(() => {
      fetchStatus()
      fetchLog()
    }, 2000)
    return () => clearInterval(interval)
  }, [fetchStatus, fetchLog])

  // Pause dialogue
  const handlePause = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/v2/intervention/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId || 'default' })
      })
      const data = await res.json()
      if (data.status === 'error') {
        setError(data.message)
      } else {
        fetchStatus()
        fetchLog()
      }
    } catch (e) {
      setError('Failed to pause')
    } finally {
      setLoading(false)
    }
  }

  // Resume dialogue
  const handleResume = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/v2/intervention/resume`, {
        method: 'POST'
      })
      const data = await res.json()
      if (data.status === 'error') {
        setError(data.message)
      } else {
        setQueryBack(null)
        fetchStatus()
        fetchLog()
      }
    } catch (e) {
      setError('Failed to resume')
    } finally {
      setLoading(false)
    }
  }

  // Send instruction
  const handleSend = async () => {
    if (!message.trim()) return

    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/v2/intervention/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, type: 'instruction' })
      })
      const data = await res.json()

      if (data.status === 'error') {
        setError(data.result?.error || data.message)
      } else {
        const result: InterventionResult = data.result
        if (result.needs_clarification && result.query_back) {
          setQueryBack(result.query_back)
        } else {
          setMessage('')
          fetchStatus()
          fetchLog()
        }
      }
    } catch (e) {
      setError('Failed to send instruction')
    } finally {
      setLoading(false)
    }
  }

  // Answer query back
  const handleAnswer = async (answer: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/v2/intervention/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer })
      })
      const data = await res.json()

      if (data.status === 'error') {
        setError(data.result?.error || data.message)
      } else {
        setQueryBack(null)
        setMessage('')
        fetchStatus()
        fetchLog()
      }
    } catch (e) {
      setError('Failed to answer')
    } finally {
      setLoading(false)
    }
  }

  const state: InterventionState = status?.state || 'running'
  const isRunning = state === 'running'
  const isPaused = state === 'paused' || state === 'processing'
  const isQueryBack = state === 'query_back'

  const getStateLabel = (s: InterventionState) => {
    switch (s) {
      case 'running': return 'RUNNING'
      case 'paused': return 'PAUSED'
      case 'processing': return 'PROCESSING'
      case 'query_back': return 'QUERY BACK'
      case 'resuming': return 'RESUMING'
      default: return s
    }
  }

  const getStateColor = (s: InterventionState) => {
    switch (s) {
      case 'running': return 'bg-green-500'
      case 'paused': return 'bg-yellow-500'
      case 'processing': return 'bg-blue-500'
      case 'query_back': return 'bg-purple-500'
      case 'resuming': return 'bg-cyan-500'
      default: return 'bg-gray-500'
    }
  }

  const getLogIcon = (type: string) => {
    switch (type) {
      case 'owner': return 'user'
      case 'director': return 'arrow-right'
      case 'character': return 'message-circle'
      case 'system': return 'info'
      default: return 'circle'
    }
  }

  return (
    <div className="space-y-4 p-4 bg-white rounded-lg shadow">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Owner Control</h3>
        <div className="flex items-center gap-2">
          <span className={`w-3 h-3 rounded-full ${getStateColor(state)}`} />
          <span className="text-sm font-medium">{getStateLabel(state)}</span>
        </div>
      </div>

      {/* Control Buttons */}
      <div className="flex gap-2">
        <button
          className={`flex-1 px-4 py-2 rounded text-sm font-medium transition-colors
            ${isRunning
              ? 'bg-yellow-500 hover:bg-yellow-600 text-white'
              : 'bg-gray-200 text-gray-500 cursor-not-allowed'}`}
          onClick={handlePause}
          disabled={!isRunning || loading}
        >
          Pause
        </button>
        <button
          className={`flex-1 px-4 py-2 rounded text-sm font-medium transition-colors
            ${!isRunning
              ? 'bg-green-500 hover:bg-green-600 text-white'
              : 'bg-gray-200 text-gray-500 cursor-not-allowed'}`}
          onClick={handleResume}
          disabled={isRunning || loading}
        >
          Resume
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="p-2 bg-red-100 text-red-700 text-sm rounded">
          {error}
        </div>
      )}

      {/* Query Back Modal */}
      {queryBack && (
        <div className="p-4 bg-purple-50 rounded-lg border border-purple-200">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-2xl">
              {queryBack.from_character === 'yana' ? '\u{1F467}' : '\u{1F469}'}
            </span>
            <span className="font-medium">
              {queryBack.from_character === 'yana' ? '\u3084\u306A' : '\u3042\u3086'}
            </span>
          </div>
          <p className="text-gray-700 mb-3">{queryBack.question}</p>

          {queryBack.options && (
            <div className="flex flex-wrap gap-2 mb-3">
              {queryBack.options.map((opt, idx) => (
                <button
                  key={idx}
                  className="px-3 py-1 bg-white border border-purple-300 rounded text-sm hover:bg-purple-100"
                  onClick={() => handleAnswer(opt)}
                  disabled={loading}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            <input
              className="flex-1 px-3 py-2 border rounded text-sm"
              placeholder="Answer..."
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAnswer(message)}
            />
            <button
              className="px-4 py-2 bg-purple-500 text-white rounded text-sm hover:bg-purple-600 disabled:bg-gray-300"
              onClick={() => handleAnswer(message)}
              disabled={!message.trim() || loading}
            >
              Answer
            </button>
          </div>
        </div>
      )}

      {/* Intervention Input */}
      {(isPaused || isQueryBack) && !queryBack && (
        <div className="space-y-2">
          <label className="text-sm font-medium text-gray-700">
            Intervention Message
          </label>
          <textarea
            className="w-full px-3 py-2 border rounded text-sm resize-none"
            rows={3}
            placeholder="..."
            value={message}
            onChange={e => setMessage(e.target.value)}
          />
          <button
            className="w-full px-4 py-2 bg-blue-500 text-white rounded text-sm font-medium hover:bg-blue-600 disabled:bg-gray-300"
            onClick={handleSend}
            disabled={!message.trim() || loading}
          >
            {loading ? 'Sending...' : 'Send Instruction'}
          </button>
        </div>
      )}

      {/* Intervention Log */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-2">Intervention Log</h4>
        <div className="max-h-48 overflow-y-auto space-y-1 bg-gray-50 rounded p-2">
          {log.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-2">No logs yet</p>
          ) : (
            log.slice(-10).map((entry, idx) => (
              <div key={idx} className="flex items-start gap-2 text-xs">
                <span className="text-gray-400 whitespace-nowrap">
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
                <span className={`font-medium ${
                  entry.type === 'owner' ? 'text-blue-600' :
                  entry.type === 'director' ? 'text-green-600' :
                  entry.type === 'character' ? 'text-purple-600' :
                  'text-gray-600'
                }`}>
                  [{entry.type === 'owner' ? 'Owner' :
                    entry.type === 'director' ? 'Director' :
                    entry.type === 'character' ? entry.character :
                    'System'}]
                </span>
                <span className="text-gray-700">{entry.content}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
