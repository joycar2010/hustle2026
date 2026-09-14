import { useEffect, useState, useCallback, useMemo } from 'react'
import { getCoins, markNewCoin, markDelisting, patchCoin, syncVolume, type Coin } from '@/api/coins'
import { extractError } from '@/api/client'
import { useToastStore } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn, formatNumber } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'

type Filter = 'all' | 'new' | 'delisting'

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

  const filtered = useMemo(() => {
    const q = search.toUpperCase()
    return coins.filter((c) => {
      if (q && !c.symbol.includes(q)) return false
      if (filter === 'new') return c.is_new_coin
      if (filter === 'delisting') return c.is_delisting
      return true
    })
  }, [coins, filter, search])

  const newCount = coins.filter((c) => c.is_new_coin).length
  const delistCount = coins.filter((c) => c.is_delisting).length

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-xl font-bold">币种管理</h1>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {(['all', 'new', 'delisting'] as Filter[]).map((f) => (
              <Button
                key={f}
                size="sm"
                variant={filter === f ? 'default' : 'outline'}
                onClick={() => setFilter(f)}
              >
                {f === 'all' ? '全部' : f === 'new' ? `新币(${newCount})` : `下架(${delistCount})`}
              </Button>
            ))}
          </div>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索币种..."
            className="w-full sm:w-36"
          />
          <Button size="sm" variant="outline" disabled={syncing} onClick={handleSyncVolume}>
            <RefreshCw className={cn('h-4 w-4', syncing && 'animate-spin')} />
            {syncing ? '同步中...' : '同步交易量'}
          </Button>
          <span className="text-xs text-muted-foreground">{filtered.length} / {coins.length}</span>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full md:min-w-[900px] text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-3 font-medium">币种</th>
                <th className="px-4 py-3 font-medium">基础资产</th>
                <th className="px-4 py-3 text-center font-medium">杠杆</th>
                <th className="px-4 py-3 text-center font-medium">合约</th>
                <th className="px-4 py-3 text-right font-medium">24h交易量</th>
                <th className="px-4 py-3 text-center font-medium">新币</th>
                <th className="px-4 py-3 text-center font-medium">下架</th>
                <th className="px-4 py-3 text-center font-medium">允许开仓</th>
                <th className="px-4 py-3 text-center font-medium">活跃</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">{search ? '未找到匹配币种' : '暂无数据'}</td></tr>
              ) : filtered.map((c) => (
                <tr key={c.id} className="border-b last:border-0 hover:bg-accent/50">
                  <td className="px-4 py-2.5 font-medium">{c.symbol}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">{c.base_asset}</td>
                  <td className="px-4 py-2.5 text-center">
                    <Badge variant={c.margin_tradable ? 'success' : 'secondary'}>
                      {c.margin_tradable ? '✓' : '-'}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <Badge variant={c.futures_tradable ? 'success' : 'secondary'}>
                      {c.futures_tradable ? '✓' : '-'}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {c.volume_24h ? formatNumber(c.volume_24h) : '-'}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <Button size="sm" variant="ghost" onClick={() => handleMarkNew(c.symbol)}>
                      <Badge variant={c.is_new_coin ? 'warning' : 'secondary'}>
                        {c.is_new_coin ? '新币' : '-'}
                      </Badge>
                    </Button>
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <Button size="sm" variant="ghost" onClick={() => handleMarkDelisting(c.symbol)}>
                      <Badge variant={c.is_delisting ? 'destructive' : 'secondary'}>
                        {c.is_delisting ? '下架' : '-'}
                      </Badge>
                    </Button>
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <Button size="sm" variant="ghost" onClick={() => handleToggleOpen(c.symbol, c.allow_open)}>
                      <Badge variant={c.allow_open ? 'success' : 'destructive'}>
                        {c.allow_open ? '允许' : '禁止'}
                      </Badge>
                    </Button>
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <Badge variant={c.is_active ? 'success' : 'secondary'}>
                      {c.is_active ? '✓' : '-'}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
