import { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { useSpreadStore, type SpreadData } from '@/stores/spreadStore'
import { useMarketDataStore } from '@/stores/marketDataStore'
import { getSpreads } from '@/api/spreads'
import { pushSymbol, getPushedSymbols } from '@/api/engine'
import { getCoins } from '@/api/coins'
import { getGlobalRules, getSymbolRules, addToBlacklist } from '@/api/rules'
import { getKlineData, searchCoin, getRankings, type CoinSearchItem, type RankingItem, type HistoryScoreItem } from '@/api/market'
import { Card, CardContent } from '@/components/ui/card'
import { useToastStore } from '@/components/ui/toast'
import { createChart, type IChartApi, CandlestickSeries, HistogramSeries, ColorType, type UTCTimestamp } from 'lightweight-charts'
import { MoreVertical } from 'lucide-react'

// Surface real HTTP status/detail so failures are diagnosable instead of silently empty.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function errMsg(e: any): string {
  const status = e?.response?.status
  const detail = e?.response?.data?.detail ?? e?.message
  return status ? `${status}${detail ? ': ' + detail : ''}` : (detail || '未知错误')
}

type Tab = 'spreads' | 'kline' | 'rankings'

// 24h 成交量(USDT)简显: 亿/万
function fmtVol(v: number | undefined): string {
  if (!v || v <= 0) return '-'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

export function SpreadsPage() {
  const [tab, setTab] = useState<Tab>('spreads')

  const tabCls = (t: Tab) =>
    `border-b-2 px-3 py-1.5 text-xs transition-colors ${
      tab === t ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
    }`

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1 border-b border-border">
        <button onClick={() => setTab('spreads')} className={tabCls('spreads')}>利差监控</button>
        <button onClick={() => setTab('kline')} className={tabCls('kline')}>K线查询</button>
        <button onClick={() => setTab('rankings')} className={tabCls('rankings')}>涨幅榜</button>
      </div>

      {tab === 'spreads' && <SpreadsTab />}
      {tab === 'kline' && <KlineTab />}
      {tab === 'rankings' && <RankingsTab />}
    </div>
  )
}

// ─── Spreads Tab (original SpreadsPage content) ───

// 单腿超过此时长未更新视为死币/冻结 → 不显示(用 store 内最新 ts 作参照,免客户端时钟偏差)
const SPREAD_STALE_DEFAULT_SEC = 300   // 利差监控新鲜阈值默认值(秒);实际值由 admin「系统后端规则」spread_stale_sec 配

function SpreadsTab() {
  const spreads = useSpreadStore((s) => s.spreads)
  const lastUpdateTs = useSpreadStore((s) => s.lastUpdateTs)
  const setBulk = useSpreadStore((s) => s.setBulk)
  const marketData = useMarketDataStore((s) => s.marketData)
  const [search, setSearch] = useState('')
  const [globalRules, setGlobalRules] = useState<Record<string, unknown>>({})
  const [symbolRulesMap, setSymbolRulesMap] = useState<Map<string, { open: number; close: number }>>(new Map())
  const [pushedSymbols, setPushedSymbols] = useState<Set<string>>(new Set())
  const [minSpread, setMinSpread] = useState(0)
  const [minVol, setMinVol] = useState(0)   // 24h 成交量门槛(USDT),过滤低流动性薄盘
  const [volMap, setVolMap] = useState<Map<string, number>>(new Map())
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; symbol: string } | null>(null)

  useEffect(() => {
    getSpreads().then((data: SpreadData[]) => setBulk(data)).catch(() => {})
    getCoins().then((coins) => setVolMap(new Map(coins.map((c) => [c.symbol, parseFloat(c.volume_24h || '0') || 0])))).catch(() => {})
    getGlobalRules().then(setGlobalRules).catch(() => {})
    getSymbolRules().then((resp: { items?: Array<{ symbol: string; effective_open_spread: number | string | null; effective_close_spread: number | string | null }> }) => {
      const m = new Map<string, { open: number; close: number }>()
      for (const r of resp.items || []) {
        m.set(r.symbol, {
          open: parseFloat(String(r.effective_open_spread ?? 0)),
          close: parseFloat(String(r.effective_close_spread ?? 0)),
        })
      }
      setSymbolRulesMap(m)
    }).catch(() => {})
    getPushedSymbols().then((d) => setPushedSymbols(new Set(d.pushed_symbols || []))).catch(() => {})
  }, [setBulk])

  // 定时整表刷新:setBulk 现为整表替换,周期性拉取可剪掉引擎已停发的死币
  useEffect(() => {
    const t = setInterval(() => {
      getSpreads().then((data: SpreadData[]) => setBulk(data)).catch(() => {})
    }, 20_000)
    return () => clearInterval(t)
  }, [setBulk])

  const openSpread = parseFloat(String(globalRules.open_spread ?? 0.8))
  const closeSpread = parseFloat(String(globalRules.close_spread ?? 0.2))
  // 利差监控新鲜阈值(秒→ms),由 admin「系统后端规则」spread_stale_sec 配,缺省 300s
  const staleMs = (parseInt(String(globalRules.spread_stale_sec ?? SPREAD_STALE_DEFAULT_SEC)) || SPREAD_STALE_DEFAULT_SEC) * 1000

  const totalCount = spreads.size

  const filtered = useMemo(() => {
    const items = Array.from(spreads.values())
    const q = search.toUpperCase()
    let result = q ? items.filter((s) => s.symbol.includes(q)) : items
    // 剔除死币/冻结:某币 ts 比全表最新 ts 落后超过阈值 → 引擎已停发(退市/盘口冻结),不显示陈旧值
    if (lastUpdateTs > 0) {
      result = result.filter((s) => lastUpdateTs - s.ts <= staleMs)
    }
    if (minSpread > 0) {
      result = result.filter((s) => Math.abs(s.spread_short) >= minSpread)
    }
    if (minVol > 0) {
      result = result.filter((s) => (volMap.get(s.symbol) ?? 0) >= minVol)
    }
    result.sort((a, b) => b.spread_short - a.spread_short)   // 按开仓值(spread_short)降序,与参照系统一致
    return result
  }, [spreads, search, minSpread, minVol, volMap, lastUpdateTs, staleMs])

  const handlePush = useCallback(async (symbol: string) => {
    try {
      await pushSymbol(symbol)
      setPushedSymbols((prev) => new Set([...prev, symbol]))
      window.dispatchEvent(new CustomEvent('pushed:refresh'))
    } catch { /* ignore */ }
    setContextMenu(null)
  }, [])

  const handleBlacklist = useCallback(async (symbol: string) => {
    if (!confirm(`确认将 "${symbol}" 加入黑名单？加入后不再自动推送。`)) {
      setContextMenu(null)
      return
    }
    try {
      await addToBlacklist(symbol)
    } catch { /* ignore */ }
    setContextMenu(null)
  }, [])

  useEffect(() => {
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索..."
          className="w-32 bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
        />
        <select
          value={minSpread}
          onChange={(e) => setMinSpread(parseFloat(e.target.value))}
          className="bg-[#1a1a22] border border-border rounded px-1.5 py-1 text-xs text-foreground focus:outline-none focus:border-primary"
        >
          <option value={0}>全部利差</option>
          <option value={0.1}>&gt; 0.1%</option>
          <option value={0.3}>&gt; 0.3%</option>
          <option value={0.5}>&gt; 0.5%</option>
          <option value={0.8}>&gt; 0.8%</option>
          <option value={1.0}>&gt; 1.0%</option>
          <option value={2.0}>&gt; 2.0%</option>
        </select>
        <select
          value={minVol}
          onChange={(e) => setMinVol(parseFloat(e.target.value))}
          className="bg-[#1a1a22] border border-border rounded px-1.5 py-1 text-xs text-foreground focus:outline-none focus:border-primary"
          title="按 24h 成交量过滤低流动性薄盘(点差易虚高/glitch)"
        >
          <option value={0}>全部成交量</option>
          <option value={1000000}>&gt; 100万</option>
          <option value={5000000}>&gt; 500万</option>
          <option value={10000000}>&gt; 1000万</option>
          <option value={50000000}>&gt; 5000万</option>
          <option value={100000000}>&gt; 1亿</option>
        </select>
        <span className="text-[11px] text-muted-foreground ml-auto">{filtered.length} / {totalCount} 币种</span>
      </div>

      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full min-w-[600px] text-[11px]">
          <thead>
            <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
              <th className="px-2 py-1.5 text-left font-medium">做空</th>
              <th className="px-2 py-1.5 text-left font-medium">做多</th>
              <th className="px-2 py-1.5 text-left font-medium">币种</th>
              <th className="px-2 py-1.5 text-right font-medium">当期</th>
              <th className="px-2 py-1.5 text-right font-medium">开仓</th>
              <th className="px-2 py-1.5 text-right font-medium">清仓</th>
              <th className="px-2 py-1.5 text-right font-medium">24h量</th>
              <th className="px-2 py-1.5 text-right font-medium">决</th>
              <th className="px-2 py-1.5 text-center font-medium">推送</th>
              <th className="px-1 py-1.5 font-medium md:hidden w-8"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => {
              const sr = symbolRulesMap.get(s.symbol)
              const symOpen = sr ? sr.open : openSpread
              const symClose = sr ? sr.close : closeSpread
              const isPushed = pushedSymbols.has(s.symbol)
              const mi = marketData.get(s.symbol)
              // 开仓/平仓以合约 mark 为锚(mark 缺失用合约 mid 兜底):开仓=公允基差,平仓=开仓+一来回滑点
              // 开仓/清仓 口径对齐 coinmini 参照源(server_proxy.py / gui.py):
              // 开仓 =(spot_bid−fut_ask)/fut_ask×100(=引擎 spread_short:卖现货吃bid+买合约吃ask)
              // 清仓 = |(fut_bid−spot_ask)/fut_bid×100|(平仓侧基差取绝对值,gui.py abs(cv))
              const openActual = s.spread_short
              const closeActual = s.fut_bid !== 0 ? Math.abs((s.fut_bid - s.spot_ask) / s.fut_bid * 100) : 0
              // 当期 = 当期资金费率(premiumIndex.lastFundingRate ×100)
              const funding = mi ? mi.funding_rate * 100 : null
              return (
                <tr
                  key={s.symbol}
                  className="border-b border-border/30 hover:bg-accent/20 cursor-pointer"
                  onContextMenu={(e) => {
                    e.preventDefault()
                    setContextMenu({ x: e.clientX, y: e.clientY, symbol: s.symbol })
                  }}
                >
                  <td className="px-2 py-1 text-muted-foreground whitespace-nowrap">币安现货</td>
                  <td className="px-2 py-1 text-muted-foreground whitespace-nowrap">币安期货</td>
                  <td className="px-2 py-1 font-medium whitespace-nowrap">{s.symbol.replace('USDT', '')}</td>
                  <td className="px-2 py-1 text-right tabular-nums font-mono">
                    {funding !== null ? (
                      <span className={funding >= 0 ? 'text-positive' : 'text-negative'}>{funding.toFixed(2)}</span>
                    ) : <span className="text-muted-foreground">-</span>}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums font-mono">
                    <span className={openActual >= symOpen ? 'text-positive' : 'text-foreground'}>{openActual.toFixed(2)}</span>
                    <span className="text-muted-foreground text-[9px] ml-0.5">/{symOpen.toFixed(2)}</span>
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums font-mono">
                    <span className={closeActual <= symClose ? 'text-positive' : 'text-foreground'}>{closeActual.toFixed(2)}</span>
                    <span className="text-muted-foreground text-[9px] ml-0.5">/{symClose.toFixed(2)}</span>
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums font-mono text-muted-foreground">
                    {fmtVol(volMap.get(s.symbol))}
                  </td>
                  <td className="px-2 py-1 text-right font-medium text-positive">
                    期多
                  </td>
                  <td className="px-2 py-1 text-center">
                    {isPushed ? (
                      <span className="text-positive">●</span>
                    ) : (
                      <span className="text-muted-foreground">○</span>
                    )}
                  </td>
                  <td className="px-1 py-1 text-center md:hidden">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        const rect = e.currentTarget.getBoundingClientRect()
                        setContextMenu({ x: rect.left - 120, y: rect.bottom + 4, symbol: s.symbol })
                      }}
                      className="p-0.5 rounded hover:bg-accent/50"
                    >
                      <MoreVertical size={14} className="text-muted-foreground" />
                    </button>
                  </td>
                </tr>
              )
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={10} className="py-8 text-center text-muted-foreground text-xs">
                  {search ? '未找到匹配币种' : '等待利差数据...'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {contextMenu && (
        <div
          className="fixed z-50 min-w-[160px] rounded border border-border bg-[#141420] py-1 shadow-xl"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-3 py-1 text-[10px] text-muted-foreground border-b border-border/50 mb-0.5">
            {contextMenu.symbol}
          </div>
          {pushedSymbols.has(contextMenu.symbol) ? (
            <div className="px-3 py-1 text-[11px] text-muted-foreground">已推送</div>
          ) : (
            <button
              className="flex w-full items-center px-3 py-1 text-[11px] hover:bg-accent/50 transition-colors text-left"
              onClick={() => handlePush(contextMenu.symbol)}
            >
              推送到借币列表
            </button>
          )}
          <div className="my-0.5 border-t border-border/50" />
          <button
            className="flex w-full items-center px-3 py-1 text-[11px] hover:bg-accent/50 transition-colors text-left text-negative"
            onClick={() => handleBlacklist(contextMenu.symbol)}
          >
            加入黑名单
          </button>
        </div>
      )}
    </div>
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
      height: 440,
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
        chart.applyOptions({ width: chartContainerRef.current.clientWidth })
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
    } catch (e) {
      addToast(`K线加载失败: ${errMsg(e)}`, 'error')
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
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <input
            className="w-44 bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
            placeholder="搜索币种 (BTC, ETH...)"
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            onFocus={() => results.length > 0 && setShowSearch(true)}
            onBlur={() => setTimeout(() => setShowSearch(false), 200)}
          />
          {showSearch && results.length > 0 && (
            <div className="absolute z-50 mt-1 w-72 max-h-60 overflow-y-auto rounded border border-border bg-[#141420] shadow-lg">
              {results.map((c, i) => (
                <button
                  key={c.coinKey + i}
                  className="flex w-full items-center justify-between px-3 py-1.5 text-xs hover:bg-accent/50 text-left"
                  onMouseDown={() => selectCoin(c)}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{c.coinShow || c.coinName}</span>
                    {c.degree24H && c.degree24H !== '-' && (
                      <span className={`text-[10px] ${parseFloat(c.degree24H) >= 0 ? 'text-positive' : 'text-negative'}`}>
                        {parseFloat(c.degree24H) >= 0 ? '+' : ''}{c.degree24H}%
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground">${c.price || '—'}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex rounded border border-border">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-2 py-1 text-[10px] border-r border-border last:border-0 transition-colors ${
                period === p.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent/50'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        <span className="text-xs font-medium text-primary">{selectedLabel}</span>
        {loading && <span className="text-[10px] text-muted-foreground">加载中...</span>}

        <button onClick={loadKline} className="text-muted-foreground hover:text-foreground text-xs px-1">⟳</button>
      </div>

      <div className="flex items-center gap-3 text-[10px] font-mono">
        <span>开 <span className="text-foreground">{ohlc.o.toFixed(4)}</span></span>
        <span>高 <span className="text-positive">{ohlc.h.toFixed(4)}</span></span>
        <span>低 <span className="text-negative">{ohlc.l.toFixed(4)}</span></span>
        <span>收 <span className="text-foreground">{ohlc.c.toFixed(4)}</span></span>
        <span className={ohlc.change >= 0 ? 'text-positive' : 'text-negative'}>
          {ohlc.change >= 0 ? '+' : ''}{ohlc.change.toFixed(2)}%
        </span>
      </div>

      <div className="rounded border border-border overflow-hidden">
        <div ref={chartContainerRef} className="w-full" />
      </div>
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
  const [err, setErr] = useState<string | null>(null)

  const fetchRankings = useCallback(() => {
    getRankings()
      .then((data) => {
        setErr(null)
        setGainers(data.gainers || [])
        setLosers(data.losers || [])
        setGainers5min(data.gainers_5min || [])
        setHistorical(data.historical || [])
      })
      .catch((e) => setErr(errMsg(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchRankings()
    const timer = setInterval(fetchRankings, 30000)
    return () => clearInterval(timer)
  }, [fetchRankings])

  if (loading) return <div className="py-8 text-center text-muted-foreground text-xs">加载中...</div>

  return (
    <div className="space-y-3">
      {err && <div className="rounded border border-negative/40 bg-negative/10 px-3 py-1.5 text-[11px] text-negative">涨幅榜加载失败: {err}</div>}
      <p className="text-[10px] text-muted-foreground">数据来源: AiCoin · 每30秒自动刷新 · 历史分数持续累加</p>

      <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 xl:grid-cols-4">
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
        <div className={`border-b px-3 py-1.5 ${color === 'positive' ? 'bg-positive/5' : 'bg-negative/5'}`}>
          <span className="text-xs font-medium">{title}</span>
        </div>
        <div className="divide-y divide-border/30">
          {items.length === 0 ? (
            <div className="px-3 py-4 text-center text-[10px] text-muted-foreground">{emptyText || '暂无数据'}</div>
          ) : (
            items.map((item, i) => {
              const val = field === 'change_5min' ? (item.change_5min ?? 0) : item.change_24h
              const isTop = i === 0
              return (
                <div key={item.coin_key + i} className={`flex items-center justify-between px-3 py-1 text-[11px] ${isTop ? (color === 'positive' ? 'bg-positive/10' : 'bg-negative/10') : 'hover:bg-accent/20'}`}>
                  <div className="flex items-center gap-1.5">
                    <span className="w-4 text-center text-[10px] text-muted-foreground">{i + 1}</span>
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
        <div className="border-b bg-primary/5 px-3 py-1.5">
          <span className="text-xs font-medium">{title}</span>
        </div>
        <div className="divide-y divide-border/30">
          {items.length === 0 ? (
            <div className="px-3 py-4 text-center text-[10px] text-muted-foreground">暂无历史数据</div>
          ) : (
            items.map((item, i) => {
              const barWidth = Math.max(8, (item.score / maxScore) * 100)
              return (
                <div key={item.symbol} className={`relative flex items-center justify-between px-3 py-1 text-[11px] ${i === 0 ? 'bg-primary/10' : 'hover:bg-accent/20'}`}>
                  <div className="absolute inset-y-0 left-0 bg-primary/5 transition-all" style={{ width: `${barWidth}%` }} />
                  <div className="relative flex items-center gap-1.5">
                    <span className="w-4 text-center text-[10px] text-muted-foreground">{i + 1}</span>
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
