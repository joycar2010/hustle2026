import { useEffect, useState, useCallback, useRef } from 'react'
import {
  getAnnouncements, checkDelist, listPendingBlacklist, confirmBlacklist, dismissPending,
  getKlineData, searchCoin, getRankings, resetHistoryScores, getNetExpect,
  type AnnouncementItem, type PendingBlacklistItem, type CoinSearchItem, type RankingItem, type HistoryScoreItem,
  type NetExpectRow,
} from '@/api/admin'
import { extractError } from '@/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { useAutoRefresh } from '@/hooks/useAutoRefresh'
import {
  AlertTriangle, Search, CheckCircle, XCircle, ExternalLink, RefreshCw, ShieldAlert,
  CandlestickChart, TrendingUp, Calculator,
} from 'lucide-react'
import { createChart, type IChartApi, CandlestickSeries, HistogramSeries, ColorType, type UTCTimestamp } from 'lightweight-charts'

type Tab = 'kline' | 'rankings' | 'announcements' | 'blacklist' | 'netexpect'

export function MarketMonitorPage() {
  const [tab, setTab] = useState<Tab>('kline')

  const tabCls = (t: Tab) =>
    `flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
      tab === t ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
    }`

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">行情检测</h1>

      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <button onClick={() => setTab('kline')} className={tabCls('kline')}>
          <CandlestickChart className="h-4 w-4" /> K线查询
        </button>
        <button onClick={() => setTab('rankings')} className={tabCls('rankings')}>
          <TrendingUp className="h-4 w-4" /> 涨幅榜
        </button>
        <button onClick={() => setTab('announcements')} className={tabCls('announcements')}>
          <AlertTriangle className="h-4 w-4" /> 公告监控
        </button>
        <button onClick={() => setTab('blacklist')} className={tabCls('blacklist')}>
          <ShieldAlert className="h-4 w-4" /> 待审核黑名单
        </button>
        <button onClick={() => setTab('netexpect')} className={tabCls('netexpect')}>
          <Calculator className="h-4 w-4" /> 净期望E榜
        </button>
      </div>

      {tab === 'kline' && <KlineTab />}
      {tab === 'rankings' && <RankingsTab />}
      {tab === 'announcements' && <AnnouncementsTab />}
      {tab === 'blacklist' && <BlacklistTab />}
      {tab === 'netexpect' && <NetExpectTab />}
    </div>
  )
}

// ─── 净期望 E 榜 Tab(P0-1: 开仓成本线) ───

function NetExpectTab() {
  const [rows, setRows] = useState<NetExpectRow[]>([])
  const [meta, setMeta] = useState<{ positive: number; negative: number; gate_mode: string | null }>({ positive: 0, negative: 0, gate_mode: null })

  const fetch = useCallback(async () => {
    try {
      const d = await getNetExpect()
      setRows(d.rows || [])
      setMeta({ positive: d.positive, negative: d.negative, gate_mode: d.gate_mode })
    } catch { /* 静默 */ }
  }, [])
  useAutoRefresh(fetch, 10000)

  const modeLabel = meta.gate_mode === 'enforce' ? '强制(E≤0拒开)'
    : meta.gate_mode === 'off' ? '关闭' : '影子(记录不拦)'
  const fmt = (v: number | null | undefined, d = 4) => v == null ? '—' : v.toFixed(d)

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium">开仓净期望收益 E</span>
          <Badge variant={meta.gate_mode === 'enforce' ? 'default' : 'secondary'}>闸模式: {modeLabel}</Badge>
          <span className="text-emerald-500">可做(E&gt;0): {meta.positive}</span>
          <span className="text-red-500">被成本吃(E≤0): {meta.negative}</span>
          <span className="text-muted-foreground text-xs">E = 点差捕获 − 利息 − 4腿手续费 − tick摩擦(USDT);60s内引擎评估过的币</span>
        </div>
        {rows.length === 0 ? (
          <div className="py-10 text-center text-muted-foreground text-sm">近 60 秒无开仓评估记录(点差达标才评估;shadow 模式下有借币尝试才写入)</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-muted-foreground text-left">
                  <th className="px-2 py-1.5">币种</th>
                  <th className="px-2 py-1.5 text-right">净期望 E(U)</th>
                  <th className="px-2 py-1.5 text-right">名义(U)</th>
                  <th className="px-2 py-1.5 text-right">点差捕获</th>
                  <th className="px-2 py-1.5 text-right">利息</th>
                  <th className="px-2 py-1.5 text-right">手续费</th>
                  <th className="px-2 py-1.5 text-right">tick摩擦</th>
                  <th className="px-2 py-1.5 text-center">决定</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const pos = (r.E ?? 0) > 0
                  return (
                    <tr key={`${r.user_id}-${r.symbol}`} className="border-b border-border/30 hover:bg-accent/10">
                      <td className="px-2 py-1.5 font-medium">{r.symbol.replace('USDT', '')}</td>
                      <td className={`px-2 py-1.5 text-right font-mono font-semibold ${pos ? 'text-emerald-500' : 'text-red-500'}`}>{fmt(r.E)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{fmt(r.notional_usdt, 1)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-emerald-500/80">{fmt(r.spread_capture)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-amber-500/80">−{fmt(r.interest_cost)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-amber-500/80">−{fmt(r.fee_cost)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-amber-500/80">−{fmt(r.tick_cost)}</td>
                      <td className="px-2 py-1.5 text-center">
                        <Badge variant={r.decision === 'reject' ? 'destructive' : pos ? 'default' : 'secondary'}>
                          {r.decision === 'reject' ? '拒开' : r.decision === 'borrow' && !pos ? '影子放行' : '可做'}
                        </Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── K-Line Tab ───

const PERIODS = [
  { label: '1分', value: '1' },
  { label: '5分', value: '5' },
  { label: '15分', value: '15' },
  { label: '30分', value: '30' },
  { label: '1时', value: '60' },
  { label: '4时', value: '240' },
  { label: '1天', value: '1440' },
]

function KlineTab() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CoinSearchItem[]>([])
  const [selectedSymbol, setSelectedSymbol] = useState('btcswapusdt:binance')
  const [selectedLabel, setSelectedLabel] = useState('BTC/USDT (Binance)')
  const [period, setPeriod] = useState('60')
  const [loading, setLoading] = useState(false)
  const [showSearch, setShowSearch] = useState(false)
  const [ohlc, setOhlc] = useState({ o: 0, h: 0, l: 0, c: 0, change: 0 })
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const candleSeriesRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const volumeSeriesRef = useRef<any>(null)
  const addToast = useToastStore((s) => s.addToast)
  const searchTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    if (!chartContainerRef.current) return
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a12' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1e1e2e' },
        horzLines: { color: '#1e1e2e' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: '#2d2d3d' },
      timeScale: { borderColor: '#2d2d3d', timeVisible: true, secondsVisible: false },
      width: chartContainerRef.current.clientWidth,
      height: window.innerWidth < 768 ? 300 : 500,
    })
    chartRef.current = chart

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      wickUpColor: '#22c55e',
    })
    candleSeriesRef.current = candleSeries

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })
    volumeSeriesRef.current = volumeSeries

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth, height: window.innerWidth < 768 ? 300 : 500 })
      }
    }
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  const loadKline = useCallback(async () => {
    if (!selectedSymbol) return
    setLoading(true)
    try {
      const res = await getKlineData({ symbol: selectedSymbol, period, size: 300 })
      const raw = res.data || []
      if (!raw.length) {
        addToast('无K线数据', 'error')
        return
      }

      const candles = raw.map((d: number[]) => ({
        time: d[0] as UTCTimestamp,
        open: d[1],
        high: d[2],
        low: d[3],
        close: d[4],
      }))
      const volumes = raw.map((d: number[]) => ({
        time: d[0] as UTCTimestamp,
        value: d[5] || 0,
        color: d[4] >= d[1] ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
      }))

      candleSeriesRef.current?.setData(candles)
      volumeSeriesRef.current?.setData(volumes)
      chartRef.current?.timeScale().fitContent()

      const last = candles[candles.length - 1]
      const first = candles[0]
      if (last && first) {
        const change = ((last.close - first.open) / first.open) * 100
        setOhlc({ o: last.open, h: last.high, l: last.low, c: last.close, change })
      }
    } catch {
      addToast('K线加载失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [selectedSymbol, period, addToast])

  useEffect(() => { loadKline() }, [loadKline])

  const handleSearch = (val: string) => {
    setQuery(val)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    if (val.length < 1) { setResults([]); setShowSearch(false); return }
    searchTimer.current = setTimeout(async () => {
      try {
        const data = await searchCoin(val)
        setResults(Array.isArray(data) ? data : [])
        setShowSearch(true)
      } catch { setResults([]) }
    }, 300)
  }

  const selectCoin = (coin: CoinSearchItem) => {
    const dbKey = coin.dbKeys?.split(',')[0] || coin.coinKey
    setSelectedSymbol(dbKey)
    setSelectedLabel(coin.coinShow || coin.coinName)
    setQuery('')
    setShowSearch(false)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative">
          <Input
            className="w-full sm:w-52"
            placeholder="搜索币种 (BTC, ETH...)"
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            onFocus={() => results.length > 0 && setShowSearch(true)}
            onBlur={() => setTimeout(() => setShowSearch(false), 200)}
          />
          {showSearch && results.length > 0 && (
            <div className="absolute z-50 mt-1 w-[calc(100vw-4rem)] max-w-80 max-h-60 overflow-y-auto rounded-md border bg-popover shadow-lg">
              {results.map((c, i) => (
                <button
                  key={c.coinKey + i}
                  className="flex w-full items-center justify-between px-3 py-2 text-sm hover:bg-accent text-left"
                  onMouseDown={() => selectCoin(c)}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{c.coinShow || c.coinName}</span>
                    {c.degree24H && c.degree24H !== '-' && (
                      <span className={`text-xs ${parseFloat(c.degree24H) >= 0 ? 'text-positive' : 'text-negative'}`}>
                        {parseFloat(c.degree24H) >= 0 ? '+' : ''}{c.degree24H}%
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">${c.price || '—'}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex rounded-md border">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1.5 text-xs border-r last:border-0 transition-colors ${
                period === p.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        <span className="text-sm font-medium text-primary">{selectedLabel}</span>
        {loading && <span className="text-xs text-muted-foreground">加载中...</span>}

        <Button size="sm" variant="ghost" onClick={loadKline}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex items-center gap-4 text-xs font-mono">
        <span>开 <span className="text-foreground">{ohlc.o.toFixed(4)}</span></span>
        <span>高 <span className="text-positive">{ohlc.h.toFixed(4)}</span></span>
        <span>低 <span className="text-negative">{ohlc.l.toFixed(4)}</span></span>
        <span>收 <span className="text-foreground">{ohlc.c.toFixed(4)}</span></span>
        <span className={ohlc.change >= 0 ? 'text-positive' : 'text-negative'}>
          {ohlc.change >= 0 ? '+' : ''}{ohlc.change.toFixed(2)}%
        </span>
      </div>

      <Card>
        <CardContent className="p-0">
          <div ref={chartContainerRef} className="w-full" />
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Rankings Tab (4-column: 24h涨幅 / 5分钟涨幅 / 24h跌幅 / 历史累计) ───

function RankingsTab() {
  const [gainers, setGainers] = useState<RankingItem[]>([])
  const [losers, setLosers] = useState<RankingItem[]>([])
  const [gainers5min, setGainers5min] = useState<RankingItem[]>([])
  const [historical, setHistorical] = useState<HistoryScoreItem[]>([])
  const [loading, setLoading] = useState(true)
  const addToast = useToastStore((s) => s.addToast)

  const fetchRankings = useCallback(async () => {
    try {
      const data = await getRankings()
      setGainers(data.gainers || [])
      setLosers(data.losers || [])
      setGainers5min(data.gainers_5min || [])
      setHistorical(data.historical || [])
    } finally {
      setLoading(false)
    }
  }, [])

  useAutoRefresh(fetchRankings, 30000)

  const handleResetHistory = async () => {
    if (!confirm('确认清零历史累计分数？')) return
    try {
      await resetHistoryScores()
      addToast('历史分数已清零', 'success')
      fetchRankings()
    } catch (err: unknown) { addToast(extractError(err, '操作失败'), 'error') }
  }

  if (loading) return <div className="py-8 text-center text-muted-foreground">加载中...</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">数据来源: AiCoin · 每30秒自动刷新 · 历史分数持续累加</p>
        <Button size="sm" variant="ghost" onClick={handleResetHistory} title="清零历史分数">
          <RefreshCw className="h-3.5 w-3.5 mr-1" /> 重置历史
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
        <RankColumn title="涨幅榜 (24h)" items={gainers} field="change_24h" color="positive" />
        <RankColumn title="5分钟涨幅" items={gainers5min} field="change_5min" color="positive" emptyText="等待数据采集 (~5min)" />
        <RankColumn title="跌幅榜 (24h)" items={losers} field="change_24h" color="negative" />
        <HistoryColumn title="历史累计" items={historical} />
      </div>
    </div>
  )
}

function RankColumn({ title, items, field, color, emptyText }: {
  title: string
  items: RankingItem[]
  field: 'change_24h' | 'change_5min'
  color: 'positive' | 'negative'
  emptyText?: string
}) {
  return (
    <Card>
      <CardContent className="p-0">
        <div className={`border-b px-3 py-2 ${color === 'positive' ? 'bg-positive/5' : 'bg-negative/5'}`}>
          <span className="text-sm font-medium">{title}</span>
        </div>
        <div className="divide-y">
          {items.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">{emptyText || '暂无数据'}</div>
          ) : (
            items.map((item, i) => {
              const val = field === 'change_5min' ? (item.change_5min ?? 0) : item.change_24h
              const isTop = i === 0
              return (
                <div key={item.coin_key + i} className={`flex items-center justify-between px-3 py-1.5 text-xs ${isTop ? (color === 'positive' ? 'bg-positive/10' : 'bg-negative/10') : 'hover:bg-accent/30'}`}>
                  <div className="flex items-center gap-2">
                    <span className="w-5 text-center text-muted-foreground">{i + 1}</span>
                    <span className={`font-medium ${isTop ? (color === 'positive' ? 'text-positive' : 'text-negative') : ''}`}>
                      {item.symbol}
                    </span>
                  </div>
                  <span className={`font-mono font-medium ${val >= 0 ? 'text-positive' : 'text-negative'}`}>
                    {val >= 0 ? '+' : ''}{val.toFixed(2)}%
                  </span>
                </div>
              )
            })
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function HistoryColumn({ title, items }: { title: string; items: HistoryScoreItem[] }) {
  const maxScore = items.length > 0 ? items[0].score : 1
  return (
    <Card>
      <CardContent className="p-0">
        <div className="border-b bg-primary/5 px-3 py-2">
          <span className="text-sm font-medium">{title}</span>
        </div>
        <div className="divide-y">
          {items.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">暂无历史数据</div>
          ) : (
            items.map((item, i) => {
              const barWidth = Math.max(8, (item.score / maxScore) * 100)
              return (
                <div key={item.symbol} className={`relative flex items-center justify-between px-3 py-1.5 text-xs ${i === 0 ? 'bg-primary/10' : 'hover:bg-accent/30'}`}>
                  <div className="absolute inset-y-0 left-0 bg-primary/5 transition-all" style={{ width: `${barWidth}%` }} />
                  <div className="relative flex items-center gap-2">
                    <span className="w-5 text-center text-muted-foreground">{i + 1}</span>
                    <span className={`font-medium ${i === 0 ? 'text-primary' : ''}`}>{item.symbol}</span>
                  </div>
                  <span className="relative font-mono font-bold text-primary">{item.score}</span>
                </div>
              )
            })
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Announcements Tab (existing) ───

function AnnouncementsTab() {
  const [articles, setArticles] = useState<AnnouncementItem[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    getAnnouncements()
      .then((data) => {
        if (Array.isArray(data)) setArticles(data)
        else setArticles([])
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(reload, [reload])

  const handleScan = async () => {
    setScanning(true)
    try {
      const res = await checkDelist()
      if (res.count > 0) {
        addToast(`发现 ${res.count} 个下线币种: ${res.found.join(', ')}`, 'success')
      } else {
        addToast('未发现新的下线公告', 'success')
      }
    } catch { addToast('扫描失败', 'error') }
    finally { setScanning(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">币安公告中心 — 自动检测下线/退市公告</p>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={reload}>
            <RefreshCw className="h-4 w-4" /> 刷新
          </Button>
          <Button size="sm" onClick={handleScan} disabled={scanning}>
            <Search className="h-4 w-4" /> {scanning ? '扫描中...' : '扫描下线公告'}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full md:min-w-[600px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">标题</th>
                <th className="px-4 py-3">下线检测</th>
                <th className="px-4 py-3">发布时间</th>
                <th className="px-4 py-3">链接</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : articles.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">暂无公告数据</td></tr>
              ) : (
                articles.map((a) => (
                  <tr key={a.id} className={`border-b last:border-0 hover:bg-accent/50 ${a.is_delist ? 'bg-negative/5' : ''}`}>
                    <td className="px-4 py-3 max-w-md truncate">
                      {a.is_delist && <AlertTriangle className="inline h-3.5 w-3.5 text-negative mr-1" />}
                      {a.title}
                    </td>
                    <td className="px-4 py-3">
                      {a.is_delist ? (
                        <Badge variant="destructive">疑似下线</Badge>
                      ) : (
                        <Badge variant="secondary">正常</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {a.release_date ? new Date(a.release_date).toLocaleString('zh-CN') : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <a href={a.url} target="_blank" rel="noreferrer" className="text-primary hover:underline inline-flex items-center gap-1">
                        查看 <ExternalLink className="h-3 w-3" />
                      </a>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Blacklist Tab (existing) ───

function BlacklistTab() {
  const [items, setItems] = useState<PendingBlacklistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [actionId, setActionId] = useState<number | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    listPendingBlacklist().then(setItems).finally(() => setLoading(false))
  }, [])

  useEffect(reload, [reload])

  const handleConfirm = async (item: PendingBlacklistItem) => {
    if (!confirm(`确认将 ${item.symbol} 加入所有用户的黑名单？`)) return
    setActionId(item.id)
    try {
      const res = await confirmBlacklist(item.id)
      addToast(`${item.symbol} 已分发给 ${res.distributed} 个用户`, 'success')
      reload()
    } catch (err: unknown) { addToast(extractError(err, '操作失败'), 'error') }
    finally { setActionId(null) }
  }

  const handleDismiss = async (item: PendingBlacklistItem) => {
    setActionId(item.id)
    try {
      await dismissPending(item.id)
      addToast('已忽略', 'success')
      reload()
    } catch (err: unknown) { addToast(extractError(err, '操作失败'), 'error') }
    finally { setActionId(null) }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">管理员确认后将自动分发到所有用户的黑名单</p>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full md:min-w-[650px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">币种</th>
                <th className="px-4 py-3">原因</th>
                <th className="px-4 py-3">来源</th>
                <th className="px-4 py-3">检测时间</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">暂无待审核项目</td></tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3 font-medium font-mono">{item.symbol}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground max-w-sm truncate">{item.reason}</td>
                    <td className="px-4 py-3">
                      <Badge variant="outline">{item.source}</Badge>
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" disabled={actionId === item.id} onClick={() => handleConfirm(item)} title="确认并分发">
                          <CheckCircle className="h-3.5 w-3.5 text-positive" />
                        </Button>
                        <Button size="sm" variant="ghost" disabled={actionId === item.id} onClick={() => handleDismiss(item)} title="忽略">
                          <XCircle className="h-3.5 w-3.5 text-negative" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
