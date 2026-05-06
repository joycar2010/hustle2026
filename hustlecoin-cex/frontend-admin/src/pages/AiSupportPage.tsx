import { useEffect, useState, useCallback } from 'react'
import {
  getAiConfig, updateAiConfig,
  getAiStats, listAiConversations, getConversationMessages, getHotQuestions,
  type AiConfigItem, type AiStatsData,
  type AiConversationItem, type AiMessageItem, type HotQuestionItem,
} from '@/api/admin'
import { extractError } from '@/api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import {
  BarChart3, MessageSquare, Settings, Database,
  Save, Search, Eye, X, TrendingUp,
  Users, Zap, ChevronLeft, ChevronRight, RefreshCw,
} from 'lucide-react'

type Tab = 'overview' | 'conversations' | 'knowledge' | 'config'
const SITES = [
  { value: '', label: '全部站点' },
  { value: 'coin', label: '用户端 (coin)' },
  { value: 'coinadmin', label: '管理端 (coinadmin)' },
]

const PROVIDER_MODELS: Record<string, { value: string; label: string }[]> = {
  claude: [
    { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (推荐)' },
    { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
    { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (快速)' },
    { value: 'claude-sonnet-4-5-20250514', label: 'Claude Sonnet 4.5' },
  ],
  openai: [
    { value: 'gpt-5.5', label: 'GPT-5.5 (最新)' },
    { value: 'gpt-5.4', label: 'GPT-5.4' },
    { value: 'gpt-5.4-mini', label: 'GPT-5.4 Mini (快速)' },
    { value: 'gpt-5.3-codex', label: 'GPT-5.3 Codex' },
    { value: 'gpt-5.3-codex-spark', label: 'GPT-5.3 Codex Spark' },
    { value: 'gpt-5.2', label: 'GPT-5.2' },
    { value: 'gpt-4o', label: 'GPT-4o (推荐)' },
    { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
    { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
    { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo (经济)' },
    { value: 'o3-mini', label: 'o3 Mini (推理)' },
  ],
}

export function AiSupportPage() {
  const [tab, setTab] = useState<Tab>('overview')

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">AI 客服</h1>
      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <TabBtn active={tab === 'overview'} onClick={() => setTab('overview')} icon={BarChart3} label="数据概览" />
        <TabBtn active={tab === 'conversations'} onClick={() => setTab('conversations')} icon={MessageSquare} label="对话管理" />
        <TabBtn active={tab === 'knowledge'} onClick={() => setTab('knowledge')} icon={Database} label="知识库配置" />
        <TabBtn active={tab === 'config'} onClick={() => setTab('config')} icon={Settings} label="服务配置" />
      </div>
      {tab === 'overview' && <OverviewTab />}
      {tab === 'conversations' && <ConversationsTab />}
      {tab === 'knowledge' && <KnowledgeTab />}
      {tab === 'config' && <ConfigTab />}
    </div>
  )
}

function TabBtn({ active, onClick, icon: Icon, label }: {
  active: boolean; onClick: () => void; icon: React.ComponentType<{ className?: string }>; label: string
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
        active ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  )
}


// ═══════════════════════════════════════════════════
// Overview Tab — Stats + Daily Trend + Hot Questions
// ═══════════════════════════════════════════════════

function OverviewTab() {
  const [site, setSite] = useState('')
  const [stats, setStats] = useState<AiStatsData | null>(null)
  const [hot, setHot] = useState<HotQuestionItem[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(() => {
    setLoading(true)
    Promise.all([
      getAiStats(site || undefined),
      getHotQuestions(site || undefined),
    ]).then(([s, h]) => {
      setStats(s)
      setHot(h)
    }).finally(() => setLoading(false))
  }, [site])

  useEffect(reload, [reload])

  const maxCount = stats?.daily_trend?.length
    ? Math.max(...stats.daily_trend.map(d => d.count), 1)
    : 1

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <SiteSelector value={site} onChange={setSite} />
        <Button size="sm" variant="ghost" onClick={reload} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> 刷新
        </Button>
      </div>

      {loading && !stats ? (
        <div className="py-12 text-center text-muted-foreground">加载中...</div>
      ) : stats ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard icon={MessageSquare} label="总消息数" value={stats.total_messages} color="text-blue-500" />
            <StatCard icon={Zap} label="今日消息" value={stats.today_messages} color="text-green-500" />
            <StatCard icon={Users} label="活跃用户" value={stats.active_users} color="text-purple-500" />
            <StatCard icon={TrendingUp} label="Token 消耗" value={stats.total_tokens.toLocaleString()} color="text-orange-500" />
          </div>

          <Card>
            <CardHeader><CardTitle className="text-sm">14 天消息趋势</CardTitle></CardHeader>
            <CardContent>
              <div className="flex items-end gap-1" style={{ height: 140 }}>
                {stats.daily_trend.map((d) => (
                  <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                    <span className="text-[10px] text-muted-foreground">{d.count || ''}</span>
                    <div
                      className="w-full rounded-t bg-primary/80 transition-all"
                      style={{ height: `${Math.max((d.count / maxCount) * 100, 2)}%`, minHeight: 2 }}
                    />
                    <span className="text-[10px] text-muted-foreground">{d.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-sm">热门问题 Top 10</CardTitle></CardHeader>
            <CardContent>
              {hot.length === 0 ? (
                <div className="py-4 text-center text-muted-foreground text-sm">暂无数据</div>
              ) : (
                <div className="space-y-2">
                  {hot.map((h, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <span className={`flex h-6 w-6 items-center justify-center rounded text-xs font-bold ${
                        i < 3 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                      }`}>{i + 1}</span>
                      <span className="flex-1 truncate text-sm">{h.question}</span>
                      <Badge variant="outline">{h.count} 次</Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  )
}

function StatCard({ icon: Icon, label, value, color }: {
  icon: React.ComponentType<{ className?: string }>; label: string; value: number | string; color: string
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className={`rounded-lg bg-muted p-2 ${color}`}><Icon className="h-5 w-5" /></div>
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-xl font-bold">{value}</p>
        </div>
      </CardContent>
    </Card>
  )
}


// ═══════════════════════════════════════
// Conversations Tab
// ═══════════════════════════════════════

function ConversationsTab() {
  const [site, setSite] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [items, setItems] = useState<AiConversationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [viewConv, setViewConv] = useState<AiConversationItem | null>(null)
  const pageSize = 20

  const reload = useCallback(() => {
    setLoading(true)
    listAiConversations({ site: site || undefined, page, page_size: pageSize, search: search || undefined })
      .then((r) => { setItems(r.items); setTotal(r.total) })
      .finally(() => setLoading(false))
  }, [site, page, search])

  useEffect(reload, [reload])
  useEffect(() => setPage(1), [site, search])

  const totalPages = Math.ceil(total / pageSize) || 1

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <SiteSelector value={site} onChange={setSite} />
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="搜索对话标题..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span className="text-xs text-muted-foreground">共 {total} 条</span>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-muted-foreground">加载中...</div>
          ) : items.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">暂无对话记录</div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">站点</th>
                  <th className="px-4 py-3">用户</th>
                  <th className="px-4 py-3">标题</th>
                  <th className="px-4 py-3">消息数</th>
                  <th className="px-4 py-3">Token</th>
                  <th className="px-4 py-3">时间</th>
                  <th className="px-4 py-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map(c => (
                  <tr key={c.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3">{c.id}</td>
                    <td className="px-4 py-3"><Badge variant="outline">{c.site}</Badge></td>
                    <td className="px-4 py-3">{c.user_id ?? '-'}</td>
                    <td className="px-4 py-3 max-w-xs truncate">{c.title || '-'}</td>
                    <td className="px-4 py-3">{c.message_count}</td>
                    <td className="px-4 py-3">{c.token_used}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{c.created_at?.slice(0, 16)}</td>
                    <td className="px-4 py-3">
                      <Button size="sm" variant="ghost" onClick={() => setViewConv(c)}>
                        <Eye className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-center gap-2">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm">{page} / {totalPages}</span>
        <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {viewConv && <ConversationDialog conv={viewConv} onClose={() => setViewConv(null)} />}
    </div>
  )
}

function ConversationDialog({ conv, onClose }: { conv: AiConversationItem; onClose: () => void }) {
  const [messages, setMessages] = useState<AiMessageItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getConversationMessages(conv.id).then(setMessages).finally(() => setLoading(false))
  }, [conv.id])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="relative w-[calc(100vw-2rem)] max-w-2xl max-h-[80vh] rounded-lg bg-background shadow-xl flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h3 className="font-medium">对话详情 #{conv.id}</h3>
            <p className="text-xs text-muted-foreground">{conv.title} · {conv.site} · {conv.message_count} 条消息</p>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
        <div className="flex-1 overflow-auto p-4 space-y-3">
          {loading ? (
            <div className="text-center text-muted-foreground py-8">加载中...</div>
          ) : messages.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">无消息</div>
          ) : (
            messages.map(m => (
              <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                  m.role === 'user'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted'
                }`}>
                  <p className="whitespace-pre-wrap">{m.content}</p>
                  <p className="mt-1 text-[10px] opacity-60">{m.created_at?.slice(11, 16)} · {m.token_count} tokens</p>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════
// Knowledge Tab — Per-site system prompt
// ═══════════════════════════════════════

function KnowledgeTab() {
  const [activeSite, setActiveSite] = useState('coin')
  const [config, setConfig] = useState<AiConfigItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hot, setHot] = useState<HotQuestionItem[]>([])
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    Promise.all([
      getAiConfig(activeSite),
      getHotQuestions(activeSite),
    ]).then(([c, h]) => { setConfig(c); setHot(h) })
      .finally(() => setLoading(false))
  }, [activeSite])

  useEffect(reload, [reload])

  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    try {
      await updateAiConfig({ system_prompt: config.system_prompt }, activeSite)
      addToast('知识库已保存', 'success')
    } catch (err: unknown) { addToast(extractError(err, '保存失败'), 'error') }
    finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {[
          { value: 'coin', label: '用户端 (coin)', color: 'bg-blue-500' },
          { value: 'coinadmin', label: '管理端 (coinadmin)', color: 'bg-purple-500' },
        ].map(s => (
          <button
            key={s.value}
            onClick={() => setActiveSite(s.value)}
            className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm transition-colors ${
              activeSite === s.value ? 'border-primary bg-primary/5 font-medium' : 'border-border hover:bg-accent/50'
            }`}
          >
            <span className={`h-2.5 w-2.5 rounded-full ${s.color}`} />
            {s.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="py-12 text-center text-muted-foreground">加载中...</div>
      ) : config ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">System Prompt — {activeSite}</CardTitle>
                  <span className="text-xs text-muted-foreground">{(config.system_prompt || '').length} 字符</span>
                </div>
              </CardHeader>
              <CardContent>
                <textarea
                  className="flex min-h-[400px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
                  value={config.system_prompt}
                  onChange={(e) => setConfig({ ...config, system_prompt: e.target.value })}
                  placeholder="输入该站点的 AI 客服系统提示词..."
                />
                <div className="mt-3 flex justify-end">
                  <Button onClick={handleSave} disabled={saving}>
                    <Save className="h-4 w-4" /> {saving ? '保存中...' : '保存知识库'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader><CardTitle className="text-sm">服务状态</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm">AI 客服</span>
                  <Badge variant={config.is_enabled ? 'success' : 'secondary'}>
                    {config.is_enabled ? '已启用' : '未启用'}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Provider</span>
                  <span className="text-sm">{config.provider}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Model</span>
                  <span className="text-sm">{config.model_name}</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="text-sm">热门问题 ({activeSite})</CardTitle></CardHeader>
              <CardContent>
                {hot.length === 0 ? (
                  <div className="py-4 text-center text-muted-foreground text-xs">暂无数据</div>
                ) : (
                  <div className="space-y-1.5">
                    {hot.slice(0, 5).map((h, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <span className="text-muted-foreground">{i + 1}.</span>
                        <span className="flex-1 truncate">{h.question}</span>
                        <Badge variant="outline" className="text-[10px]">{h.count}</Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  )
}


// ═══════════════════════════════════════
// Config Tab — Per-site service config with dynamic model dropdown
// ═══════════════════════════════════════

function ConfigTab() {
  const [activeSite, setActiveSite] = useState('coin')
  const [config, setConfig] = useState<AiConfigItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    getAiConfig(activeSite).then(setConfig).finally(() => setLoading(false))
  }, [activeSite])

  useEffect(reload, [reload])

  const handleProviderChange = (provider: string) => {
    if (!config) return
    const models = PROVIDER_MODELS[provider] || []
    const defaultModel = models[0]?.value || ''
    setConfig({ ...config, provider, model_name: defaultModel })
  }

  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    try {
      await updateAiConfig({
        provider: config.provider,
        api_key: config.api_key,
        base_url: config.base_url,
        model_name: config.model_name,
        temperature: config.temperature,
        max_tokens: config.max_tokens,
        is_enabled: config.is_enabled,
        rate_limit_per_min: config.rate_limit_per_min,
      }, activeSite)
      addToast('配置已保存', 'success')
    } catch (err: unknown) { addToast(extractError(err, '保存失败'), 'error') }
    finally { setSaving(false) }
  }

  const modelOptions = config ? (PROVIDER_MODELS[config.provider] || []) : []
  const isCustomModel = config ? !modelOptions.some(m => m.value === config.model_name) : false

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {[
          { value: 'coin', label: '用户端 (coin)', color: 'bg-blue-500' },
          { value: 'coinadmin', label: '管理端 (coinadmin)', color: 'bg-purple-500' },
        ].map(s => (
          <button
            key={s.value}
            onClick={() => setActiveSite(s.value)}
            className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm transition-colors ${
              activeSite === s.value ? 'border-primary bg-primary/5 font-medium' : 'border-border hover:bg-accent/50'
            }`}
          >
            <span className={`h-2.5 w-2.5 rounded-full ${s.color}`} />
            {s.label}
          </button>
        ))}
      </div>

      {loading || !config ? (
        <div className="text-muted-foreground py-8 text-center">加载中...</div>
      ) : (
        <Card>
          <CardHeader><CardTitle className="text-sm">AI 服务配置 — {activeSite}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Provider</label>
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                  value={config.provider}
                  onChange={(e) => handleProviderChange(e.target.value)}
                >
                  <option value="claude">Claude (Anthropic)</option>
                  <option value="openai">OpenAI</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">中转地址 (Base URL)</label>
                <Input
                  value={config.base_url || ''}
                  onChange={(e) => setConfig({ ...config, base_url: e.target.value })}
                  placeholder="留空则直连官方 API"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">模型</label>
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                  value={config.model_name}
                  onChange={(e) => setConfig({ ...config, model_name: e.target.value })}
                >
                  {modelOptions.map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                  {isCustomModel && (
                    <option value={config.model_name}>{config.model_name} (自定义)</option>
                  )}
                  <option value="__custom__">自定义模型...</option>
                </select>
                {config.model_name === '__custom__' && (
                  <Input
                    className="mt-1"
                    placeholder="输入模型 ID..."
                    value=""
                    onChange={(e) => setConfig({ ...config, model_name: e.target.value })}
                    autoFocus
                  />
                )}
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">API Key</label>
                <Input
                  type="password"
                  value={config.api_key}
                  onChange={(e) => setConfig({ ...config, api_key: e.target.value })}
                  placeholder="输入 API Key..."
                  autoComplete="off"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Temperature</label>
                <Input type="number" step="0.1" min="0" max="2" value={config.temperature} onChange={(e) => setConfig({ ...config, temperature: parseFloat(e.target.value) || 0.7 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Max Tokens</label>
                <Input type="number" value={config.max_tokens} onChange={(e) => setConfig({ ...config, max_tokens: parseInt(e.target.value) || 2000 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">频率限制 (次/分钟)</label>
                <Input type="number" value={config.rate_limit_per_min} onChange={(e) => setConfig({ ...config, rate_limit_per_min: parseInt(e.target.value) || 10 })} />
              </div>
            </div>

            <div className="flex items-center justify-between border-t pt-4">
              <div className="flex items-center gap-2">
                <label className="text-sm">启用 AI 客服</label>
                <button
                  onClick={() => setConfig({ ...config, is_enabled: !config.is_enabled })}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.is_enabled ? 'bg-primary' : 'bg-muted'}`}
                >
                  <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${config.is_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>
              <Button onClick={handleSave} disabled={saving}>
                <Save className="h-4 w-4" /> {saving ? '保存中...' : '保存配置'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}


// ─── Shared Components ───

function SiteSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select
      className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {SITES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
    </select>
  )
}
