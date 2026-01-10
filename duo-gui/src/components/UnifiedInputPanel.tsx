import { useState, useRef, useEffect, useCallback } from 'react'
import type { InterventionLogEntry, InterventionResult, InterventionState, InterventionStatus, QueryBack } from '../lib/types'

interface UnifiedInputPanelProps {
    apiBase: string
    runId?: string
    // Callback when a new run is started
    onRunStarted?: (runId: string) => void
    // Callback for pause state change
    onPauseChange?: (paused: boolean) => void
}

type InputMode = 'draft' | 'chat' | 'director'

export default function UnifiedInputPanel({ apiBase, runId, onRunStarted, onPauseChange }: UnifiedInputPanelProps) {
    const [mode, setMode] = useState<InputMode>('draft')
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    // Draft Mode State
    const [topic, setTopic] = useState('') // Separate topic state or use input? Let's use `input` as main text
    const [imageFile, setImageFile] = useState<File | null>(null)
    const [imagePreview, setImagePreview] = useState<string | null>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)
    // Optional settings for Draft
    const [maxTurns, setMaxTurns] = useState(8)
    const [showSettings, setShowSettings] = useState(false)

    // Director Mode State
    const [interventionStatus, setInterventionStatus] = useState<InterventionStatus | null>(null)
    const [queryBack, setQueryBack] = useState<QueryBack | null>(null)

    // Auto-switch mode based on run status?
    // If runId exists, default to 'director' or 'chat'?
    useEffect(() => {
        if (runId) {
            // If we just started a run, maybe switch to Director?
            if (mode === 'draft') setMode('director')
        }
    }, [runId])

    // --- Image Handling (Draft Mode) ---
    const handleImageSelect = useCallback((file: File) => {
        if (!file.type.startsWith('image/')) return
        setImageFile(file)
        const reader = new FileReader()
        reader.onload = (e) => setImagePreview(e.target?.result as string)
        reader.readAsDataURL(file)
    }, [])

    const clearImage = () => {
        setImageFile(null)
        setImagePreview(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
    }

    // --- Director Status Polling ---
    const fetchStatus = useCallback(async () => {
        if (!runId && mode !== 'director') return
        try {
            const res = await fetch(`${apiBase}/api/v2/intervention/status`)
            const data = await res.json()
            if (data.status === 'ok') {
                const status = data.intervention as InterventionStatus
                setInterventionStatus(status)
                // Check for Query Back
                if (status.state === 'query_back' && !queryBack) {
                    // We might need to fetch the specific log or just know we need to answer?
                    // Actually, `query_back` details usually come from the log or the result of the `send` command.
                    // But if we reload page, we need to fetch pending query.
                    // For now, let's rely on status. If status is query_back, we show indicator.
                }
            }
        } catch (e) { }
    }, [apiBase, runId, mode, queryBack])

    useEffect(() => {
        const id = setInterval(fetchStatus, 2000)
        return () => clearInterval(id)
    }, [fetchStatus])


    // --- Actions ---

    const handleStartRun = async () => {
        if (!input.trim() && !imageFile) return
        setLoading(true)
        setError(null)
        try {
            // Upload image if present
            let imagePath: string | undefined = undefined
            if (imageFile) {
                const formData = new FormData()
                formData.append('image', imageFile)
                const ur = await fetch(`${apiBase}/api/image/upload`, { method: 'POST', body: formData })
                const uj = await ur.json()
                if (uj.error) throw new Error(uj.error)
                imagePath = uj.path
            }

            const body = {
                text: input, // Topic
                maxTurns,
                imagePath
            }

            // Use Unified Stream API
            const response = await fetch(`${apiBase}/api/unified/run/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            })

            if (!response.ok) throw new Error("Failed to start")

            // Read stream briefly to get run_id
            const reader = response.body?.getReader()
            if (reader) {
                const decoder = new TextDecoder()
                let buffer = ''
                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break
                    buffer += decoder.decode(value, { stream: true })
                    if (buffer.includes('run_id')) {
                        // Lazy parse
                        const lines = buffer.split('\n')
                        for (const line of lines) {
                            if (line.includes('run_id')) {
                                try {
                                    const data = JSON.parse(line.replace('data: ', ''))
                                    if (data.run_id) {
                                        onRunStarted?.(data.run_id)
                                        setMode('director') // Switch to director
                                        setInput('')
                                        clearImage()
                                        return // Stop reading, let background handle?
                                    }
                                } catch { }
                            }
                        }
                    }
                }
            }
        } catch (e: any) {
            setError(e.message || "Error starting run")
        } finally {
            setLoading(false)
        }
    }

    const handleSendChat = async () => {
        if (!input.trim()) return
        setLoading(true)
        // Call Sync Chat API
        try {
            // This is a simplified call - ideally we want unified chat integration
            await fetch(`${apiBase}/api/unified/run/start-sync`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: input, maxTurns: 2 })
            })
            setInput('')
            // We rely on polling in App.tsx to pick up new events if they are logged?
            // Wait, start-sync output is immediate. It might not log to main timeline events if using legacy endpoint.
            // For now, just fire and forget (assuming logs will improve later).
        } catch (e) { }
        setLoading(false)
    }

    const handleSendDirector = async () => {
        if (!input.trim()) return
        setLoading(true)
        try {
            const res = await fetch(`${apiBase}/api/v2/intervention/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: input, type: 'instruction' })
            })
            setInput('')
            fetchStatus()
        } catch (e) { }
        setLoading(false)
    }

    const handlePauseToggle = async () => {
        if (!interventionStatus) return
        const isRunning = interventionStatus.state === 'running'
        const endpoint = isRunning ? 'pause' : 'resume'

        setLoading(true)
        try {
            await fetch(`${apiBase}/api/v2/intervention/${endpoint}`, { method: 'POST', body: JSON.stringify({ run_id: runId }) })
            onPauseChange?.(isRunning) // Optimistic update
            fetchStatus()
        } catch (e) { }
        setLoading(false)
    }

    // --- Render Helpers ---
    const isRunning = interventionStatus?.state === 'running'
    const statusColor = isRunning ? 'bg-green-500' : 'bg-yellow-500'

    return (
        <div className="flex flex-col bg-white border-t border-gray-200 shadow-lg p-4 gap-3 relative z-20">
            {/* Error Toast */}
            {error && <div className="absolute top-[-40px] left-0 right-0 bg-red-100 text-red-700 p-2 text-center text-xs">{error}</div>}

            {/* Top Bar: Mode Switcher & Status */}
            <div className="flex items-center justify-between">
                <div className="flex bg-slate-100 p-1 rounded-lg">
                    <button onClick={() => setMode('draft')} className={`px-4 py-1.5 rounded-md text-xs font-bold transition-all ${mode === 'draft' ? 'bg-white shadow text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}>
                        ✨ New Run
                    </button>
                    <button onClick={() => setMode('director')} disabled={!runId} className={`px-4 py-1.5 rounded-md text-xs font-bold transition-all ${mode === 'director' ? 'bg-white shadow text-blue-900' : 'text-slate-500 hover:text-slate-700 disabled:opacity-50'}`}>
                        🎬 Director
                    </button>
                    <button onClick={() => setMode('chat')} className={`px-4 py-1.5 rounded-md text-xs font-bold transition-all ${mode === 'chat' ? 'bg-white shadow text-green-900' : 'text-slate-500 hover:text-slate-700'}`}>
                        💬 Chat
                    </button>
                </div>

                {/* Director Controls (Pause/Resume) - Only in Director Mode */}
                {mode === 'director' && runId && (
                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-1.5 px-3 py-1 bg-slate-50 rounded-full border">
                            <div className={`w-2 h-2 rounded-full ${statusColor} animate-pulse`} />
                            <span className="text-xs font-medium text-slate-600 uppercase">{interventionStatus?.state || 'Connecting...'}</span>
                        </div>
                        <button
                            onClick={handlePauseToggle}
                            disabled={loading}
                            className="p-1.5 hover:bg-slate-100 rounded text-slate-600 transition-colors"
                            title={isRunning ? "Pause Run" : "Resume Run"}
                        >
                            {isRunning ?
                                <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg> :
                                <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                            }
                        </button>
                    </div>
                )}

                {/* Draft Settings Toggle */}
                {mode === 'draft' && (
                    <button onClick={() => setShowSettings(!showSettings)} className="text-xs text-slate-400 hover:text-slate-600 flex items-center gap-1">
                        ⚙️ Settings
                    </button>
                )}
            </div>

            {/* Settings Panel (Draft Only) */}
            {mode === 'draft' && showSettings && (
                <div className="flex gap-4 p-3 bg-slate-50 rounded text-xs border">
                    <label className="flex flex-col gap-1">
                        <span className="font-semibold text-slate-500">Max Turns</span>
                        <input type="number" value={maxTurns} onChange={e => setMaxTurns(parseInt(e.target.value))} className="border rounded px-2 py-1 w-20" />
                    </label>
                    {/* Add more settings here */}
                </div>
            )}

            {/* Image Preview Area */}
            {imagePreview && (
                <div className="relative inline-block w-24 h-24 bg-slate-100 rounded border overflow-hidden group">
                    <img src={imagePreview} alt="upload preview" className="w-full h-full object-cover" />
                    <button onClick={clearImage} className="absolute top-1 right-1 bg-black/50 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>
            )}

            {/* Main Input Area */}
            <div className="relative">
                <textarea
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault()
                            if (mode === 'draft') handleStartRun()
                            else if (mode === 'chat') handleSendChat()
                            else handleSendDirector()
                        }
                    }}
                    placeholder={
                        mode === 'draft' ? "Enter a topic to start narrated dialogue..." :
                            mode === 'chat' ? "Chat with the system..." :
                                "Enter instructions for the Director..."
                    }
                    disabled={loading}
                    className="w-full bg-slate-50 border border-gray-300 rounded-xl px-4 py-3 pr-24 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none resize-none text-sm min-h-[50px] max-h-[200px]"
                    rows={Math.min(5, Math.max(1, input.split('\n').length))}
                />

                <div className="absolute bottom-2.5 right-2.5 flex items-center gap-2">
                    {/* Image Upload Button (Draft Only) */}
                    {mode === 'draft' && (
                        <button onClick={() => fileInputRef.current?.click()} className="p-2 text-slate-400 hover:text-slate-600 rounded-full hover:bg-slate-200 transition-colors" title="Upload Image">
                            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
                        </button>
                    )}

                    {/* Send Button */}
                    <button
                        onClick={() => {
                            if (mode === 'draft') handleStartRun()
                            else if (mode === 'chat') handleSendChat()
                            else handleSendDirector()
                        }}
                        disabled={loading || (!input.trim() && !imageFile)}
                        className={`p-2 rounded-lg transition-all ${loading ? 'bg-gray-300 cursor-not-allowed' :
                                mode === 'draft' ? 'bg-slate-900 text-white hover:bg-slate-700' :
                                    mode === 'director' ? 'bg-blue-600 text-white hover:bg-blue-700' :
                                        'bg-green-600 text-white hover:bg-green-700'
                            }`}
                    >
                        {loading ? (
                            <svg className="w-5 h-5 animate-spin" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                        ) : (
                            <svg className="w-5 h-5 transform rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19V5m0 0l-7 7m7-7l7 7" /></svg>
                        )}
                    </button>
                </div>
            </div>
            <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={e => e.target.files?.[0] && handleImageSelect(e.target.files[0])} />
        </div>
    )
}
