import { useState, useEffect } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { getIpWhitelist, updateIpWhitelist, removeIpFromWhitelist, getServerIp } from '@/api/accounts'

interface IpWhitelistPanelProps {
  accountId: number
  accountNote: string
  onClose: () => void
}

interface IpRestrictionData {
  ipRestrict: boolean
  ipList: Array<{ ip: string }>
}

export function IpWhitelistPanel({ accountId, accountNote, onClose }: IpWhitelistPanelProps) {
  const [restriction, setRestriction] = useState<IpRestrictionData | null>(null)
  const [loading, setLoading] = useState(true)
  const [newIp, setNewIp] = useState('')
  const [stagedIps, setStagedIps] = useState<string[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [serverIp, setServerIp] = useState('')
  const [loadingServerIp, setLoadingServerIp] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const data = await getIpWhitelist(accountId)
      setRestriction(data)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || '获取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [accountId])

  useEffect(() => {
    setLoadingServerIp(true)
    getServerIp()
      .then((d) => setServerIp(d.ip || ''))
      .catch(() => {})
      .finally(() => setLoadingServerIp(false))
  }, [])

  const addServerIp = () => {
    if (!serverIp) return
    const existing = restriction?.ipList?.map(i => i.ip) || []
    if (existing.includes(serverIp) || stagedIps.includes(serverIp)) {
      setError('服务器 IP 已在列表中')
      return
    }
    setStagedIps(prev => [...prev, serverIp])
    setError('')
  }

  const addToStaging = () => {
    const ip = newIp.trim()
    if (!ip) return
    const ipv4 = /^(\d{1,3}\.){3}\d{1,3}(\/\d{1,2})?$/
    if (!ipv4.test(ip)) {
      setError('请输入有效的 IPv4 地址')
      return
    }
    if (stagedIps.includes(ip)) return
    const existing = restriction?.ipList?.map(i => i.ip) || []
    if (existing.includes(ip)) {
      setError('该 IP 已在白名单中')
      return
    }
    setStagedIps(prev => [...prev, ip])
    setNewIp('')
    setError('')
  }

  const removeFromStaging = (ip: string) => {
    setStagedIps(prev => prev.filter(i => i !== ip))
  }

  const commitStaged = async () => {
    if (stagedIps.length === 0) return
    setSaving(true)
    setError('')
    try {
      await updateIpWhitelist(accountId, {
        ip_restrict: true,
        ip_list: stagedIps,
      })
      setStagedIps([])
      await fetchData()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || '提交失败')
    } finally {
      setSaving(false)
    }
  }

  const handleRemoveIp = async (ip: string) => {
    if (!confirm(`确认移除 IP ${ip}?`)) return
    try {
      await removeIpFromWhitelist(accountId, ip)
      await fetchData()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || '移除失败')
    }
  }

  const existingIps = restriction?.ipList?.map(i => i.ip) || []

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50">
      <Card className="w-[calc(100vw-2rem)] max-w-[480px] max-h-[80vh] overflow-y-auto">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">IP 白名单 — {accountNote}</CardTitle>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground">✕</button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <p className="text-xs text-muted-foreground py-4 text-center">加载中...</p>
          ) : (
            <>
              <div>
                <p className="text-[10px] text-muted-foreground mb-1">
                  IP 限制状态: {restriction?.ipRestrict ? (
                    <Badge className="bg-positive/20 text-positive text-[9px]">已启用</Badge>
                  ) : (
                    <Badge className="bg-negative/20 text-negative text-[9px]">未启用</Badge>
                  )}
                </p>
              </div>

              <div>
                <p className="text-[10px] text-muted-foreground mb-1">当前白名单 ({existingIps.length})</p>
                <div className="flex flex-wrap gap-1.5">
                  {existingIps.map((ip) => (
                    <Badge
                      key={ip}
                      className="bg-card border border-border text-xs px-2 py-0.5 cursor-pointer hover:border-negative/50"
                      onClick={() => handleRemoveIp(ip)}
                      title="点击移除"
                    >
                      {ip} ✕
                    </Badge>
                  ))}
                  {existingIps.length === 0 && (
                    <span className="text-xs text-muted-foreground">暂无</span>
                  )}
                </div>
              </div>

              {stagedIps.length > 0 && (
                <div>
                  <p className="text-[10px] text-muted-foreground mb-1">
                    暂存区 ({stagedIps.length}) — 批量提交
                  </p>
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {stagedIps.map((ip) => (
                      <Badge
                        key={ip}
                        className="bg-primary/20 text-primary border border-primary/30 text-xs px-2 py-0.5 cursor-pointer"
                        onClick={() => removeFromStaging(ip)}
                      >
                        {ip} ✕
                      </Badge>
                    ))}
                  </div>
                  <Button onClick={commitStaged} disabled={saving} className="w-full text-xs">
                    {saving ? '提交中...' : `批量提交 ${stagedIps.length} 个 IP`}
                  </Button>
                </div>
              )}

              <div className="flex gap-2">
                <Input
                  value={newIp}
                  onChange={(e) => setNewIp(e.target.value)}
                  placeholder="输入 IP 地址..."
                  className="text-xs flex-1"
                  onKeyDown={(e) => e.key === 'Enter' && addToStaging()}
                />
                <Button onClick={addToStaging} variant="outline" className="text-xs px-3">
                  暂存
                </Button>
              </div>

              {serverIp && (
                <Button onClick={addServerIp} variant="outline" className="w-full text-xs" disabled={loadingServerIp}>
                  添加服务器 IP ({serverIp})
                </Button>
              )}

              {error && <p className="text-xs text-negative">{error}</p>}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
