import React, { useState, useRef, useCallback, useEffect } from 'react'

interface ModelStatus {
  status: string
  running_model: string | null
  running_model_name: string
  selected_model: string | null
  supports_vision: boolean
  needs_restart: boolean
}

export default function ControlPanel({ apiBase, onStarted }:{ apiBase: string, onStarted: (rid?:string)=>void }){
  const [topic,setTopic]=useState('')
  const [maxTurns,setMax]=useState(8)
  const [seed,setSeed]=useState<number|''>('')
  const [noRag,setNoRag]=useState(false)
  const [imageFile, setImageFile] = useState<File|null>(null)
  const [imagePreview, setImagePreview] = useState<string|null>(null)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Model status (display only)
  const [modelInfo, setModelInfo] = useState<ModelStatus | null>(null)

  // Poll model status every 3 seconds
  useEffect(() => {
    const fetchStatus = () => {
      fetch(`${apiBase}/api/models/status`)
        .then(res => res.json())
        .then(data => setModelInfo(data))
        .catch(() => setModelInfo(null))
    }
    fetchStatus()
    const interval = setInterval(fetchStatus, 3000)
    return () => clearInterval(interval)
  }, [apiBase])

  const handleImageSelect = useCallback((file: File) => {
    if (!file.type.startsWith('image/')) {
      alert('画像ファイルを選択してください')
      return
    }
    setImageFile(file)
    const reader = new FileReader()
    reader.onload = (e) => setImagePreview(e.target?.result as string)
    reader.readAsDataURL(file)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleImageSelect(file)
  }, [handleImageSelect])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
  }, [])

  const clearImage = useCallback(() => {
    setImageFile(null)
    setImagePreview(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  const start = async ()=>{
    setUploading(true)
    try {
      let imagePath: string | undefined = undefined

      // 画像がある場合はアップロード
      if (imageFile) {
        const formData = new FormData()
        formData.append('image', imageFile)
        const uploadRes = await fetch(`${apiBase}/api/image/upload`, {
          method: 'POST',
          body: formData
        })
        const uploadJson = await uploadRes.json()
        if (uploadJson.error) {
          alert(`画像アップロードエラー: ${uploadJson.error}`)
          return
        }
        imagePath = uploadJson.path
      }

      const body = {
        topic,
        maxTurns,
        seed: (seed===''?undefined:seed),
        noRag,
        imagePath  // 画像パスを追加
      }
      const r = await fetch(`${apiBase}/api/run/start`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body)
      })
      const js = await r.json().catch(()=>({}))
      onStarted(js?.run_id)

      // 成功したら画像をクリア
      if (js?.run_id) {
        clearImage()
      }
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-3">
      {/* 画像アップロードエリア */}
      <div
        className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors cursor-pointer
          ${dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}
          ${imagePreview ? 'border-green-500 bg-green-50' : ''}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleImageSelect(e.target.files[0])}
        />
        {imagePreview ? (
          <div className="relative">
            <img src={imagePreview} alt="Preview" className="max-h-32 mx-auto rounded" />
            <button
              className="absolute top-0 right-0 bg-red-500 text-white rounded-full w-6 h-6 text-sm hover:bg-red-600"
              onClick={(e) => { e.stopPropagation(); clearImage() }}
            >×</button>
            <p className="text-xs text-green-600 mt-1">{imageFile?.name}</p>
          </div>
        ) : (
          <div className="text-gray-500">
            <p className="text-sm">📷 画像をドラッグ&ドロップ</p>
            <p className="text-xs">またはクリックして選択</p>
          </div>
        )}
      </div>

      {/* トピック入力 */}
      <input
        className="w-full px-3 py-2 border rounded"
        placeholder={imagePreview ? "トピック（オプション：画像から自動生成）" : "トピック（必須）"}
        value={topic}
        onChange={e=>setTopic(e.target.value)}
      />

      {/* オプション */}
      <div className="grid grid-cols-3 gap-2">
        <input
          className="px-3 py-2 border rounded"
          type="number"
          placeholder="maxTurns"
          value={maxTurns}
          onChange={e=>setMax(parseInt(e.target.value||'8',10))}
        />
        <input
          className="px-3 py-2 border rounded"
          type="number"
          placeholder="seed"
          value={seed}
          onChange={e=>setSeed(e.target.value===''?'':parseInt(e.target.value,10))}
        />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={noRag} onChange={e=>setNoRag(e.target.checked)} /> noRag
        </label>
      </div>

      {/* 現在のモデル表示 */}
      {modelInfo && (
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 rounded text-sm">
          <span
            className={`w-2 h-2 rounded-full flex-shrink-0 ${
              modelInfo.status === 'ready' ? 'bg-green-500' :
              modelInfo.status === 'stopped' ? 'bg-gray-400' :
              'bg-red-500'
            }`}
          />
          <span className="text-gray-600 truncate">
            {modelInfo.running_model_name && modelInfo.running_model_name !== 'N/A' ? (
              <>
                {modelInfo.running_model_name.split('/').pop()}
                {modelInfo.supports_vision && <span className="ml-1">📷</span>}
              </>
            ) : modelInfo.status === 'stopped' ? '停止中' : '接続中...'}
          </span>
          {modelInfo.needs_restart && (
            <span className="text-amber-500 text-xs">⚠️再起動必要</span>
          )}
        </div>
      )}

      {/* 開始ボタン */}
      <button
        className={`w-full px-3 py-2 text-white rounded transition-colors
          ${uploading ? 'bg-gray-400 cursor-not-allowed' : 'bg-slate-900 hover:bg-slate-800'}
          ${!topic && !imageFile ? 'opacity-50 cursor-not-allowed' : ''}`}
        onClick={start}
        disabled={uploading || (!topic && !imageFile)}
      >
        {uploading ? '処理中...' : (imageFile ? '🖼️ 画像から対話生成' : '▶️ Start')}
      </button>
    </div>
  )
}

