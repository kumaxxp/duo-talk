import React, { useEffect, useState, useCallback } from 'react'
import {
  Server, Cloud, Container, Play, Square, RefreshCw,
  CheckCircle, XCircle, Loader2, Copy, Terminal,
  Zap, Database
} from 'lucide-react'

// === Types ===
interface BackendHealth {
  available: boolean
  running_model: string | null
  error: string | null
  container_id?: string | null
}

interface FlorenceHealth {
  available: boolean
  state: string
  container_id: string | null
  gpu_memory_gb: number | null
  error?: string
}

interface ProviderStatus {
  current_backend: string | null
  current_model: string | null
  ollama: BackendHealth
  vllm: BackendHealth
  florence2?: FlorenceHealth
  defaults: {
    backend: string
    model: string
    fallback_backend: string
    fallback_model: string
  }
}

interface ModelInfo {
  id: string
  name: string
  supports_vlm: boolean
  vram_gb: number
  description: string
}

interface BackendInfo {
  id: string
  base_url: string
  is_current: boolean
  models: ModelInfo[]
}

// === Component ===
import { Eye, Activity } from 'lucide-react'

export default function ProviderPanel({ apiBase }: { apiBase: string }) {
  // State
  const [status, setStatus] = useState<ProviderStatus | null>(null)
  const [backends, setBackends] = useState<BackendInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [dockerAction, setDockerAction] = useState<'starting' | 'stopping' | 'florence_start' | 'florence_stop' | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null)
  const [dockerCommand, setDockerCommand] = useState<string | null>(null)
  const [selectedVllmModel, setSelectedVllmModel] = useState<string>('gemma3-12b-int8')

  // ... (fetchStatus etc same) ...

  // Fetch status
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/status`)
      const data = await res.json()
      setStatus(data)
    } catch (err) {
      console.error('Failed to fetch provider status:', err)
    }
  }, [apiBase])

  // ... (fetchBackends same) ...
  const fetchBackends = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/backends`)
      const data = await res.json()
      if (Array.isArray(data.backends)) {
        setBackends(data.backends)
      }
    } catch (err) {
      console.error('Failed to fetch backends:', err)
    }
  }, [apiBase])

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      await Promise.all([fetchStatus(), fetchBackends()])
      setLoading(false)
    }
    loadData()
  }, [fetchStatus, fetchBackends])

  // Polling
  useEffect(() => {
    const interval = setInterval(fetchStatus, 5000)
    return () => clearInterval(interval)
  }, [fetchStatus])

  // ... (handleSwitchBackend same) ...
  const handleSwitchBackend = async (backend: string, modelId?: string) => {
    setSwitching(true)
    setMessage(null)
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend, model_id: modelId })
      })
      const data = await res.json()
      if (data.success) {
        setMessage({ type: 'success', text: `${backend} に切り替えました` })
        await fetchStatus()
      } else {
        setMessage({ type: 'error', text: data.error || '切り替えに失敗しました' })
        if (data.hint) {
          setDockerCommand(data.hint)
        }
      }
    } catch {
      setMessage({ type: 'error', text: '接続エラー' })
    } finally {
      setSwitching(false)
    }
  }

  // ... (vLLM docker handlers same) ...
  const handleStartDocker = async () => {
    setDockerAction('starting')
    setMessage({ type: 'info', text: 'vLLM Docker を起動中... (2-3分かかります)' })
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/docker/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: selectedVllmModel })
      })
      const data = await res.json()
      if (data.success) {
        setMessage({ type: 'success', text: 'vLLM Docker を起動しました' })
        await fetchStatus()
      } else {
        setMessage({ type: 'error', text: data.error || '起動に失敗しました' })
        if (data.command) {
          setDockerCommand(data.command)
        }
      }
    } catch {
      setMessage({ type: 'error', text: '起動リクエストに失敗しました' })
    } finally {
      setDockerAction(null)
    }
  }

  const handleStopDocker = async () => {
    setDockerAction('stopping')
    setMessage(null)
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/docker/stop`, {
        method: 'POST'
      })
      const data = await res.json()
      if (data.success) {
        setMessage({ type: 'success', text: 'vLLM Docker を停止しました' })
        await fetchStatus()
      } else {
        setMessage({ type: 'error', text: data.error || '停止に失敗しました' })
      }
    } catch {
      setMessage({ type: 'error', text: '停止リクエストに失敗しました' })
    } finally {
      setDockerAction(null)
    }
  }

  // Florence-2 Handlers
  const handleStartFlorence = async () => {
    setDockerAction('florence_start')
    setMessage({ type: 'info', text: 'Florence-2 を起動中...' })
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/florence/start`, { method: 'POST' })
      const data = await res.json()
      if (data.success) {
        setMessage({ type: 'success', text: 'Florence-2 を起動しました' })
        await fetchStatus()
      } else {
        setMessage({ type: 'error', text: data.error || '起動に失敗しました' })
      }
    } catch {
      setMessage({ type: 'error', text: 'エラーが発生しました' })
    } finally {
      setDockerAction(null)
    }
  }

  const handleStopFlorence = async () => {
    setDockerAction('florence_stop')
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/florence/stop`, { method: 'POST' })
      const data = await res.json()
      if (data.success) {
        setMessage({ type: 'success', text: 'Florence-2 を停止しました' })
        await fetchStatus()
      }
    } catch {
      // ignore
    } finally {
      setDockerAction(null)
    }
  }

  // ... (helpers same) ...
  const handleGetDockerCommand = async (modelId: string) => {
    try {
      const res = await fetch(`${apiBase}/api/v2/provider/docker/command/${modelId}`)
      const data = await res.json()
      if (data.command) {
        setDockerCommand(data.command)
      }
    } catch (err) {
      console.error('Failed to get docker command:', err)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setMessage({ type: 'info', text: 'コピーしました' })
    setTimeout(() => setMessage(null), 2000)
  }

  const StatusIcon = ({ available }: { available: boolean }) => {
    if (available) {
      return <CheckCircle className="w-5 h-5 text-green-500" />
    }
    return <XCircle className="w-5 h-5 text-red-400" />
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        <span className="ml-2 text-slate-500">読み込み中...</span>
      </div>
    )
  }

  const ollamaBackend = backends.find(b => b.id === 'ollama')
  const vllmBackend = backends.find(b => b.id === 'vllm')
  const ollamaModels = ollamaBackend?.models || []
  const vllmModels = vllmBackend?.models || []
  const isOllamaActive = status?.current_backend === 'ollama'
  const isVllmActive = status?.current_backend === 'vllm'

  // Determine display name for current backend
  const currentBackendName = isOllamaActive ? 'Ollama' : (isVllmActive ? 'vLLM (Docker)' : (status?.current_backend || '-'))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server className="w-5 h-5 text-slate-600" />
          <h2 className="text-lg font-semibold">LLM Provider</h2>
        </div>
        <button
          onClick={() => { fetchStatus(); fetchBackends() }}
          className="p-2 hover:bg-slate-100 rounded"
          title="更新"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Message */}
      {message && (
        <div className={`p-3 rounded text-sm flex items-center gap-2
          ${message.type === 'success' ? 'bg-emerald-50 text-emerald-700' : ''}
          ${message.type === 'error' ? 'bg-red-50 text-red-700' : ''}
          ${message.type === 'info' ? 'bg-blue-50 text-blue-700' : ''}`}
        >
          {message.type === 'info' && <Loader2 className="w-4 h-4 animate-spin" />}
          {message.text}
        </div>
      )}

      {/* Current Status */}
      <div className="p-4 bg-gradient-to-r from-slate-800 to-slate-700 rounded-lg text-white">
        <div className="text-sm text-slate-300 mb-1">現在のバックエンド</div>
        <div className="flex items-center gap-3">
          <span className="text-2xl font-bold capitalize">{currentBackendName}</span>
          <span className="px-2 py-1 bg-slate-600 rounded text-sm">{status?.current_model || '-'}</span>
        </div>
      </div>

      {/* Backend Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* Ollama Card */}
        <div className={`p-4 bg-white border-2 rounded-lg transition-all
          ${isOllamaActive ? 'border-green-500 shadow-lg shadow-green-100' : 'border-slate-200'}`}
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Cloud className="w-5 h-5 text-orange-500" />
              <span className="font-semibold">Ollama</span>
              {isOllamaActive && (
                <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">使用中</span>
              )}
            </div>
            <StatusIcon available={status?.ollama?.available || false} />
          </div>

          <div className="space-y-2 mb-4">
            <div className="flex items-center gap-2 text-sm">
              <span className={`w-2 h-2 rounded-full ${status?.ollama?.available ? 'bg-green-500' : 'bg-red-400'}`} />
              <span className="text-slate-600">
                {status?.ollama?.available ? '起動中' : '停止'}
              </span>
            </div>
            {status?.ollama?.running_model && (
              <div className="text-sm text-slate-500">
                モデル: <span className="font-mono">{status.ollama.running_model}</span>
              </div>
            )}
            {status?.ollama?.error && (
              <div className="text-xs text-red-500 truncate" title={status.ollama.error}>
                {status.ollama.error.slice(0, 50)}...
              </div>
            )}
          </div>

          {/* Ollama Models List */}
          <div className="space-y-2 mb-4 max-h-40 overflow-y-auto">
            {ollamaModels.map((model) => (
              <button
                key={model.id}
                onClick={() => handleSwitchBackend('ollama', model.id)}
                disabled={switching || !status?.ollama?.available}
                className={`w-full p-2 text-left rounded text-sm transition-colors
                  ${status?.current_model === model.name && isOllamaActive
                    ? 'bg-green-50 border border-green-300'
                    : 'bg-slate-50 hover:bg-slate-100 border border-transparent'}
                  disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{model.name}</span>
                  <div className="flex gap-1">
                    {model.supports_vlm && (
                      <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 text-xs rounded">VLM</span>
                    )}
                    <span className="px-1.5 py-0.5 bg-slate-200 text-slate-600 text-xs rounded">
                      {model.vram_gb}GB
                    </span>
                  </div>
                </div>
              </button>
            ))}
          </div>

          {!isOllamaActive && status?.ollama?.available && (
            <button
              onClick={() => handleSwitchBackend('ollama')}
              disabled={switching}
              className="w-full py-2 bg-orange-500 text-white rounded hover:bg-orange-600 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {switching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              Ollamaに切り替え
            </button>
          )}
        </div>

        {/* vLLM Card */}
        <div className={`p-4 bg-white border-2 rounded-lg transition-all
          ${isVllmActive ? 'border-green-500 shadow-lg shadow-green-100' : 'border-slate-200'}`}
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Container className="w-5 h-5 text-blue-500" />
              <span className="font-semibold">vLLM (Docker)</span>
              {isVllmActive && (
                <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">使用中</span>
              )}
            </div>
            <StatusIcon available={status?.vllm?.available || false} />
          </div>

          <div className="space-y-2 mb-4">
            <div className="flex items-center gap-2 text-sm">
              <span className={`w-2 h-2 rounded-full ${status?.vllm?.available ? 'bg-green-500' : 'bg-red-400'}`} />
              <span className="text-slate-600">
                {status?.vllm?.available ? '起動中' : '停止'}
              </span>
              {status?.vllm?.container_id && (
                <span className="text-xs text-slate-400 font-mono">
                  ({status.vllm.container_id.slice(0, 12)})
                </span>
              )}
            </div>
            {status?.vllm?.running_model && (
              <div className="text-sm text-slate-500">
                モデル: <span className="font-mono">{status.vllm.running_model}</span>
              </div>
            )}
          </div>

          <div className="mb-4">
            <label className="text-sm text-slate-600 mb-1 block">モデル選択</label>
            <select
              value={selectedVllmModel}
              onChange={(e) => {
                setSelectedVllmModel(e.target.value)
                handleGetDockerCommand(e.target.value)
              }}
              className="w-full p-2 border rounded text-sm"
            >
              {vllmModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.id} ({model.vram_gb}GB)
                </option>
              ))}
            </select>
          </div>

          <div className="flex gap-2">
            {!status?.vllm?.available ? (
              <button
                onClick={handleStartDocker}
                disabled={dockerAction !== null}
                className="flex-1 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {dockerAction === 'starting' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Docker起動
              </button>
            ) : (
              <>
                <button
                  onClick={() => handleSwitchBackend('vllm', selectedVllmModel)}
                  disabled={switching || isVllmActive}
                  className="flex-1 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {switching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                  vLLMに切り替え
                </button>
                <button
                  onClick={handleStopDocker}
                  disabled={dockerAction !== null}
                  className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50 flex items-center justify-center"
                >
                  {dockerAction === 'stopping' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
                </button>
              </>
            )}
          </div>
        </div>

        {/* Florence-2 Card */}
        <div className="p-4 bg-white border-2 border-slate-200 rounded-lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Eye className="w-5 h-5 text-purple-500" />
              <span className="font-semibold">Florence-2 (Vision)</span>
            </div>
            <StatusIcon available={status?.florence2?.available || false} />
          </div>

          <div className="space-y-2 mb-4">
            <div className="flex items-center gap-2 text-sm">
              <span className={`w-2 h-2 rounded-full ${status?.florence2?.available ? 'bg-green-500' : 'bg-red-400'}`} />
              <span className="text-slate-600">
                {status?.florence2?.available ? '起動中' : '停止'}
              </span>
              {status?.florence2?.container_id && (
                <span className="text-xs text-slate-400 font-mono">
                  ({status.florence2.container_id.slice(0, 12)})
                </span>
              )}
            </div>
            {status?.florence2?.available && status.florence2.gpu_memory_gb && (
              <div className="text-sm text-slate-500">
                GPU使用量: {status.florence2.gpu_memory_gb} GB
              </div>
            )}
            {status?.florence2?.error && (
              <div className="text-xs text-red-500 truncate" title={status.florence2.error}>
                {status.florence2.error.slice(0, 50)}...
              </div>
            )}
          </div>

          <div className="mt-auto">
            {!status?.florence2?.available ? (
              <button
                onClick={handleStartFlorence}
                disabled={dockerAction !== null}
                className="w-full py-2 bg-purple-500 text-white rounded hover:bg-purple-600 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {dockerAction === 'florence_start' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                起動する
              </button>
            ) : (
              <button
                onClick={handleStopFlorence}
                disabled={dockerAction !== null}
                className="w-full py-2 bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {dockerAction === 'florence_stop' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
                停止する
              </button>
            )}
          </div>
        </div>

      </div>


      {/* Docker Command */}
      {dockerCommand && (
        <div className="p-4 bg-slate-900 rounded-lg">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 text-slate-300">
              <Terminal className="w-4 h-4" />
              <span className="text-sm">Docker起動コマンド</span>
            </div>
            <button
              onClick={() => copyToClipboard(dockerCommand)}
              className="p-1.5 hover:bg-slate-700 rounded text-slate-400 hover:text-white"
              title="コピー"
            >
              <Copy className="w-4 h-4" />
            </button>
          </div>
          <pre className="text-xs text-green-400 overflow-x-auto whitespace-pre-wrap font-mono">
            {dockerCommand}
          </pre>
        </div>
      )}

      {/* Defaults Info */}
      {status?.defaults && (
        <div className="p-4 bg-slate-50 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <Database className="w-4 h-4 text-slate-500" />
            <span className="text-sm font-medium text-slate-600">デフォルト設定</span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-slate-500">優先バックエンド:</span>
              <span className="ml-2 font-mono">{status.defaults.backend}</span>
            </div>
            <div>
              <span className="text-slate-500">優先モデル:</span>
              <span className="ml-2 font-mono">{status.defaults.model}</span>
            </div>
            <div>
              <span className="text-slate-500">フォールバック:</span>
              <span className="ml-2 font-mono">{status.defaults.fallback_backend}</span>
            </div>
            <div>
              <span className="text-slate-500">フォールバックモデル:</span>
              <span className="ml-2 font-mono">{status.defaults.fallback_model}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
