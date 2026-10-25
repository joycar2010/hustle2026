import { useState, useRef, useEffect, useCallback } from 'react'
import { MessageSquare, X, Send, Trash2, Search, ArrowLeft, Plus } from 'lucide-react'

interface ChatMsg { role: 'user' | 'assistant'; content: string }
interface ConvItem { id: number; session_id: string; title: string; message_count: number; updated_at: string | null }

const SITE = 'coin'
const TOKEN_KEY = 'cex_jwt_token'
const SESSION_KEY = 'ai_chat_session_coin'
const PRIMARY = '#3b82f6'

function apiFetch(path: string, opts: RequestInit = {}) {
  const token = localStorage.getItem(TOKEN_KEY)
  const base = import.meta.env.VITE_API_BASE_URL || ''
  return fetch(`${base}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...opts.headers,
    },
  })
}

export function FloatingChatWidget() {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<'chat' | 'history'>('chat')
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(SESSION_KEY) || crypto.randomUUID())
  const [convId, setConvId] = useState<number | null>(null)
  const [convList, setConvList] = useState<ConvItem[]>([])
  const [searchText, setSearchText] = useState('')
  const [historyLoading, setHistoryLoading] = useState(false)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const loadedRef = useRef(false)

  useEffect(() => { localStorage.setItem(SESSION_KEY, sessionId) }, [sessionId])
  useEffect(() => { messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, open])

  const loadCurrentMessages = useCallback(async () => {
    if (!convId || loadedRef.current) return
    try {
      const resp = await apiFetch(`/api/ai/chat/history/${convId}`)
      if (resp.ok) {
        const msgs: { role: string; content: string }[] = await resp.json()
        setMessages(msgs.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
        loadedRef.current = true
      }
    } catch { /* ignore */ }
  }, [convId])

  useEffect(() => {
    if (open && convId) loadCurrentMessages()
  }, [open, convId, loadCurrentMessages])

  const findCurrentConv = useCallback(async () => {
    try {
      const resp = await apiFetch(`/api/ai/chat/history?site=${SITE}`)
      if (!resp.ok) return
      const list: ConvItem[] = await resp.json()
      const match = list.find(c => c.session_id === sessionId)
      if (match) {
        setConvId(match.id)
      }
    } catch { /* ignore */ }
  }, [sessionId])

  useEffect(() => {
    if (open && !convId) findCurrentConv()
  }, [open, convId, findCurrentConv])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const params = new URLSearchParams({ site: SITE })
      if (searchText) params.set('search', searchText)
      const resp = await apiFetch(`/api/ai/chat/history?${params}`)
      if (resp.ok) setConvList(await resp.json())
    } catch { /* ignore */ }
    finally { setHistoryLoading(false) }
  }, [searchText])

  useEffect(() => {
    if (view === 'history') loadHistory()
  }, [view, loadHistory])

  const startNewChat = () => {
    const newId = crypto.randomUUID()
    setSessionId(newId)
    setConvId(null)
    setMessages([])
    loadedRef.current = false
    setView('chat')
  }

  const switchToConv = async (conv: ConvItem) => {
    setSessionId(conv.session_id)
    setConvId(conv.id)
    loadedRef.current = false
    setMessages([])
    setView('chat')
  }

  const deleteConv = async (id: number) => {
    try {
      const resp = await apiFetch(`/api/ai/chat/history/${id}`, { method: 'DELETE' })
      if (resp.ok) {
        setConvList(prev => prev.filter(c => c.id !== id))
        if (convId === id) startNewChat()
      }
    } catch { /* ignore */ }
  }

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setStreaming(true)
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      const controller = new AbortController()
      abortRef.current = controller
      const resp = await apiFetch('/api/ai/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, session_id: sessionId, site: SITE }),
        signal: controller.signal,
      })

      if (!resp.ok) {
        const err = await resp.text()
        setMessages(prev => { const c = [...prev]; c[c.length - 1] = { role: 'assistant', content: `Error: ${err}` }; return c })
        setStreaming(false)
        return
      }

      const reader = resp.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) return

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data: ')) continue
          try {
            const data = JSON.parse(line.slice(6))
            if (data.content) {
              setMessages(prev => {
                const c = [...prev]; const last = c[c.length - 1]
                c[c.length - 1] = { ...last, content: last.content + data.content }; return c
              })
            }
            if (data.done) {
              if (data.conversation_id) setConvId(data.conversation_id)
            }
          } catch { /* skip */ }
        }
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setMessages(prev => { const c = [...prev]; c[c.length - 1] = { role: 'assistant', content: 'Network error' }; return c })
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }, [input, streaming, sessionId])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-50 flex h-12 w-12 md:bottom-6 md:right-6 md:h-14 md:w-14 items-center justify-center rounded-full shadow-lg transition-transform hover:scale-110"
          style={{ backgroundColor: PRIMARY }}>
          <MessageSquare className="h-6 w-6 text-white" />
        </button>
      )}

      {open && (
        <div className="fixed inset-0 z-50 flex flex-col bg-background md:inset-auto md:bottom-6 md:right-6 md:h-[520px] md:w-[400px] md:rounded-xl md:shadow-2xl md:border">
          {/* Header */}
          <div className="flex items-center justify-between rounded-t-xl px-4 py-3 text-white"
            style={{ background: `linear-gradient(135deg, ${PRIMARY}, #2563eb)` }}>
            <div className="flex items-center gap-2">
              {view === 'history' && (
                <button onClick={() => setView('chat')} className="rounded p-1 hover:bg-white/20">
                  <ArrowLeft className="h-4 w-4" />
                </button>
              )}
              <MessageSquare className="h-5 w-5" />
              <span className="font-medium text-sm">{view === 'chat' ? 'HustleCoin 智能助手' : '对话记录'}</span>
            </div>
            <div className="flex items-center gap-1">
              {view === 'chat' && (
                <>
                  <button onClick={startNewChat} className="rounded p-1 hover:bg-white/20" title="新对话">
                    <Plus className="h-4 w-4" />
                  </button>
                  <button onClick={() => setView('history')} className="rounded p-1 hover:bg-white/20" title="对话记录">
                    <Search className="h-4 w-4" />
                  </button>
                </>
              )}
              <button onClick={() => setOpen(false)} className="rounded p-1 hover:bg-white/20">
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {view === 'history' ? (
            <div className="flex flex-1 flex-col overflow-hidden">
              <div className="border-b p-2">
                <div className="flex items-center gap-2 rounded-md border border-input px-2">
                  <Search className="h-3.5 w-3.5 text-muted-foreground" />
                  <input className="h-8 flex-1 bg-transparent text-sm outline-none"
                    placeholder="搜索对话..." value={searchText}
                    onChange={e => setSearchText(e.target.value)} />
                </div>
              </div>
              <div className="flex-1 overflow-auto">
                {historyLoading ? (
                  <p className="py-8 text-center text-sm text-muted-foreground">加载中...</p>
                ) : convList.length === 0 ? (
                  <p className="py-8 text-center text-sm text-muted-foreground">暂无对话记录</p>
                ) : convList.map(c => (
                  <div key={c.id}
                    className={`flex items-center gap-2 border-b px-3 py-2.5 hover:bg-accent/50 cursor-pointer ${c.id === convId ? 'bg-accent/30' : ''}`}
                    onClick={() => switchToConv(c)}>
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-sm font-medium">{c.title || '未命名对话'}</p>
                      <p className="text-xs text-muted-foreground">
                        {c.message_count} 条消息 · {c.updated_at ? new Date(c.updated_at).toLocaleString('zh-CN') : ''}
                      </p>
                    </div>
                    <button onClick={e => { e.stopPropagation(); deleteConv(c.id) }}
                      className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <>
              <div className="flex-1 overflow-auto p-3 space-y-3">
                {messages.length === 0 && (
                  <div className="flex items-center justify-center h-full">
                    <p className="text-sm text-muted-foreground text-center px-4">
                      你好！我是 HustleCoin 智能助手，有任何交易或操作问题都可以问我。
                    </p>
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.role === 'user' ? 'text-white' : 'bg-muted'}`}
                      style={m.role === 'user' ? { backgroundColor: PRIMARY } : undefined}>
                      <p className="whitespace-pre-wrap break-words">
                        {m.content || (streaming && i === messages.length - 1 ? '...' : '')}
                      </p>
                    </div>
                  </div>
                ))}
                <div ref={messagesEnd} />
              </div>
              <div className="border-t p-3">
                <div className="flex gap-2">
                  <textarea className="flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none"
                    rows={1} placeholder="输入问题..." value={input}
                    onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown} disabled={streaming} />
                  <button onClick={sendMessage} disabled={!input.trim() || streaming}
                    className="flex h-9 w-9 items-center justify-center rounded-md text-white disabled:opacity-50"
                    style={{ backgroundColor: PRIMARY }}>
                    <Send className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}
