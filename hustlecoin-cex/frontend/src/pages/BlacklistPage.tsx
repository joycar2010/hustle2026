import { useEffect, useState, useCallback } from 'react'
import { getBlacklist, addToBlacklist, removeFromBlacklist, batchAddBlacklist } from '@/api/blacklist'

interface BlacklistItem {
  symbol: string
  reason?: string | null
  created_at?: string
  user_id?: number | null   // null=全局系统黑名单(不可删除);有值=本人个人黑名单
}

export function BlacklistPage({ embedded }: { onClose?: () => void; embedded?: boolean } = {}) {
  const [items, setItems] = useState<BlacklistItem[]>([])
  const [input, setInput] = useState('')
  const [reason, setReason] = useState('')
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchText, setBatchText] = useState('')
  const [batchReason, setBatchReason] = useState('')
  const [loading, setLoading] = useState(true)
  // 右键菜单:对某行币种快捷操作(移除黑名单)。全局系统条目(user_id==null)不可删。
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; item: BlacklistItem } | null>(null)

  useEffect(() => {
    if (!ctxMenu) return
    const close = () => setCtxMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => { window.removeEventListener('click', close); window.removeEventListener('scroll', close, true) }
  }, [ctxMenu])

  const refresh = useCallback(async () => {
    try {
      const data = await getBlacklist()
      setItems(Array.isArray(data) ? data : data.items ?? [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const handleAdd = useCallback(async () => {
    const sym = input.trim().toUpperCase()
    if (!sym) return
    if (!confirm(`确认将 "${sym}" 加入黑名单？加入后从借币列表移除，不再推送。`)) return
    try {
      await addToBlacklist(sym, reason.trim() || undefined)
      setInput(''); setReason('')
      refresh()
    } catch (e) {
      const resp = (e as { response?: { data?: { detail?: string } } })?.response
      alert(`添加失败: ${resp?.data?.detail || '未知错误'}`)
    }
  }, [input, reason, refresh])

  const handleBatchAdd = useCallback(async () => {
    const syms = batchText
      .split(/[\s,，、\n]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    if (syms.length === 0) { alert('请输入至少一个币种'); return }
    if (!confirm(`确认批量加入 ${syms.length} 个币种到黑名单？\n${syms.join(', ')}`)) return
    try {
      const r = await batchAddBlacklist(syms, batchReason.trim() || undefined)
      alert(r.message || '批量添加完成')
      setBatchText(''); setBatchReason(''); setBatchOpen(false)
      refresh()
    } catch (e) {
      const resp = (e as { response?: { data?: { detail?: string } } })?.response
      alert(`批量添加失败: ${resp?.data?.detail || '未知错误'}`)
    }
  }, [batchText, batchReason, refresh])

  const handleRemove = useCallback(async (symbol: string) => {
    try {
      await removeFromBlacklist(symbol)
      refresh()
    } catch { /* ignore */ }
  }, [refresh])

  return (
    <div className={embedded ? 'space-y-3 p-3' : 'space-y-3'}>
      <div className="flex items-center gap-2">
        {!embedded && <h1 className="text-sm font-semibold">黑名单管理</h1>}
        <div className="ml-auto flex items-center gap-1">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="输入币种"
            className="w-28 bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
          />
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="原因(可选)"
            className="w-32 bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
          />
          <button
            onClick={handleAdd}
            disabled={!input.trim()}
            className="px-2 py-1 bg-primary/20 text-primary rounded text-xs hover:bg-primary/30 disabled:opacity-40"
          >
            添加
          </button>
          <button
            onClick={() => setBatchOpen((v) => !v)}
            className="px-2 py-1 border border-border rounded text-xs text-muted-foreground hover:bg-accent/50"
          >
            批量
          </button>
        </div>
      </div>

      {batchOpen && (
        <div className="rounded border border-border p-3 space-y-2 bg-[#111118]">
          <div className="text-[11px] text-muted-foreground">批量添加 — 用空格/逗号/换行分隔多个币种</div>
          <textarea
            value={batchText}
            onChange={(e) => setBatchText(e.target.value)}
            placeholder="BTC, ETH, DUSK&#10;SOL PEPE"
            rows={3}
            className="w-full bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary font-mono"
          />
          <div className="flex items-center gap-2">
            <input
              value={batchReason}
              onChange={(e) => setBatchReason(e.target.value)}
              placeholder="统一原因(可选)"
              className="flex-1 bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
            />
            <button
              onClick={handleBatchAdd}
              className="px-3 py-1 bg-primary/20 text-primary rounded text-xs hover:bg-primary/30"
            >
              批量添加
            </button>
          </div>
        </div>
      )}

      <div className="rounded border border-border overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-[#111118] text-muted-foreground border-b border-border">
              <th className="text-left px-3 py-2 font-medium">币种</th>
              <th className="text-left px-3 py-2 font-medium">原因</th>
              <th className="text-left px-3 py-2 font-medium">添加时间</th>
              <th className="text-right px-3 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">加载中...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">暂无黑名单</td></tr>
            ) : items.map((item) => {
              const isGlobal = item.user_id == null
              return (
              <tr
                key={item.symbol}
                onContextMenu={(e) => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, item }) }}
                className="border-b border-border/50 hover:bg-accent/30"
              >
                <td className="px-3 py-1.5 font-mono">
                  {item.symbol}
                  {isGlobal && (
                    <span className="ml-1.5 px-1 py-0.5 rounded bg-muted text-[10px] text-muted-foreground align-middle">系统</span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-muted-foreground">{item.reason || '-'}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '-'}</td>
                <td className="px-3 py-1.5 text-right">
                  {isGlobal ? (
                    <span className="text-muted-foreground/50 text-xs" title="系统全局黑名单(死币/持续无券),由引擎自动管理,不可手动删除">自动</span>
                  ) : (
                    <button
                      onClick={() => handleRemove(item.symbol)}
                      className="text-negative hover:text-negative/80 text-xs"
                    >
                      移除
                    </button>
                  )}
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 右键菜单 — 移除黑名单(全局系统条目不可删) */}
      {ctxMenu && (
        <div
          className="fixed z-50 min-w-[140px] max-w-[90vw] rounded-md border border-border bg-[#111118] py-1 shadow-xl text-xs"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-3 py-1 text-muted-foreground/60 border-b border-border/50 font-mono">{ctxMenu.item.symbol}</div>
          {ctxMenu.item.user_id == null ? (
            <div className="px-3 py-1.5 text-muted-foreground/50" title="系统全局黑名单,由引擎自动管理,不可手动删除">系统条目不可删除</div>
          ) : (
            <button
              onClick={() => { handleRemove(ctxMenu.item.symbol); setCtxMenu(null) }}
              className="block w-full text-left px-3 py-1.5 text-negative hover:bg-accent/40"
            >
              移除黑名单
            </button>
          )}
        </div>
      )}
    </div>
  )
}
