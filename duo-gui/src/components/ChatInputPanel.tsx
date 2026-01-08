import React, { useState, useRef, useEffect } from 'react'

interface ChatMessage {
  speaker: 'user' | 'yana' | 'ayu'
  text: string
  time: string
}

interface ChatInputPanelProps {
  apiBase: string
  onSendComplete?: () => void
}

/**
 * ChatInputPanel - RUNSタブのチャット機能
 * 
 * テキスト入力からやな・あゆの応答を生成・表示するコンポーネント
 * API: POST /api/unified/run/start-sync
 */
export default function ChatInputPanel({ apiBase, onSendComplete }: ChatInputPanelProps) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // 自動スクロール to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async () => {
    if (!input.trim()) return

    setLoading(true)
    setError(null)

    try {
      // ユーザー入力をチャット履歴に追加
      const userMessage: ChatMessage = {
        speaker: 'user',
        text: input,
        time: new Date().toLocaleTimeString('ja-JP', {
          hour: '2-digit',
          minute: '2-digit'
        })
      }
      setMessages(prev => [...prev, userMessage])
      setInput('')

      // API 呼び出し（既存エンドポイント）
      const apiUrl = `${apiBase || 'http://localhost:5000'}/api/unified/run/start-sync`
      
      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          text: userMessage.text,
          maxTurns: 2
        })
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.error || `HTTP ${response.status}`)
      }

      const result = await response.json()

      // レスポンス時刻
      const responseTime = new Date().toLocaleTimeString('ja-JP', {
        hour: '2-digit',
        minute: '2-digit'
      })

      // dialogue 配列から Yana/Ayu の応答を抽出
      if (result.dialogue && Array.isArray(result.dialogue)) {
        const newMessages: ChatMessage[] = []
        
        for (const turn of result.dialogue) {
          const speaker: 'yana' | 'ayu' = turn.speaker === 'A' ? 'yana' : 'ayu'
          newMessages.push({
            speaker,
            text: turn.text,
            time: responseTime
          })
        }

        setMessages(prev => [...prev, ...newMessages])
      }

      // コールバック実行
      onSendComplete?.()

    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : '不明なエラー'
      setError(errorMessage)
      console.error('Chat error:', e)
    } finally {
      setLoading(false)
    }
  }

  // Enter キーで送信（Shift+Enter は改行）
  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !loading) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="space-y-3 h-full flex flex-col">
      {/* Header */}
      <div className="border-b pb-2">
        <h3 className="text-sm font-semibold">💬 Chat Mode</h3>
      </div>

      {/* Chat History */}
      <div className="flex-1 bg-slate-50 rounded-lg p-3 overflow-y-auto space-y-2">
        {messages.length === 0 ? (
          <p className="text-slate-400 text-xs text-center py-6">
            メッセージを入力して開始してください
          </p>
        ) : (
          messages.map((msg, idx) => {
            const bgColor =
              msg.speaker === 'user'
                ? 'bg-blue-100 text-blue-900'
                : msg.speaker === 'yana'
                  ? 'bg-green-100 text-green-900'
                  : 'bg-purple-100 text-purple-900'

            const nameLabel =
              msg.speaker === 'user' ? 'You' : msg.speaker === 'yana' ? 'Yana' : 'Ayu'

            return (
              <div key={idx} className={`p-2 rounded text-xs ${bgColor}`}>
                <div className="flex justify-between items-start">
                  <strong>{nameLabel}</strong>
                  <span className="text-xs opacity-70">{msg.time}</span>
                </div>
                <p className="mt-1 text-sm">{msg.text}</p>
              </div>
            )
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Error Message */}
      {error && (
        <div className="p-2 bg-red-100 text-red-700 rounded text-xs">
          <strong>❌ エラー:</strong> {error}
        </div>
      )}

      {/* Loading Status */}
      {loading && (
        <div className="p-2 bg-yellow-100 text-yellow-800 rounded text-xs">
          <strong>⏳ 応答を待機中...</strong> (処理時間: 2-5秒)
        </div>
      )}

      {/* Input Area */}
      <div className="space-y-2 border-t pt-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="メッセージを入力..."
            disabled={loading}
            className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-200 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:bg-slate-400 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? '...' : '送信'}
          </button>
        </div>

        {/* Tips */}
        <div className="text-xs text-slate-500">
          💡 Enterキーで送信 | Shift+Enterで複数行入力
        </div>
      </div>
    </div>
  )
}
