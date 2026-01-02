import React, { useEffect, useState, useCallback, useRef } from 'react'
import { Settings, Save, RotateCcw, Play, Loader2, Upload, X, Camera, Cpu, Layers, RefreshCw } from 'lucide-react'

interface VisionConfig {
  mode: string
  segmentation_model: string
  segmentation_confidence_threshold: number
  enable_ocr: boolean
  max_objects: number
  vlm_temperature: number
  vlm_max_tokens: number
  llm_temperature: number
  llm_max_tokens: number
  use_gpu: boolean
  output_language: string
  include_coordinates: boolean
  include_confidence: boolean
  custom_description_prompt: string
}

interface ModelInfo {
  id: string
  name: string
  vision: boolean
  description: string
  vram: string
  verified: boolean
  running: boolean
  selected: boolean
}

interface ModelStatus {
  status: string
  running_model: string | null
  running_model_name: string
  selected_model: string | null
  selected_model_name: string
  supports_vision: boolean
  needs_restart: boolean
}

const PROCESSING_MODES = [
  {
    id: 'single_vlm',
    name: 'VLMのみ',
    icon: Camera,
    description: '画像をVLMに直接入力して説明を生成',
    detail: 'シンプルで高速。VLM対応モデルが必要です。',
    requiresVision: true,
  },
  {
    id: 'segmentation_llm',
    name: 'セグメンテーション→LLM',
    icon: Layers,
    description: 'Florence-2で物体検出→LLMで説明生成',
    detail: '正確な位置情報。VLM非対応モデルでも動作。',
    requiresVision: false,
  },
  {
    id: 'vlm_segmentation',
    name: 'VLM+セグメンテーション',
    icon: Cpu,
    description: 'VLMとセグメンテーションを併用',
    detail: '最も詳細な解析。VLM対応モデルが必要。',
    requiresVision: true,
  },
]

const SEGMENTATION_MODELS = [
  { id: 'none', name: 'なし', description: '物体検出を使用しない' },
  { id: 'florence2-base', name: 'Florence-2 Base', description: '軽量・高速（約1GB）' },
  { id: 'florence2-large', name: 'Florence-2 Large', description: '高精度（約2GB）' },
]

const defaultConfig: VisionConfig = {
  mode: 'single_vlm',
  segmentation_model: 'none',
  segmentation_confidence_threshold: 0.5,
  enable_ocr: false,
  max_objects: 20,
  vlm_temperature: 0.3,
  vlm_max_tokens: 1024,
  llm_temperature: 0.5,
  llm_max_tokens: 512,
  use_gpu: true,
  output_language: 'ja',
  include_coordinates: true,
  include_confidence: true,
  custom_description_prompt: '',
}

export default function SettingsPanel({ apiBase }: { apiBase: string }) {
  const [config, setConfig] = useState<VisionConfig>(defaultConfig)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Model management state
  const [llmModels, setLlmModels] = useState<ModelInfo[]>([])
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null)

  // Restart state
  const [restarting, setRestarting] = useState(false)
  const [restartProgress, setRestartProgress] = useState(0)
  const [restartMessage, setRestartMessage] = useState('')

  // Test image state
  const [testImageFile, setTestImageFile] = useState<File | null>(null)
  const [testImagePreview, setTestImagePreview] = useState<string | null>(null)
  const [testImagePath, setTestImagePath] = useState<string>('')
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Load initial data
  useEffect(() => {
    const loadData = async () => {
      try {
        const [configRes, modelsRes, statusRes] = await Promise.all([
          fetch(`${apiBase}/api/vision/config`),
          fetch(`${apiBase}/api/models`),
          fetch(`${apiBase}/api/models/status`),
        ])

        const configData = await configRes.json()
        const modelsData = await modelsRes.json()
        const statusData = await statusRes.json()

        if (configData.config) setConfig({ ...defaultConfig, ...configData.config })
        if (modelsData.models) setLlmModels(modelsData.models)
        setModelStatus(statusData)
      } catch (e) {
        setMessage({ type: 'error', text: '設定の読み込みに失敗しました' })
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [apiBase])

  // Poll model status
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${apiBase}/api/models/status`)
        const data = await res.json()
        setModelStatus(data)
      } catch {
        // Ignore errors
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [apiBase])

  // Save configuration
  const handleSave = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const res = await fetch(`${apiBase}/api/vision/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setMessage({ type: 'success', text: '設定を保存しました' })
      } else {
        setMessage({ type: 'error', text: data.error || '保存に失敗しました' })
      }
    } catch {
      setMessage({ type: 'error', text: '保存に失敗しました' })
    } finally {
      setSaving(false)
    }
  }

  // Handle model selection (saves to config, requires restart)
  const handleModelSelect = async (modelId: string) => {
    try {
      const res = await fetch(`${apiBase}/api/models/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: modelId }),
      })
      const data = await res.json()
      if (data.status === 'saved') {
        setMessage({ type: 'success', text: data.message })
        // Refresh model list to update selected state
        const modelsRes = await fetch(`${apiBase}/api/models`)
        const modelsData = await modelsRes.json()
        if (modelsData.models) setLlmModels(modelsData.models)
        // Refresh status
        const statusRes = await fetch(`${apiBase}/api/models/status`)
        const statusData = await statusRes.json()
        setModelStatus(statusData)
      } else if (data.status === 'no_change') {
        setMessage({ type: 'success', text: data.message })
      } else {
        setMessage({ type: 'error', text: data.message || 'エラーが発生しました' })
      }
    } catch (e) {
      console.error('Model select error:', e)
      setMessage({ type: 'error', text: 'モデル選択に失敗しました' })
    }
  }

  // Handle vLLM restart
  const handleRestart = async () => {
    if (restarting) return

    setRestarting(true)
    setRestartProgress(0)
    setRestartMessage('再起動を開始...')
    setMessage(null)

    try {
      const response = await fetch(`${apiBase}/api/models/restart`, {
        method: 'POST',
      })

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('Response body is not readable')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              setRestartProgress(data.progress || 0)
              setRestartMessage(data.message || '')

              if (data.status === 'ready') {
                setMessage({ type: 'success', text: data.message })
                // Refresh model status
                const statusRes = await fetch(`${apiBase}/api/models/status`)
                const statusData = await statusRes.json()
                setModelStatus(statusData)
                // Refresh model list
                const modelsRes = await fetch(`${apiBase}/api/models`)
                const modelsData = await modelsRes.json()
                if (modelsData.models) setLlmModels(modelsData.models)
              } else if (data.status === 'error') {
                setMessage({ type: 'error', text: data.message })
              }
            } catch {
              // Ignore JSON parse errors
            }
          }
        }
      }
    } catch (e) {
      console.error('Restart error:', e)
      setMessage({ type: 'error', text: 'vLLMの再起動に失敗しました' })
    } finally {
      setRestarting(false)
      setRestartProgress(0)
      setRestartMessage('')
    }
  }

  // Handle image selection for test
  const handleImageSelect = useCallback((file: File) => {
    if (!file.type.startsWith('image/')) {
      setMessage({ type: 'error', text: '画像ファイルを選択してください' })
      return
    }
    setTestImageFile(file)
    setTestImagePath('')
    const reader = new FileReader()
    reader.onload = (e) => setTestImagePreview(e.target?.result as string)
    reader.readAsDataURL(file)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleImageSelect(file)
  }, [handleImageSelect])

  const clearTestImage = useCallback(() => {
    setTestImageFile(null)
    setTestImagePreview(null)
    setTestImagePath('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  // Test configuration
  const handleTest = async () => {
    let imagePath = testImagePath

    // Upload image if file is selected
    if (testImageFile) {
      const formData = new FormData()
      formData.append('image', testImageFile)
      try {
        const uploadRes = await fetch(`${apiBase}/api/image/upload`, {
          method: 'POST',
          body: formData,
        })
        const uploadData = await uploadRes.json()
        if (uploadData.error) {
          setMessage({ type: 'error', text: `画像アップロードエラー: ${uploadData.error}` })
          return
        }
        imagePath = uploadData.path
      } catch {
        setMessage({ type: 'error', text: '画像アップロードに失敗しました' })
        return
      }
    }

    if (!imagePath) {
      setMessage({ type: 'error', text: '画像を選択またはパスを入力してください' })
      return
    }

    setTesting(true)
    setTestResult(null)
    setMessage(null)
    try {
      const res = await fetch(`${apiBase}/api/vision/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_path: imagePath, config }),
      })
      const data = await res.json()
      if (data.result) {
        setTestResult(data.result)
        const timeMs = (data.result.processing_time_ms as number)?.toFixed(0) || '?'
        setMessage({ type: 'success', text: `解析完了（${timeMs}ms）` })
      } else {
        setMessage({ type: 'error', text: data.error || 'テストに失敗しました' })
      }
    } catch {
      setMessage({ type: 'error', text: 'テストリクエストに失敗しました' })
    } finally {
      setTesting(false)
    }
  }

  // Update config field
  const updateConfig = <K extends keyof VisionConfig>(key: K, value: VisionConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

  // Check if current model supports vision
  const currentModelSupportsVision = modelStatus?.supports_vision ?? false
  const currentMode = PROCESSING_MODES.find(m => m.id === config.mode)
  const modeRequiresVision = currentMode?.requiresVision ?? false
  const usesSegmentation = config.mode === 'vlm_segmentation' || config.mode === 'segmentation_llm'

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        <span className="ml-2 text-slate-500">設定を読み込み中...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-slate-600" />
          <h2 className="text-lg font-semibold">Vision設定</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setConfig(defaultConfig)}
            className="px-3 py-1.5 text-sm border rounded hover:bg-slate-50 flex items-center gap-1"
          >
            <RotateCcw className="w-4 h-4" /> リセット
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 text-sm bg-slate-900 text-white rounded hover:bg-slate-800 flex items-center gap-1 disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存
          </button>
        </div>
      </div>

      {/* Message */}
      {message && (
        <div
          className={`p-3 rounded text-sm ${
            message.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
          }`}
        >
          {message.text}
        </div>
      )}

      {/* 1. Processing Mode Selection */}
      <div className="p-4 bg-white border rounded-lg">
        <h3 className="font-medium mb-3">処理モード</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {PROCESSING_MODES.map(mode => {
            const Icon = mode.icon
            const isSelected = config.mode === mode.id
            const isDisabled = mode.requiresVision && !currentModelSupportsVision
            return (
              <button
                key={mode.id}
                onClick={() => !isDisabled && updateConfig('mode', mode.id)}
                disabled={isDisabled}
                className={`p-4 rounded-lg border-2 text-left transition-all
                  ${isSelected ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'}
                  ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Icon className={`w-5 h-5 ${isSelected ? 'text-blue-600' : 'text-gray-500'}`} />
                  <span className={`font-medium ${isSelected ? 'text-blue-700' : ''}`}>{mode.name}</span>
                </div>
                <p className="text-sm text-gray-600">{mode.description}</p>
                <p className="text-xs text-gray-400 mt-1">{mode.detail}</p>
                {isDisabled && (
                  <p className="text-xs text-red-500 mt-2">※ VLM対応モデルに切り替えてください</p>
                )}
              </button>
            )
          })}
        </div>

        {/* Mode warning */}
        {modeRequiresVision && !currentModelSupportsVision && (
          <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded text-sm text-amber-700">
            現在のモデル（{modelStatus?.running_model_name}）はVLM非対応です。
            「VLM対応モデル」に切り替えるか、「セグメンテーション→LLM」モードを使用してください。
          </div>
        )}
      </div>

      {/* 2. Main Model (LLM/VLM) Selection */}
      <div className="p-4 bg-white border rounded-lg">
        <h3 className="font-medium mb-3">メインモデル（LLM/VLM）</h3>

        {/* Status */}
        <div className="flex items-center gap-2 mb-3 text-sm">
          <span
            className={`w-2 h-2 rounded-full ${
              modelStatus?.status === 'ready' ? 'bg-green-500' :
              modelStatus?.status === 'stopped' ? 'bg-gray-400' :
              'bg-red-500'
            }`}
          />
          <span className="text-gray-600">
            {modelStatus?.status === 'ready' ? '起動中' :
             modelStatus?.status === 'stopped' ? '停止' : 'エラー'}
          </span>
          {modelStatus?.running_model && (
            <span className="text-gray-500">
              - {modelStatus.running_model_name?.split('/')[1]}
            </span>
          )}
        </div>

        {/* Restart warning and button */}
        {(modelStatus?.needs_restart || restarting) && (
          <div className="mb-3 p-3 bg-amber-50 border border-amber-200 rounded text-sm">
            {restarting ? (
              <>
                <div className="flex items-center gap-2 font-medium text-amber-700 mb-2">
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  vLLMを再起動中...
                </div>
                <div className="text-amber-600 text-xs mb-2">
                  {restartMessage}
                </div>
                <div className="w-full bg-amber-200 rounded-full h-2">
                  <div
                    className="bg-amber-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${restartProgress}%` }}
                  />
                </div>
                <div className="text-amber-500 text-xs mt-1 text-right">
                  {restartProgress}%
                </div>
              </>
            ) : (
              <>
                <div className="font-medium text-amber-700 mb-1">
                  再起動が必要です
                </div>
                <div className="text-amber-600 text-xs mb-2">
                  選択: {modelStatus?.selected_model_name?.split('/')[1]} /
                  現在: {modelStatus?.running_model_name?.split('/')[1]}
                </div>
                <button
                  onClick={handleRestart}
                  className="w-full px-3 py-2 bg-amber-600 text-white rounded hover:bg-amber-700 flex items-center justify-center gap-2 text-sm font-medium"
                >
                  <RefreshCw className="w-4 h-4" />
                  vLLMを再起動
                </button>
                <div className="text-amber-500 text-xs mt-2">
                  再起動には1〜3分かかります
                </div>
              </>
            )}
          </div>
        )}

        {/* Model selection */}
        <div className="space-y-2">
          {llmModels.map(m => (
            <label
              key={m.id}
              className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors
                ${m.running ? 'bg-green-50 border-2 border-green-300' :
                  m.selected ? 'bg-amber-50 border-2 border-amber-300' :
                  'bg-gray-50 border-2 border-transparent hover:bg-gray-100'}`}
            >
              <input
                type="radio"
                name="main-model"
                value={m.id}
                checked={m.selected}
                onChange={() => handleModelSelect(m.id)}
                className="mt-1"
              />
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium">{m.name.split('/')[1]}</span>
                  {m.vision ? (
                    <span className="px-2 py-0.5 bg-purple-100 text-purple-700 text-xs rounded">VLM</span>
                  ) : (
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">Text</span>
                  )}
                  <span className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded font-mono">{m.vram}</span>
                  {m.verified ? (
                    <span className="text-green-600 text-xs">✓</span>
                  ) : (
                    <span className="text-amber-500 text-xs">⚠️要確認</span>
                  )}
                  {m.running && (
                    <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded">起動中</span>
                  )}
                  {m.selected && !m.running && (
                    <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs rounded">次回起動</span>
                  )}
                </div>
                <div className="text-sm text-gray-500 mt-1">{m.description}</div>
              </div>
            </label>
          ))}
        </div>

        {modelStatus?.status === 'stopped' && (
          <div className="mt-3 p-3 bg-gray-50 border border-gray-200 rounded text-sm text-gray-700">
            vLLMサーバーが停止しています。ターミナルで起動してください。
          </div>
        )}
      </div>

      {/* 3. Segmentation Model Selection */}
      <div className={`p-4 bg-white border rounded-lg ${!usesSegmentation ? 'opacity-50' : ''}`}>
        <h3 className="font-medium mb-3">
          セグメンテーションモデル
          {!usesSegmentation && <span className="text-xs text-gray-500 ml-2">（現在のモードでは使用しません）</span>}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {SEGMENTATION_MODELS.map(seg => (
            <button
              key={seg.id}
              onClick={() => usesSegmentation && updateConfig('segmentation_model', seg.id)}
              disabled={!usesSegmentation}
              className={`p-3 rounded-lg border-2 text-left transition-all
                ${config.segmentation_model === seg.id ? 'border-green-500 bg-green-50' : 'border-gray-200'}
                ${!usesSegmentation ? 'cursor-not-allowed' : 'cursor-pointer hover:border-gray-300'}`}
            >
              <div className={`font-medium ${config.segmentation_model === seg.id ? 'text-green-700' : ''}`}>
                {seg.name}
              </div>
              <p className="text-sm text-gray-500 mt-1">{seg.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* 4. Parameters */}
      <div className="p-4 bg-white border rounded-lg">
        <h3 className="font-medium mb-4">パラメータ</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Temperature */}
          <div>
            <label className="text-sm text-gray-600 block mb-2">
              Temperature: <span className="font-mono">{config.vlm_temperature}</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={config.vlm_temperature}
              onChange={e => updateConfig('vlm_temperature', parseFloat(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>正確（0.0）</span>
              <span>創造的（1.0）</span>
            </div>
          </div>

          {/* Max Tokens */}
          <div>
            <label className="text-sm text-gray-600 block mb-2">最大トークン数</label>
            <input
              type="number"
              value={config.vlm_max_tokens}
              onChange={e => updateConfig('vlm_max_tokens', parseInt(e.target.value) || 512)}
              className="w-full px-3 py-2 border rounded"
            />
          </div>

          {/* Max Objects */}
          <div>
            <label className="text-sm text-gray-600 block mb-2">最大検出オブジェクト数</label>
            <input
              type="number"
              value={config.max_objects}
              onChange={e => updateConfig('max_objects', parseInt(e.target.value) || 20)}
              className="w-full px-3 py-2 border rounded"
              disabled={!usesSegmentation}
            />
          </div>

          {/* Options */}
          <div className="space-y-2">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={config.use_gpu}
                onChange={e => updateConfig('use_gpu', e.target.checked)}
              />
              <span className="text-sm">GPUを使用</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={config.include_coordinates}
                onChange={e => updateConfig('include_coordinates', e.target.checked)}
              />
              <span className="text-sm">座標情報を含める</span>
            </label>
          </div>
        </div>
      </div>

      {/* 5. Test Area */}
      <div className="p-4 bg-white border rounded-lg">
        <h3 className="font-medium mb-4">テスト</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Image drop zone */}
          <div
            className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer
              ${dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}
              ${testImagePreview ? 'border-green-500 bg-green-50' : ''}`}
            onDrop={handleDrop}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={e => { e.preventDefault(); setDragOver(false) }}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={e => e.target.files?.[0] && handleImageSelect(e.target.files[0])}
            />
            {testImagePreview ? (
              <div className="relative inline-block">
                <img src={testImagePreview} alt="テスト画像" className="max-h-40 mx-auto rounded" />
                <button
                  className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full w-6 h-6 flex items-center justify-center hover:bg-red-600"
                  onClick={(e) => { e.stopPropagation(); clearTestImage() }}
                >
                  <X className="w-4 h-4" />
                </button>
                <p className="text-xs text-green-600 mt-2">{testImageFile?.name}</p>
              </div>
            ) : (
              <div className="text-gray-500">
                <Upload className="w-8 h-8 mx-auto mb-2 text-gray-400" />
                <p className="text-sm">画像をドラッグ&ドロップ</p>
                <p className="text-xs text-gray-400">またはクリックして選択</p>
              </div>
            )}
          </div>

          {/* Path input and test button */}
          <div className="space-y-3">
            <div>
              <label className="text-sm text-gray-600 block mb-1">または画像パスを入力</label>
              <input
                type="text"
                placeholder="/path/to/image.jpg"
                value={testImagePath}
                onChange={e => { setTestImagePath(e.target.value); setTestImageFile(null); setTestImagePreview(null) }}
                className="w-full px-3 py-2 border rounded text-sm"
              />
            </div>

            <button
              onClick={handleTest}
              disabled={testing || (!testImageFile && !testImagePath)}
              className="w-full px-4 py-3 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {testing ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  解析中...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  テスト実行
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* 6. Test Results */}
      {testResult && (
        <div className="p-4 bg-white border rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium">解析結果</h3>
            <span className="text-sm text-gray-500">
              モード: {(testResult.mode_used as string) || '?'} |
              処理時間: {((testResult.processing_time_ms as number) || 0).toFixed(0)}ms
            </span>
          </div>

          {(testResult.status as string) === 'success' ? (
            <div className="space-y-4">
              {/* Visual Info */}
              {testResult.visual_info && (
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2">映像情報</h4>
                  <div className="bg-gray-50 rounded-lg p-3 space-y-2 text-sm">
                    {Object.entries(testResult.visual_info as Record<string, string>).map(([key, value]) => (
                      value && (
                        <div key={key}>
                          <span className="text-gray-500">{key}:</span>
                          <span className="ml-2 text-gray-800">{value}</span>
                        </div>
                      )
                    ))}
                  </div>
                </div>
              )}

              {/* Detected Objects */}
              {(testResult.detected_objects as Array<{label: string; position: string; size: string}>)?.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2">
                    検出オブジェクト（{(testResult.detected_objects as Array<unknown>).length}件）
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {(testResult.detected_objects as Array<{label: string; position: string; size: string}>).map((obj, i) => (
                      <span key={i} className="px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-sm">
                        {obj.label}
                        <span className="text-blue-400 ml-1">({obj.position}, {obj.size})</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Raw Text */}
              {testResult.raw_text && (
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2">生テキスト</h4>
                  <pre className="bg-gray-50 rounded-lg p-3 text-xs overflow-auto max-h-60 whitespace-pre-wrap">
                    {testResult.raw_text as string}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <div className="text-red-600 text-sm p-3 bg-red-50 rounded">
              エラー: {testResult.error as string}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
