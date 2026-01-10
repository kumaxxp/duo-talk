import { useState } from 'react'
import type { ThoughtEvent } from '../lib/types'

interface ThoughtLogItemProps {
    log: ThoughtEvent
}

export default function ThoughtLogItem({ log }: ThoughtLogItemProps) {
    const [isOpen, setIsOpen] = useState(false)

    // Status Colors
    const statusColor = (status: string) => {
        switch (status) {
            case 'retrying': return 'bg-orange-100 border-orange-200 text-orange-900'
            case 'reviewing': return 'bg-purple-100 border-purple-200 text-purple-900'
            case 'reviewed': return 'bg-green-100 border-green-200 text-green-900'
            case 'generating': return 'bg-blue-100 border-blue-200 text-blue-900'
            default: return 'bg-gray-100 border-gray-200 text-gray-700'
        }
    }

    const dotColor = (status: string) => {
        switch (status) {
            case 'retrying': return 'bg-orange-500'
            case 'reviewing': return 'bg-purple-500'
            case 'reviewed': return 'bg-green-500'
            case 'generating': return 'bg-blue-500'
            default: return 'bg-gray-500'
        }
    }

    // Summary Text
    const renderSummary = () => {
        if (log.status === 'generating') return `Generating (Attempt ${log.attempt})...`
        if (log.status === 'reviewed') return `Reviewed: ${log.result} ${log.reason ? `(${log.reason})` : ''}`
        if (log.status === 'retrying') return `Intervention/Retry: ${log.reason}`
        return log.status
    }

    const hasDetails = log.reason || log.suggestion || log.result

    return (
        <div className={`text-xs rounded border mb-1 transition-all ${statusColor(log.status)}`}>
            {/* Header / Summary */}
            <div
                className={`flex items-center gap-2 p-2 ${hasDetails ? 'cursor-pointer hover:bg-white/50' : ''}`}
                onClick={() => hasDetails && setIsOpen(!isOpen)}
            >
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColor(log.status)}`}></span>

                <div className="flex-1 min-w-0 font-medium">
                    <span className="uppercase opacity-75 mr-2 text-[10px]">{log.status}</span>
                    <span className="truncate">{renderSummary()}</span>
                </div>

                {/* Timestamp */}
                <span className="text-[10px] opacity-50 whitespace-nowrap">
                    {log.ts?.split('T')[1]?.split('.')[0]}
                </span>

                {/* Chevron for details */}
                {hasDetails && (
                    <span className="opacity-50">
                        {isOpen ? '▼' : '▶'}
                    </span>
                )}
            </div>

            {/* Expanded Details */}
            {isOpen && hasDetails && (
                <div className="px-3 pb-3 pt-1 border-t border-black/5 bg-white/30 space-y-2 animate-in fade-in slide-in-from-top-1 duration-200">
                    {log.status === 'retrying' && (
                        <div className="space-y-1">
                            <div className="font-bold text-orange-800">Reason: {log.reason}</div>
                            {log.suggestion && (
                                <div className="text-slate-600 bg-white p-2 rounded border border-slate-200">
                                    <div className="font-semibold text-[10px] uppercase text-slate-400">Suggestion / Guidance</div>
                                    <div className="whitespace-pre-wrap">{log.suggestion}</div>
                                </div>
                            )}
                        </div>
                    )}

                    {log.status === 'reviewed' && (
                        <div className="space-y-1">
                            <div className="flex items-center gap-2">
                                <span className="font-bold">Result:</span>
                                <span className={`px-1.5 py-0.5 rounded text-white text-[10px] uppercase ${log.result === 'PASS' ? 'bg-green-500' : 'bg-red-500'}`}>
                                    {log.result}
                                </span>
                            </div>
                            {log.reason && <div>Reason: {log.reason}</div>}
                        </div>
                    )}

                    {log.text && (
                        <div className="bg-slate-50 p-2 rounded border border-slate-100 italic text-slate-600 font-serif">
                            "{log.text}"
                        </div>
                    )}

                    {/* Any other details like attempt count */}
                    <div className="text-[10px] text-slate-400 mt-2 text-right">
                        Attempt #{log.attempt} • Speaker: {log.speaker}
                    </div>
                </div>
            )}
        </div>
    )
}
