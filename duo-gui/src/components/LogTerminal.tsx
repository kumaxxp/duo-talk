import { useEffect, useRef, useState } from 'react'

const API = (import.meta as any).env?.VITE_API_BASE || ''

export default function LogTerminal() {
    const [logs, setLogs] = useState<string[]>([])
    const bottomRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const fetchLogs = async () => {
            try {
                const res = await fetch(`${API}/api/system/log/tail?lines=8`)
                const data = await res.json()
                if (data.lines) {
                    setLogs(data.lines)
                }
            } catch (e) {
                // Silent fail
            }
        }

        fetchLogs()
        const id = setInterval(fetchLogs, 2000)
        return () => clearInterval(id)
    }, [])

    return (
        <div className="bg-[#1e1e1e] text-[#cccccc] font-mono text-[10px] p-2 rounded-md shadow-inner overflow-hidden flex flex-col h-32">
            <div className="flex-1 overflow-auto scrollbar-hide">
                {logs.map((line, i) => (
                    <div key={i} className="whitespace-pre-wrap leading-tight border-b border-[#333] pb-0.5 mb-0.5 last:border-0">
                        {line.trim()}
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>
        </div>
    )
}
