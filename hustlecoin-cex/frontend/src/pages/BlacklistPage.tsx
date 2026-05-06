import { useEffect, useState, useCallback } from 'react'
import { getBlacklist, addToBlacklist, removeFromBlacklist } from '@/api/blacklist'

interface BlacklistItem {
  symbol: string
  created_at?: string
}

export function BlacklistPage() {
  const [items, setItems] = useState<BlacklistItem[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)

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
      await addToBlacklist(sym)
      setInput('')
      refresh()
    } catch { /* ignore */ }
  }, [input, refresh])

  const handleRemove = useCallback(async (symbol: string) => {
    try {
      await removeFromBlacklist(symbol)
      refresh()
    } catch { /* ignore */ }
  }, [refresh])

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h1 className="text-sm font-semibold">黑名单管理</h1>
        <div className="ml-auto flex items-center gap-1">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="输入币种"
            className="w-32 bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
          />
          <button
            onClick={handleAdd}
            disabled={!input.trim()}
            className="px-2 py-1 bg-primary/20 text-primary rounded text-xs hover:bg-primary/30 disabled:opacity-40"
          >
            添加
          </button>
        </div>
      </div>

      <div className="rounded border border-border overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-[#111118] text-muted-foreground border-b border-border">
              <th className="text-left px-3 py-2 font-medium">币种</th>
              <th className="text-left px-3 py-2 font-medium">添加时间</th>
              <th className="text-right px-3 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-muted-foreground">加载中...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-muted-foreground">暂无黑名单</td></tr>
            ) : items.map((item) => (
              <tr key={item.symbol} className="border-b border-border/50 hover:bg-accent/30">
                <td className="px-3 py-1.5 font-mono">{item.symbol}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '-'}</td>
                <td className="px-3 py-1.5 text-right">
                  <button
                    onClick={() => handleRemove(item.symbol)}
                    className="text-negative hover:text-negative/80 text-xs"
                  >
                    移除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
