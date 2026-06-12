import { useState, useEffect, useRef, useCallback } from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import { LogOut, User, Menu, X } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useEngineStore } from '@/stores/engineStore'
import { useBalanceStore } from '@/stores/balanceStore'
import { useUiStore } from '@/stores/uiStore'
import { startAllWorkers, stopAllWorkers, pushSymbol } from '@/api/engine'
import { getMasterBalance } from '@/api/accounts'
import { useToastStore } from '@/components/ui/toast'
import { cn, formatNumber } from '@/lib/utils'

// 顶栏「合约账户/保/可」取主账户的 U 本位合约钱包（非子账户汇总）
function useMasterFutures() {
  const [m, setM] = useState({ total: 0, available: 0 })
  useEffect(() => {
    let cancelled = false
    const fetchIt = () => getMasterBalance()
      .then((d) => { if (!cancelled) setM({
        total: parseFloat(d.futures_total_balance || '0'),
        available: parseFloat(d.futures_available || '0'),
      }) })
      .catch(() => {})
    fetchIt()
    const t = setInterval(fetchIt, 30000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])
  return m
}

const navTabs = [
  { to: '/dashboard', label: '主控台' },
  { to: '/rules', label: '规则' },
  { to: '/history', label: '历史' },
  { to: '/accounts', label: '账户' },
  { to: '/spreads', label: '监控' },
  { to: '/blacklist', label: '黑名单' },
  { to: '/coins', label: '币管理' },
]

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  const hh = String(now.getHours()).padStart(2, '0')
  const mi = String(now.getMinutes()).padStart(2, '0')
  const ss = String(now.getSeconds()).padStart(2, '0')
  return <span className="text-xs text-muted-foreground font-mono">{mm}/{dd} {hh}:{mi}:{ss}</span>
}

// ─── Web Audio synth sounds ───

let _audioCtx: AudioContext | null = null
function getAudioCtx() {
  if (!_audioCtx) _audioCtx = new AudioContext()
  return _audioCtx
}

function playSynthSound(key: string) {
  if (key === 'none') return
  try {
    const ctx = getAudioCtx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    gain.gain.value = 0.25
    const now = ctx.currentTime
    switch (key) {
      case 'ding':
        osc.type = 'sine'; osc.frequency.setValueAtTime(880, now); osc.frequency.setValueAtTime(1100, now + 0.1)
        gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4)
        osc.start(now); osc.stop(now + 0.4); break
      case 'success':
        osc.type = 'sine'; osc.frequency.setValueAtTime(523, now); osc.frequency.setValueAtTime(659, now + 0.15); osc.frequency.setValueAtTime(784, now + 0.3)
        gain.gain.exponentialRampToValueAtTime(0.01, now + 0.5)
        osc.start(now); osc.stop(now + 0.5); break
      case 'alert':
        osc.type = 'square'; osc.frequency.setValueAtTime(440, now); osc.frequency.setValueAtTime(880, now + 0.15); osc.frequency.setValueAtTime(440, now + 0.3); osc.frequency.setValueAtTime(880, now + 0.45)
        gain.gain.setValueAtTime(0.15, now); gain.gain.exponentialRampToValueAtTime(0.01, now + 0.6)
        osc.start(now); osc.stop(now + 0.6); break
      case 'error':
        osc.type = 'sawtooth'; osc.frequency.setValueAtTime(200, now); osc.frequency.linearRampToValueAtTime(100, now + 0.5)
        gain.gain.setValueAtTime(0.15, now); gain.gain.exponentialRampToValueAtTime(0.01, now + 0.5)
        osc.start(now); osc.stop(now + 0.5); break
      case 'chime':
        osc.type = 'sine'; osc.frequency.setValueAtTime(1047, now); osc.frequency.setValueAtTime(1319, now + 0.1); osc.frequency.setValueAtTime(1568, now + 0.2)
        gain.gain.exponentialRampToValueAtTime(0.01, now + 0.6)
        osc.start(now); osc.stop(now + 0.6); break
    }
  } catch { /* audio not available */ }
}

// ─── Marquee notification bar ───

interface MarqueeItem {
  id: number
  title: string
  content: string
  color: string
  blink: boolean
  sound: string
  ts: number
}

let _marqueeId = 0
const MARQUEE_TTL = 60_000

function NotificationMarquee() {
  const [items, setItems] = useState<MarqueeItem[]>([])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail
      if (!d) return
      const item: MarqueeItem = {
        id: ++_marqueeId,
        title: d.title || '',
        content: d.content || '',
        color: d.color || '#3b82f6',
        blink: d.blink || false,
        sound: d.sound || 'none',
        ts: Date.now(),
      }
      setItems(prev => [...prev.slice(-19), item])
      playSynthSound(item.sound)
    }
    window.addEventListener('ws:notification', handler)
    return () => window.removeEventListener('ws:notification', handler)
  }, [])

  useEffect(() => {
    const t = setInterval(() => {
      setItems(prev => prev.filter(i => Date.now() - i.ts < MARQUEE_TTL))
    }, 5000)
    return () => clearInterval(t)
  }, [])

  if (items.length === 0) return null

  return (
    <div className="flex-1 min-w-0 overflow-hidden h-6 flex items-center relative mx-1">
      <div className="marquee-track whitespace-nowrap">
        {items.map(item => (
          <span key={item.id} className={cn('inline-block mx-3 text-[11px] font-medium', item.blink && 'animate-pulse')} style={{ color: item.color }}>
            [{item.title}] {item.content}
          </span>
        ))}
      </div>
      <style>{`
        .marquee-track {
          display: inline-block;
          animation: marquee-scroll ${Math.max(15, items.length * 8)}s linear infinite;
        }
        @keyframes marquee-scroll {
          0% { transform: translateX(100%); }
          100% { transform: translateX(-100%); }
        }
      `}</style>
    </div>
  )
}

// ─── Mobile Nav Drawer ───

function MobileNavDrawer() {
  const mobileNavOpen = useUiStore((s) => s.mobileNavOpen)
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen)
  const logout = useAuthStore((s) => s.logout)
  const username = useAuthStore((s) => s.username)
  const balanceSummary = useBalanceStore((s) => s.summary)
  const masterFut = useMasterFutures()
  const wsLatency = useBalanceStore((s) => s.wsLatency)
  const workers = useEngineStore((s) => s.workers)
  const engineStatus = useEngineStore((s) => s.status)
  const isRunning = engineStatus === 'RUNNING'
  const runningCount = workers.filter((w) => w.status === 'RUNNING').length
  const posCount = balanceSummary.positionCount
  const totalContracts = balanceSummary.totalContracts
  const navigate = useNavigate()
  const location = useLocation()

  const [pushInput, setPushInput] = useState('')
  const [pushing, setPushing] = useState(false)

  const handlePush = useCallback(async () => {
    const sym = pushInput.trim().toUpperCase()
    if (!sym) return
    setPushing(true)
    try {
      await pushSymbol(sym)
      setPushInput('')
      window.dispatchEvent(new CustomEvent('pushed:refresh'))
    } catch { /* ignore */ }
    setPushing(false)
  }, [pushInput])

  if (!mobileNavOpen) return null

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div className="absolute inset-0 bg-black/60" onClick={() => setMobileNavOpen(false)} />
      <div className="absolute right-0 top-0 h-full w-[280px] bg-[#0d0d12] border-l border-border flex flex-col overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-3 border-b border-border shrink-0">
          <span className="text-sm font-medium text-foreground">导航菜单</span>
          <button onClick={() => setMobileNavOpen(false)} className="p-1 rounded hover:bg-accent">
            <X size={18} className="text-muted-foreground" />
          </button>
        </div>

        {/* Nav links */}
        <nav className="p-2 space-y-0.5 border-b border-border">
          {navTabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              onClick={() => setMobileNavOpen(false)}
              className={cn(
                'flex items-center px-3 py-2.5 rounded text-sm transition-colors',
                location.pathname === tab.to
                  ? 'bg-primary/15 text-primary font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent',
              )}
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>

        {/* Stats */}
        <div className="p-3 border-b border-border space-y-2">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wider">账户概要</div>
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="text-muted-foreground">合约账户 <span className="text-foreground font-mono">{formatNumber(masterFut.total, 0)}</span></div>
            <div className="text-muted-foreground">保证金 <span className="text-foreground font-mono">{formatNumber(masterFut.total - masterFut.available, 0)}</span></div>
            <div className="text-muted-foreground">可用 <span className="text-foreground font-mono">{formatNumber(masterFut.available, 0)}</span></div>
            <div className="text-muted-foreground">合约 <span className="text-primary">{posCount}</span>/<span>{totalContracts}</span></div>
            <div className="text-muted-foreground">引擎 <span className={isRunning ? 'text-positive' : 'text-negative'}>{runningCount}</span>/{workers.length}</div>
            {wsLatency > 0 && (
              <div className="text-muted-foreground">延迟 <span className={cn('font-mono', wsLatency > 500 ? 'text-negative' : 'text-positive')}>{wsLatency}</span>ms</div>
            )}
          </div>
          <Clock />
        </div>

        {/* Push symbol */}
        <div className="p-3 border-b border-border">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">手动推送</div>
          <div className="flex items-center gap-1.5">
            <input
              value={pushInput}
              onChange={(e) => setPushInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handlePush() }}
              placeholder="币种名称"
              className="flex-1 bg-[#1a1a22] border border-border rounded px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
            />
            <button
              onClick={handlePush}
              disabled={pushing || !pushInput.trim()}
              className="px-2.5 py-1.5 bg-primary/20 text-primary rounded text-xs hover:bg-primary/30 disabled:opacity-40 whitespace-nowrap"
            >
              推送
            </button>
          </div>
        </div>

        {/* User + logout */}
        <div className="mt-auto p-3 border-t border-border space-y-1">
          <button
            onClick={() => { navigate('/settings'); setMobileNavOpen(false) }}
            className="flex w-full items-center gap-2 px-3 py-2.5 rounded text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <User size={14} />
            <span>{username || 'admin'}</span>
          </button>
          <button
            onClick={logout}
            className="flex w-full items-center gap-2 px-3 py-2.5 rounded text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <LogOut size={14} />
            <span>退出登录</span>
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main TopBar ───

export function OwlTopBar() {
  const logout = useAuthStore((s) => s.logout)
  const username = useAuthStore((s) => s.username)
  const engineStatus = useEngineStore((s) => s.status)
  const workers = useEngineStore((s) => s.workers)
  const balanceSummary = useBalanceStore((s) => s.summary)
  const masterFut = useMasterFutures()
  const wsLatency = useBalanceStore((s) => s.wsLatency)
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen)
  const addToast = useToastStore((s) => s.addToast)
  const [pushInput, setPushInput] = useState('')
  const [toggling, setToggling] = useState(false)
  const [pushing, setPushing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const isRunning = engineStatus === 'RUNNING'

  const fetchWorkers = useEngineStore((s) => s.fetchWorkers)

  const handleToggleEngine = useCallback(async () => {
    setToggling(true)
    try {
      if (isRunning) {
        await stopAllWorkers()
        addToast('停止挂单信号已发送', 'success')
      } else {
        await startAllWorkers()
        addToast('启动挂单信号已发送', 'success')
      }
      // 引擎经 Redis 异步处理启停(~3s 生效),轮询回读直到按钮状态翻转或超时
      const target = isRunning ? 'STOPPED' : 'RUNNING'
      for (let i = 0; i < 8; i++) {
        await new Promise((r) => setTimeout(r, 1500))
        await fetchWorkers()
        if (useEngineStore.getState().status === target) break
      }
    } catch {
      addToast('操作失败，请重试', 'error')
    }
    setToggling(false)
  }, [isRunning, addToast, fetchWorkers])

  const handlePush = useCallback(async () => {
    const sym = pushInput.trim().toUpperCase()
    if (!sym) return
    setPushing(true)
    try {
      await pushSymbol(sym)
      setPushInput('')
      window.dispatchEvent(new CustomEvent('pushed:refresh'))
    } catch { /* ignore */ }
    setPushing(false)
  }, [pushInput])

  const handlePushKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handlePush()
  }, [handlePush])

  const runningCount = workers.filter((w) => w.status === 'RUNNING').length
  const posCount = balanceSummary.positionCount
  const totalContracts = balanceSummary.totalContracts

  return (
    <>
      <header className="flex h-10 items-center border-b border-border bg-[#0d0d12] px-3 gap-2 shrink-0 select-none">
        {/* Logo + engine toggle */}
        <div className="flex items-center gap-1.5 shrink-0">
          <img src="/assets/logo.png" alt="HustleCoin" className="w-5 h-5 object-contain" />
        </div>

        <button
          onClick={handleToggleEngine}
          disabled={toggling}
          className={cn(
            'px-2 py-0.5 rounded text-[11px] font-medium transition-colors whitespace-nowrap shrink-0',
            isRunning
              ? 'bg-positive/20 text-positive hover:bg-positive/30'
              : 'bg-negative/20 text-negative hover:bg-negative/30',
            toggling && 'opacity-50 cursor-not-allowed',
          )}
        >
          {toggling ? '处理中…' : (isRunning ? '停止挂单' : '启动挂单')}
        </button>

        {/* Push symbol input — desktop only */}
        <div className="hidden md:flex items-center gap-1 shrink-0">
          <input
            ref={inputRef}
            value={pushInput}
            onChange={(e) => setPushInput(e.target.value)}
            onKeyDown={handlePushKeyDown}
            placeholder="推送币种"
            className="w-20 bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
          />
          <button
            onClick={handlePush}
            disabled={pushing || !pushInput.trim()}
            className="px-1.5 py-0.5 bg-primary/20 text-primary rounded text-[11px] hover:bg-primary/30 disabled:opacity-40 whitespace-nowrap"
          >
            手动推送
          </button>
        </div>

        {/* Marquee notification bar — desktop only, fills remaining space */}
        <div className="hidden md:flex flex-1 min-w-0">
          <NotificationMarquee />
        </div>

        {/* Mobile spacer */}
        <div className="flex-1 md:hidden" />

        {/* Account summary stats — desktop only */}
        <div className="hidden md:flex items-center gap-3 text-[11px] text-muted-foreground shrink-0">
          <span>
            合约账户{' '}
            <span className="text-foreground font-mono">{formatNumber(masterFut.total, 0)}</span>
          </span>
          <span>
            保{' '}
            <span className="text-foreground font-mono">{formatNumber(masterFut.total - masterFut.available, 0)}</span>
          </span>
          <span>
            可{' '}
            <span className="text-foreground font-mono">{formatNumber(masterFut.available, 0)}</span>
          </span>
          <Clock />
          <span>
            合约{' '}
            <span className="text-primary">{posCount}</span>
            /<span className="text-muted-foreground">{totalContracts}</span>
          </span>
          <span>
            引擎{' '}
            <span className={isRunning ? 'text-positive' : 'text-negative'}>{runningCount}</span>
            /{workers.length}
          </span>
          {wsLatency > 0 && (
            <span>
              延迟{' '}
              <span className={cn('font-mono', wsLatency > 500 ? 'text-negative' : 'text-positive')}>
                {wsLatency}
              </span>
              ms
            </span>
          )}
        </div>

        {/* Nav tabs — desktop only */}
        <nav className="hidden md:flex items-center gap-0.5 ml-3 shrink-0">
          {navTabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) =>
                cn(
                  'px-2.5 py-1 rounded text-[11px] transition-colors whitespace-nowrap',
                  isActive
                    ? 'bg-primary/15 text-primary font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent',
                )
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>

        {/* User status — desktop only */}
        <div className="hidden md:flex items-center gap-1 ml-2 shrink-0">
          <button
            onClick={() => navigate('/settings')}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            title="用户设置"
          >
            <User size={12} />
            <span>{username || 'admin'}</span>
          </button>
          <button
            onClick={logout}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent"
            title="退出登录"
          >
            <LogOut size={13} />
          </button>
        </div>

        {/* Hamburger button — mobile only */}
        <button
          onClick={() => setMobileNavOpen(true)}
          className="md:hidden p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          <Menu size={18} />
        </button>
      </header>

      {/* Mobile drawer */}
      <MobileNavDrawer />
    </>
  )
}
