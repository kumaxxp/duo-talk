import React from 'react'
import { covRate } from '../hooks/useCov'
import { covColor, pct } from '../lib/format'
import type { Beat, DirectorEvent, RAGEvent, SpeakEvent } from '../lib/types'

// キャラクター情報
const CHARACTER_INFO = {
  A: { name: 'やな', fullName: '澄ヶ瀬やな (姉)', color: 'bg-rose-500', bgColor: 'bg-rose-50 border-rose-200', icon: '/icon/yana_face.png' },
  B: { name: 'あゆ', fullName: '澄ヶ瀬あゆ (妹)', color: 'bg-sky-500', bgColor: 'bg-sky-50 border-sky-200', icon: '/icon/ayu_face.png' },
}

export default function TurnCard({ sp, rag, beat, directorStatus, directorReason, directorGuidance, onSelect, onViewPrompts }: { sp: SpeakEvent, rag?: RAGEvent, beat?: Beat, directorStatus?: string, directorReason?: string, directorGuidance?: string, onSelect?: () => void, onViewPrompts?: (e: React.MouseEvent<HTMLButtonElement>) => void }) {
  const canon = rag?.canon?.preview || ''
  const lore = rag?.lore?.preview || ''
  const patt = rag?.pattern?.preview || ''
  const cCanon = covRate(canon, sp.text)
  const cLore = covRate(lore, sp.text)
  const cPatt = covRate(patt, sp.text)
  const cov = Math.max(cCanon, cLore, cPatt)
  const tip = `c=${cCanon.toFixed(2)} l=${cLore.toFixed(2)} p=${cPatt.toFixed(2)}`

  const charInfo = CHARACTER_INFO[sp.speaker as 'A' | 'B'] || CHARACTER_INFO.A

  function beatColor(b?: string) {
    if (!b) return 'bg-slate-200 text-slate-700'
    if (b === 'BANter' || b === 'Setup' || b.includes('Theme')) return 'bg-gray-200 text-gray-800'
    if (b === 'PIVOT' || b.includes('Midpoint')) return 'bg-blue-200 text-blue-800'
    if (b === 'PAYOFF' || b.includes('Finale') || b.includes('Aha')) return 'bg-purple-200 text-purple-800'
    if (b.includes('Fun&Games')) return 'bg-emerald-200 text-emerald-800'
    return 'bg-slate-200 text-slate-700'
  }

  function directorIcon(status?: string) {
    if (status === 'PASS') return '✓'
    if (status === 'RETRY') return '🔄'
    if (status === 'MODIFY') return '⚠️'
    return ''
  }

  return (
    <div className={`border rounded-lg p-3 transition-all hover:shadow-md cursor-pointer ${charInfo.bgColor}`} onClick={onSelect}>
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <span className="font-mono text-slate-500">#{sp.turn}</span>
          <span className={`px-2 py-1 rounded-full text-white text-xs font-bold ${charInfo.color}`}>
            {charInfo.name}
          </span>
          <span className={`px-2 py-0.5 rounded text-xs ${beatColor(beat)}`}>{beat || '-'}</span>
          {directorStatus && (
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${directorStatus === 'PASS' ? 'bg-green-100 text-green-700' :
                directorStatus === 'RETRY' ? 'bg-amber-100 text-amber-700' :
                  'bg-red-100 text-red-700'
              }`}>
              {directorIcon(directorStatus)} {directorStatus}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="text-xs px-2 py-1 border rounded hover:bg-white/50 transition-colors"
            onClick={(e) => { e.stopPropagation(); onViewPrompts?.(e) }}>詳細</button>
        </div>
      </div>

      {/* Main Content Layout: Left (Text+Info) | Right (Icon) */}
      <div className="mt-3 flex items-start gap-4">
        {/* Left Column: Text -> Director -> RAG */}
        <div className="flex-1 min-w-0 space-y-3">
          {/* Text Bubble */}
          <div className="p-3 bg-white/80 rounded-lg shadow-sm">
            <div className="whitespace-pre-wrap leading-relaxed text-gray-800">{sp.text}</div>
          </div>

          {/* Director Feedback */}
          {directorStatus && directorReason && (
            <div className={`p-2 rounded text-sm ${directorStatus === 'PASS' ? 'bg-green-50 border border-green-200' :
                directorStatus === 'RETRY' ? 'bg-amber-50 border border-amber-200' : 'bg-red-50 border border-red-200'
              }`}>
              <div className="font-medium text-xs mb-1">
                {directorStatus === 'PASS' ? '✓ Director判定:' :
                  directorStatus === 'RETRY' ? '🔄 再生成の理由:' : '⚠️ 問題点:'}
              </div>
              <div className="text-slate-600 text-xs">{directorReason}</div>
              {directorGuidance && (
                <div className="mt-1 pt-1 border-t border-green-200/50">
                  <span className="text-slate-500 text-xs">💡 次ターン: </span>
                  <span className="text-slate-600 text-xs">{directorGuidance.length > 80 ? directorGuidance.slice(0, 80) + '...' : directorGuidance}</span>
                </div>
              )}
            </div>
          )}

          {/* RAG Coverage */}
          <div className="flex items-center gap-2" title={tip}>
            <span className="text-xs text-slate-500 w-8">RAG</span>
            <div className="flex-1 bg-slate-200/50 rounded h-1.5">
              <div className={`h-1.5 rounded ${covColor(cov)}`} style={{ width: pct(cov) }} />
            </div>
            <span className="text-xs text-slate-500 w-8 text-right">{pct(cov)}</span>
          </div>
        </div>

        {/* Right Column: Icon */}
        <img
          src={charInfo.icon}
          alt={charInfo.name}
          className="w-[120px] h-[120px] lg:w-[160px] lg:h-[160px] rounded-lg object-cover flex-shrink-0 border-2 border-white shadow-lg"
        />
      </div>
    </div>
  )
}
