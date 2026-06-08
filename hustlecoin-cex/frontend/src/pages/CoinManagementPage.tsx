import { useEffect, useState, useCallback, useMemo } from 'react'
import { getCoins, markNewCoin, markDelisting, patchCoin, syncVolume, type Coin } from '@/api/coins'
import { useToastStore } from '@/components/ui/toast'
import { extractError } from '@/api/client'
import { cn, formatNumber } from '@/lib/utils'

type Filter = 'all' | 'new' | 'delisting' | 'risky'

export function CoinManagementPage() {
  const [coins, setCoins] = useState<Coin[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const addToast = useToastStore((s) => s.addToast)

  const loadCoins = useCallback(async () => {
    try {
      const data = await getCoins()
      setCoins(data)
    } catch (err: unknown) {
      addToast(extractError(err, '加载币种失败'), 'error')
    }
    setLoading(false)
  }, [addToast])

  useEffect(() => { loadCoins() }, [loadCoins])

  const handleSyncVolume = useCallback(async () => {
    setSyncing(true)
    try {
      await syncVolume()
      addToast('交易量已同步', 'success')
      await loadCoins()
    } catch (err: unknown) {
      addToast(extractError(err, '同步失败'), 'error')
    }
    setSyncing(false)
  }, [addToast, loadCoins])

  const handleMarkNew = useCallback(async (symbol: string) => {
    try {
      await markNewCoin(symbol)
      addToast(`${symbol} 已标记为新币`, 'success')
      setCoins((prev) => prev.map((c) => c.symbol === symbol ? { ...c, is_new_coin: !c.is_new_coin } : c))
    } catch (err: unknown) {
      addToast(extractError(err, '操作失败'), 'error')
    }
  }, [addToast])

  const handleMarkDelisting = useCallback(async (symbol: string) => {
    try {
      await markDelisting(symbol)
      addToast(`${symbol} 已标记下架`, 'success')
      setCoins((prev) => prev.map((c) => c.symbol === symbol ? { ...c, is_delisting: !c.is_delisting } : c))
    } catch (err: unknown) {
      addToast(extractError(err, '操作失败'), 'error')
    }
  }, [addToast])

  const handleToggleOpen = useCallback(async (symbol: string, current: boolean) => {
    try {
      await patchCoin(symbol, { allow_open: !current })
      addToast(`${symbol} 开仓${!current ? '已启用' : '已禁用'}`, 'success')
      setCoins((prev) => prev.map((c) => c.symbol === symbol ? { ...c, allow_open: !current } : c))
    } catch (err: unknown) {
      addToast(extractError(err, '操作失败'), 'error')
    }
  }, [addToast])

  const handleToggleRisky = useCallback(async (symbol: string, current: boolean) => {
    try {
      await patchCoin(symbol, { is_risky: !current })
      addToast(`${symbol} 风险标记${!current ? '已开启' : '已清除'}`, 'success')
      setCoins((prev) => prev.map((c) => c.symbol === symbol ? { ...c, is_risky: !current } : c))
    } catch (err: unknown) {
      addToast(extractError(err, '操作失败'), 'error')
    }
  }, [addToast])

  const filtered = useMemo(() => {
    const q = search.toUpperCase()
    return coins.filter((c) => {
      if (q && !c.symbol.includes(q)) return false
      if (filter === 'new') return c.is_new_coin
      if (filter === 'delisting') return c.is_delisting
      if (filter === 'risky') return c.is_risky
      return true
    })
  }, [coins, filter, search])

  const newCount = coins.filter((c) => c.is_new_coin).length
  const delistCount = coins.filter((c) => c.is_delisting).length
  const riskyCount = coins.filter((c) => c.is_risky).length

  if (loading) return <p className="py-8 text-center text-muted-foreground text-xs">加载中...</p>

  return (
    <div className="flex flex-col h-[calc(100vh-5.5rem)]">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-border shrink-0">
        <h2 className="text-sm font-semibold">币种管理</h2>
        <button
          onClick={handleSyncVolume}
          disabled={syncing}
          className="px-2 py-0.5 bg-primary/20 text-primary rounded text-[11px] hover:bg-primary/30 disabled:opacity-40"
        >
          {syncing ? '同步中...' : '同步交易量'}
        </button>
        <div className="flex gap-1 ml-2">
          {(['all', 'new', 'delisting', 'risky'] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-2 py-0.5 rounded text-[11px]',
                filter === f ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground hover:bg-accent',
              )}
            >
              {f === 'all' ? '全部' : f === 'new' ? `新币(${newCount})` : f === 'delisting' ? `下架(${delistCount})` : `风险(${riskyCount})`}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索..."
          className="w-28 bg-transparent border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary ml-auto"
        />
        <span className="text-[11px] text-muted-foreground">{filtered.length} / {coins.length}</span>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 z-10">
            <tr className="bg-[#0d0d14] text-[10px] text-muted-foreground border-b border-border">
              <th className="px-2 py-1 text-left font-medium">币种</th>
              <th className="px-2 py-1 text-left font-medium">基础</th>
              <th className="px-2 py-1 text-center font-medium">杠杆</th>
              <th className="px-2 py-1 text-center font-medium">合约</th>
              <th className="px-2 py-1 text-right font-medium">24h交易量</th>
              <th className="px-2 py-1 text-center font-medium">新币</th>
              <th className="px-2 py-1 text-center font-medium">下架</th>
              <th className="px-2 py-1 text-center font-medium">风险</th>
              <th className="px-2 py-1 text-center font-medium">允许开仓</th>
              <th className="px-2 py-1 text-center font-medium">活跃</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.id} className="border-b border-border/20 hover:bg-accent/20">
                <td className="px-2 py-1 font-medium">{c.symbol}</td>
                <td className="px-2 py-1 text-muted-foreground">{c.base_asset}</td>
                <td className="px-2 py-1 text-center">
                  <span className={c.margin_tradable ? 'text-positive' : 'text-muted-foreground'}>
                    {c.margin_tradable ? '✓' : '-'}
                  </span>
                </td>
                <td className="px-2 py-1 text-center">
                  <span className={c.futures_tradable ? 'text-positive' : 'text-muted-foreground'}>
                    {c.futures_tradable ? '✓' : '-'}
                  </span>
                </td>
                <td className="px-2 py-1 text-right font-mono">
                  {c.volume_24h ? formatNumber(c.volume_24h) : '-'}
                </td>
                <td className="px-2 py-1 text-center">
                  <button
                    onClick={() => handleMarkNew(c.symbol)}
                    className={cn(
                      'px-1.5 py-0.5 rounded text-[10px]',
                      c.is_new_coin ? 'bg-amber-500/20 text-amber-400' : 'text-muted-foreground hover:bg-accent',
                    )}
                  >
                    {c.is_new_coin ? '新币' : '-'}
                  </button>
                </td>
                <td className="px-2 py-1 text-center">
                  <button
                    onClick={() => handleMarkDelisting(c.symbol)}
                    className={cn(
                      'px-1.5 py-0.5 rounded text-[10px]',
                      c.is_delisting ? 'bg-negative/20 text-negative' : 'text-muted-foreground hover:bg-accent',
                    )}
                  >
                    {c.is_delisting ? '下架' : '-'}
                  </button>
                </td>
                <td className="px-2 py-1 text-center">
                  <button
                    onClick={() => handleToggleRisky(c.symbol, c.is_risky)}
                    className={cn(
                      'px-1.5 py-0.5 rounded text-[10px]',
                      c.is_risky ? 'bg-negative/20 text-negative' : 'text-muted-foreground hover:bg-accent',
                    )}
                  >
                    {c.is_risky ? '⚠风险' : '-'}
                  </button>
                </td>
                <td className="px-2 py-1 text-center">
                  <button
                    onClick={() => handleToggleOpen(c.symbol, c.allow_open)}
                    className={cn(
                      'px-1.5 py-0.5 rounded text-[10px]',
                      c.allow_open ? 'bg-positive/20 text-positive' : 'bg-negative/20 text-negative',
                    )}
                  >
                    {c.allow_open ? '允许' : '禁止'}
                  </button>
                </td>
                <td className="px-2 py-1 text-center">
                  <span className={c.is_active ? 'text-positive' : 'text-muted-foreground'}>
                    {c.is_active ? '✓' : '-'}
                  </span>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={10} className="py-8 text-center text-muted-foreground text-xs">
                  {search ? '未找到匹配币种' : '暂无数据'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
