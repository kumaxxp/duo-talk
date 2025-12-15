import React, { useEffect, useState } from 'react'
import { Settings, Save, RotateCcw, Play, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'

interface VisionConfig {
  mode: string
  vlm_type: string
  vlm_custom_model: string
  segmentation_model: string
  segmentation_confidence_threshold: number
  enable_ocr: boolean
  enable_depth_estimation: boolean
  max_objects: number
  vlm_temperature: number
  vlm_max_tokens: number
  use_gpu: boolean
  batch_size: number
  output_language: string
  include_coordinates: boolean
  include_confidence: boolean
  custom_detection_prompt: string
  custom_description_prompt: string
}

interface Preset {
  name: string
  description: string
  config: VisionConfig
}

interface ModelOptions {
  vlm_types: { value: string; label: string }[]
  segmentation_models: { value: string; label: string }[]
  modes: { value: string; label: string }[]
}

const defaultConfig: VisionConfig = {
  mode: 'single_vlm',
  vlm_type: 'llava:7b',
  vlm_custom_model: '',
  segmentation_model: 'none',
  segmentation_confidence_threshold: 0.5,
  enable_ocr: false,
  enable_depth_estimation: false,
  max_objects: 20,
  vlm_temperature: 0.3,
  vlm_max_tokens: 1024,
  use_gpu: true,
  batch_size: 1,
  output_language: 'ja',
  include_coordinates: true,
  include_confidence: true,
  custom_detection_prompt: '',
  custom_description_prompt: '',
}

export default function SettingsPanel({ apiBase }: { apiBase: string }) {
  const [config, setConfig] = useState<VisionConfig>(defaultConfig)
  const [presets, setPresets] = useState<Preset[]>([])
  const [models, setModels] = useState<ModelOptions | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  const [testImagePath, setTestImagePath] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Load initial data
  useEffect(() => {
    const loadData = async () => {
      try {
        const [configRes, presetsRes, modelsRes] = await Promise.all([
          fetch(`${apiBase}/api/vision/config`),
          fetch(`${apiBase}/api/vision/presets`),
          fetch(`${apiBase}/api/vision/models`),
        ])

        const configData = await configRes.json()
        const presetsData = await presetsRes.json()
        const modelsData = await modelsRes.json()

        if (configData.config) setConfig(configData.config)
        if (presetsData.presets) setPresets(presetsData.presets)
        if (modelsData.models) setModels(modelsData.models)
      } catch (e) {
        setMessage({ type: 'error', text: 'Failed to load settings' })
      } finally {
        setLoading(false)
      }
    }
    loadData()
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
        setMessage({ type: 'success', text: 'Settings saved successfully' })
      } else {
        setMessage({ type: 'error', text: data.error || 'Failed to save' })
      }
    } catch (e) {
      setMessage({ type: 'error', text: 'Failed to save settings' })
    } finally {
      setSaving(false)
    }
  }

  // Apply preset
  const handleApplyPreset = async (presetName: string) => {
    setMessage(null)
    try {
      const res = await fetch(`${apiBase}/api/vision/presets/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset_name: presetName }),
      })
      const data = await res.json()
      if (data.config) {
        setConfig(data.config)
        setMessage({ type: 'success', text: `Preset "${presetName}" applied` })
      }
    } catch (e) {
      setMessage({ type: 'error', text: 'Failed to apply preset' })
    }
  }

  // Test configuration
  const handleTest = async () => {
    if (!testImagePath) {
      setMessage({ type: 'error', text: 'Please enter an image path' })
      return
    }
    setTesting(true)
    setTestResult(null)
    setMessage(null)
    try {
      const res = await fetch(`${apiBase}/api/vision/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_path: testImagePath, config }),
      })
      const data = await res.json()
      if (data.result) {
        setTestResult(data.result)
        setMessage({ type: 'success', text: `Test completed in ${data.result.processing_time_ms?.toFixed(0)}ms` })
      } else {
        setMessage({ type: 'error', text: data.error || 'Test failed' })
      }
    } catch (e) {
      setMessage({ type: 'error', text: 'Test request failed' })
    } finally {
      setTesting(false)
    }
  }

  // Update config field
  const updateConfig = <K extends keyof VisionConfig>(key: K, value: VisionConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        <span className="ml-2 text-slate-500">Loading settings...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-slate-600" />
          <h2 className="text-lg font-semibold">Vision Settings</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setConfig(defaultConfig)}
            className="px-3 py-1.5 text-sm border rounded hover:bg-slate-50 flex items-center gap-1"
          >
            <RotateCcw className="w-4 h-4" /> Reset
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 text-sm bg-slate-900 text-white rounded hover:bg-slate-800 flex items-center gap-1 disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save
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

      {/* Presets */}
      <div className="p-4 bg-slate-50 rounded-lg">
        <h3 className="font-medium mb-3">Quick Presets</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
          {presets.map(preset => (
            <button
              key={preset.name}
              onClick={() => handleApplyPreset(preset.name)}
              className="p-3 bg-white border rounded-lg hover:border-slate-400 text-left transition-colors"
            >
              <div className="font-medium text-sm">{preset.name}</div>
              <div className="text-xs text-slate-500 mt-1 line-clamp-2">{preset.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Main Settings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Mode Selection */}
        <div className="p-4 bg-white border rounded-lg">
          <h3 className="font-medium mb-3">Processing Mode</h3>
          <select
            value={config.mode}
            onChange={e => updateConfig('mode', e.target.value)}
            className="w-full px-3 py-2 border rounded"
          >
            {models?.modes.map(m => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-slate-500 mt-2">
            {config.mode === 'single_vlm' && 'Single VLM for both detection and description'}
            {config.mode === 'vlm_segmentation' && 'VLM + Segmentation model for detailed analysis'}
            {config.mode === 'segmentation_llm' && 'Segmentation first, then LLM for description'}
          </p>
        </div>

        {/* VLM Selection */}
        <div className="p-4 bg-white border rounded-lg">
          <h3 className="font-medium mb-3">VLM Model</h3>
          <select
            value={config.vlm_type}
            onChange={e => updateConfig('vlm_type', e.target.value)}
            className="w-full px-3 py-2 border rounded"
          >
            {models?.vlm_types.map(m => (
              <option key={m.value} value={m.value}>
                {m.label} ({m.value})
              </option>
            ))}
          </select>
          {config.vlm_type === 'custom' && (
            <input
              type="text"
              placeholder="Custom model name (e.g., my-vlm:latest)"
              value={config.vlm_custom_model}
              onChange={e => updateConfig('vlm_custom_model', e.target.value)}
              className="w-full px-3 py-2 border rounded mt-2"
            />
          )}
        </div>

        {/* Segmentation Model */}
        <div className="p-4 bg-white border rounded-lg">
          <h3 className="font-medium mb-3">Segmentation Model</h3>
          <select
            value={config.segmentation_model}
            onChange={e => updateConfig('segmentation_model', e.target.value)}
            className="w-full px-3 py-2 border rounded"
            disabled={config.mode === 'single_vlm'}
          >
            {models?.segmentation_models.map(m => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          {config.mode === 'single_vlm' && (
            <p className="text-xs text-slate-500 mt-2">Change mode to enable segmentation</p>
          )}
        </div>

        {/* VLM Parameters */}
        <div className="p-4 bg-white border rounded-lg">
          <h3 className="font-medium mb-3">VLM Parameters</h3>
          <div className="space-y-3">
            <div>
              <label className="text-sm text-slate-600">Temperature: {config.vlm_temperature}</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={config.vlm_temperature}
                onChange={e => updateConfig('vlm_temperature', parseFloat(e.target.value))}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-sm text-slate-600">Max Tokens</label>
              <input
                type="number"
                value={config.vlm_max_tokens}
                onChange={e => updateConfig('vlm_max_tokens', parseInt(e.target.value) || 1024)}
                className="w-full px-3 py-2 border rounded"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Advanced Settings */}
      <div className="border rounded-lg">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full p-4 flex items-center justify-between hover:bg-slate-50"
        >
          <span className="font-medium">Advanced Settings</span>
          {showAdvanced ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
        </button>
        {showAdvanced && (
          <div className="p-4 border-t space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.use_gpu}
                  onChange={e => updateConfig('use_gpu', e.target.checked)}
                />
                <span className="text-sm">Use GPU</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.enable_ocr}
                  onChange={e => updateConfig('enable_ocr', e.target.checked)}
                />
                <span className="text-sm">Enable OCR</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.include_coordinates}
                  onChange={e => updateConfig('include_coordinates', e.target.checked)}
                />
                <span className="text-sm">Include Coordinates</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.include_confidence}
                  onChange={e => updateConfig('include_confidence', e.target.checked)}
                />
                <span className="text-sm">Include Confidence</span>
              </label>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <label className="text-sm text-slate-600">Max Objects</label>
                <input
                  type="number"
                  value={config.max_objects}
                  onChange={e => updateConfig('max_objects', parseInt(e.target.value) || 20)}
                  className="w-full px-3 py-2 border rounded"
                />
              </div>
              <div>
                <label className="text-sm text-slate-600">Segmentation Threshold</label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.1"
                  value={config.segmentation_confidence_threshold}
                  onChange={e => updateConfig('segmentation_confidence_threshold', parseFloat(e.target.value) || 0.5)}
                  className="w-full px-3 py-2 border rounded"
                />
              </div>
              <div>
                <label className="text-sm text-slate-600">Output Language</label>
                <select
                  value={config.output_language}
                  onChange={e => updateConfig('output_language', e.target.value)}
                  className="w-full px-3 py-2 border rounded"
                >
                  <option value="ja">Japanese</option>
                  <option value="en">English</option>
                </select>
              </div>
            </div>

            <div>
              <label className="text-sm text-slate-600">Custom Description Prompt</label>
              <textarea
                value={config.custom_description_prompt}
                onChange={e => updateConfig('custom_description_prompt', e.target.value)}
                placeholder="Leave empty to use default prompt"
                className="w-full px-3 py-2 border rounded h-24 font-mono text-sm"
              />
            </div>
          </div>
        )}
      </div>

      {/* Test Section */}
      <div className="p-4 bg-white border rounded-lg">
        <h3 className="font-medium mb-3">Test Configuration</h3>
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Image path (e.g., /path/to/image.jpg)"
            value={testImagePath}
            onChange={e => setTestImagePath(e.target.value)}
            className="flex-1 px-3 py-2 border rounded"
          />
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-4 py-2 bg-emerald-600 text-white rounded hover:bg-emerald-700 flex items-center gap-2 disabled:opacity-50"
          >
            {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Test
          </button>
        </div>

        {testResult && (
          <div className="mt-4 p-4 bg-slate-50 rounded">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium">Test Result</span>
              <span className="text-sm text-slate-500">
                Mode: {testResult.mode_used} | Time: {testResult.processing_time_ms?.toFixed(0)}ms
              </span>
            </div>
            {testResult.status === 'success' ? (
              <div className="space-y-2 text-sm">
                {testResult.visual_info && (
                  <div>
                    <div className="font-medium text-slate-700">Visual Info:</div>
                    <pre className="mt-1 p-2 bg-white rounded text-xs overflow-auto max-h-40">
                      {JSON.stringify(testResult.visual_info, null, 2)}
                    </pre>
                  </div>
                )}
                {testResult.detected_objects?.length > 0 && (
                  <div>
                    <div className="font-medium text-slate-700">
                      Detected Objects ({testResult.detected_objects.length}):
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {testResult.detected_objects.map((obj: any, i: number) => (
                        <span key={i} className="px-2 py-1 bg-white rounded text-xs">
                          {obj.label} ({obj.position}, {obj.size})
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-red-600 text-sm">{testResult.error}</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
