import { useEffect, useRef } from 'react'

export function useSSE(url: string, handlers: Record<string, (data: any) => void>) {
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!url) return
    let retry = 0
    let stop = false
    const start = () => {
      if (stop) return
      const es = new EventSource(url)
      esRef.current = es
      const on = (ev: MessageEvent) => {
        try {
          const j = JSON.parse(ev.data)
          const h = handlers[j.event as string] || handlers['message']
          if (h) h(j)
        } catch {}
      }
      es.onmessage = on
      Object.keys(handlers).forEach(k => es.addEventListener(k, on as any))
      es.onerror = () => {
        es.close()
        retry = Math.min(30000, (retry ? retry * 2 : 1000))
        setTimeout(start, retry)
      }
    }
    start()
    return () => { stop = true; esRef.current?.close() }
  }, [url])
}

