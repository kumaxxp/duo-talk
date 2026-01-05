/**
 * UnifiedRunPanel - 統一パイプライン実行パネル
 *
 * 機能:
 * - テキスト入力
 * - 画像ファイル選択
 * - JetRacer接続設定
 * - 最大ターン数設定
 * - 実行/停止
 * - 対話タイムライン表示
 * - 割り込み入力
 */

import React, { useState, useCallback, useRef } from 'react'
import type {
  UnifiedDialogueTurn,
  UnifiedDialogueResult,
  UnifiedRunRequest,
} from '../lib/types'

const API = (import.meta as Record<string, Record<string, string>>).env?.VITE_API_BASE || ''

// スタイル定数
const CARD_STYLE = 'bg-white rounded-lg shadow p-4 mb-4'
const INPUT_STYLE =
  'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
const BUTTON_PRIMARY =
  'px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed'
const BUTTON_SECONDARY = 'px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300'
const BUTTON_DANGER = 'px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700'

interface UnifiedRunPanelProps {
  onRunComplete?: (result: UnifiedDialogueResult) => void
}

export default function UnifiedRunPanel({ onRunComplete }: UnifiedRunPanelProps) {
  // === 入力状態 ===
  const [topic, setTopic] = useState('')
  const [imagePath, setImagePath] = useState('')
  const [maxTurns, setMaxTurns] = useState(8)
  const [useJetRacer, setUseJetRacer] = useState(false)
  const [jetracerUrl, setJetracerUrl] = useState('http://192.168.1.65:8000')

  // === 実行状態 ===
  const [isRunning, setIsRunning] = useState(false)
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [dialogue, setDialogue] = useState<UnifiedDialogueTurn[]>([])
  const [error, setError] = useState<string | null>(null)

  // === 割り込み入力 ===
  const [interruptText, setInterruptText] = useState('')

  // === Refs ===
  const fileInputRef = useRef<HTMLInputElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)

  // === 実行開始（同期API） ===
  const handleStart = useCallback(async () => {
    if (!topic.trim() && !imagePath) {
      setError('トピックまたは画像を指定してください')
      return
    }

    setIsRunning(true)
    setDialogue([])
    setError(null)

    const request: UnifiedRunRequest = {
      text: topic.trim() || undefined,
      imagePath: imagePath || undefined,
      maxTurns,
    }

    if (useJetRacer) {
      request.jetracerUrl = jetracerUrl
      request.useJetRacerSensor = true
    }

    try {
      const response = await fetch(`${API}/api/unified/run/start-sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      })

      const result: UnifiedDialogueResult = await response.json()

      if (result.status === 'error') {
        setError(result.error || '実行エラー')
      } else {
        setDialogue(result.dialogue)
        setCurrentRunId(result.run_id)
        onRunComplete?.(result)
      }
    } catch (err) {
      setError(`通信エラー: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setIsRunning(false)
    }
  }, [topic, imagePath, maxTurns, useJetRacer, jetracerUrl, onRunComplete])

  // === SSE実行（リアルタイム） ===
  const handleStartSSE = useCallback(async () => {
    if (!topic.trim() && !imagePath) {
      setError('トピックまたは画像を指定してください')
      return
    }

    setIsRunning(true)
    setDialogue([])
    setError(null)

    const request: UnifiedRunRequest = {
      text: topic.trim() || undefined,
      imagePath: imagePath || undefined,
      maxTurns,
    }

    if (useJetRacer) {
      request.jetracerUrl = jetracerUrl
      request.useJetRacerSensor = true
    }

    try {
      const response = await fetch(`${API}/api/unified/run/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      })

      if (!response.body) {
        throw new Error('SSE not supported')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6)) as Record<string, unknown>

              if (data.type === 'speak' || data.speaker) {
                // 発話イベント
                const turn: UnifiedDialogueTurn = {
                  turn_number: (data.turn as number) ?? dialogue.length,
                  speaker: data.speaker as 'A' | 'B',
                  speaker_name:
                    (data.speaker_name as string) || (data.speaker === 'A' ? 'やな' : 'あゆ'),
                  text: data.text as string,
                  evaluation_status: data.evaluation_status as
                    | 'PASS'
                    | 'RETRY'
                    | 'MODIFY'
                    | undefined,
                  evaluation_action: data.evaluation_action as 'NOOP' | 'INTERVENE' | undefined,
                }
                setDialogue((prev) => [...prev, turn])

                // スクロール
                setTimeout(() => {
                  timelineRef.current?.scrollTo({
                    top: timelineRef.current.scrollHeight,
                    behavior: 'smooth',
                  })
                }, 100)
              }

              if (data.status === 'success' || data.type === 'complete') {
                setCurrentRunId(data.run_id as string)
              }

              if (data.error) {
                setError(data.error as string)
              }
            } catch {
              // JSON parse error, skip
            }
          }
        }
      }
    } catch (err) {
      setError(`通信エラー: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setIsRunning(false)
    }
  }, [topic, imagePath, maxTurns, useJetRacer, jetracerUrl, dialogue.length])

  // === 停止 ===
  const handleStop = useCallback(async () => {
    try {
      await fetch(`${API}/api/unified/run/stop`, { method: 'POST' })
    } catch (err) {
      console.error('Stop failed:', err)
    }
    setIsRunning(false)
  }, [])

  // === 割り込み送信 ===
  const handleInterrupt = useCallback(async () => {
    if (!interruptText.trim() || !isRunning) return

    try {
      await fetch(`${API}/api/unified/run/interrupt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: interruptText.trim() }),
      })
      setInterruptText('')
    } catch (err) {
      console.error('Interrupt failed:', err)
    }
  }, [interruptText, isRunning])

  // === 画像選択 ===
  const handleImageSelect = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      // ローカルパスを設定（実際のアップロードは別途実装）
      setImagePath(file.name)
    }
  }, [])

  // === クリア ===
  const handleClear = useCallback(() => {
    setDialogue([])
    setError(null)
    setCurrentRunId(null)
  }, [])

  return (
    <div className="p-4 space-y-4">
      {/* === 入力セクション === */}
      <div className={CARD_STYLE}>
        <h3 className="text-lg font-semibold mb-3">入力設定</h3>

        {/* トピック入力 */}
        <div className="mb-3">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            トピック / テキスト
          </label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="お正月の準備について話して"
            className={INPUT_STYLE}
            disabled={isRunning}
          />
        </div>

        {/* 画像選択 */}
        <div className="mb-3">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            画像ファイル（オプション）
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={imagePath}
              onChange={(e) => setImagePath(e.target.value)}
              placeholder="画像パスまたはURLを入力"
              className={`${INPUT_STYLE} flex-1`}
              disabled={isRunning}
            />
            <button onClick={handleImageSelect} className={BUTTON_SECONDARY} disabled={isRunning}>
              選択
            </button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            className="hidden"
          />
        </div>

        {/* JetRacer設定 */}
        <div className="mb-3">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={useJetRacer}
              onChange={(e) => setUseJetRacer(e.target.checked)}
              disabled={isRunning}
            />
            <span className="text-sm font-medium text-gray-700">JetRacer センサーを使用</span>
          </label>
          {useJetRacer && (
            <input
              type="text"
              value={jetracerUrl}
              onChange={(e) => setJetracerUrl(e.target.value)}
              placeholder="http://192.168.1.65:8000"
              className={`${INPUT_STYLE} mt-2`}
              disabled={isRunning}
            />
          )}
        </div>

        {/* ターン数 */}
        <div className="mb-3">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            最大ターン数: {maxTurns}
          </label>
          <input
            type="range"
            min={2}
            max={16}
            value={maxTurns}
            onChange={(e) => setMaxTurns(Number(e.target.value))}
            className="w-full"
            disabled={isRunning}
          />
        </div>

        {/* 実行ボタン */}
        <div className="flex gap-2">
          {!isRunning ? (
            <>
              <button onClick={handleStart} className={BUTTON_PRIMARY}>
                実行（同期）
              </button>
              <button onClick={handleStartSSE} className={BUTTON_SECONDARY}>
                実行（SSE）
              </button>
            </>
          ) : (
            <button onClick={handleStop} className={BUTTON_DANGER}>
              停止
            </button>
          )}
          <button onClick={handleClear} className={BUTTON_SECONDARY} disabled={isRunning}>
            クリア
          </button>
        </div>
      </div>

      {/* === エラー表示 === */}
      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      {/* === タイムライン === */}
      {dialogue.length > 0 && (
        <div className={CARD_STYLE}>
          <h3 className="text-lg font-semibold mb-3">
            対話タイムライン
            {currentRunId && (
              <span className="text-sm font-normal text-gray-500 ml-2">({currentRunId})</span>
            )}
          </h3>

          <div ref={timelineRef} className="space-y-3 max-h-96 overflow-y-auto">
            {dialogue.map((turn, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-lg ${
                  turn.speaker === 'A'
                    ? 'bg-pink-50 border-l-4 border-pink-400'
                    : 'bg-blue-50 border-l-4 border-blue-400'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold">{turn.speaker_name}</span>
                  <span className="text-xs text-gray-500">Turn {turn.turn_number}</span>
                  {turn.evaluation_status && (
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        turn.evaluation_status === 'PASS'
                          ? 'bg-green-200 text-green-800'
                          : turn.evaluation_status === 'RETRY'
                            ? 'bg-yellow-200 text-yellow-800'
                            : 'bg-red-200 text-red-800'
                      }`}
                    >
                      {turn.evaluation_status}
                      {turn.evaluation_action === 'INTERVENE' && ' -> INTERVENE'}
                    </span>
                  )}
                </div>
                <p className="text-gray-800">{turn.text}</p>
                {turn.rag_hints && turn.rag_hints.length > 0 && (
                  <div className="mt-2 text-xs text-gray-500">
                    RAG: {turn.rag_hints.slice(0, 2).join(', ')}
                    {turn.rag_hints.length > 2 && ` (+${turn.rag_hints.length - 2})`}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* === 割り込み入力 === */}
      {isRunning && (
        <div className={CARD_STYLE}>
          <h3 className="text-lg font-semibold mb-3">割り込み入力</h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={interruptText}
              onChange={(e) => setInterruptText(e.target.value)}
              placeholder="割り込みたい内容を入力..."
              className={`${INPUT_STYLE} flex-1`}
              onKeyPress={(e) => e.key === 'Enter' && handleInterrupt()}
            />
            <button onClick={handleInterrupt} className={BUTTON_PRIMARY}>
              送信
            </button>
          </div>
        </div>
      )}

      {/* === 実行中インジケータ === */}
      {isRunning && (
        <div className="flex items-center justify-center gap-2 text-blue-600">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
          <span>対話生成中...</span>
        </div>
      )}
    </div>
  )
}
