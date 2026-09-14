import { useEffect, useState } from 'react'
import { listSSLCerts, uploadSSLCert, deleteSSLCert, deploySSLCert, scanLetsEncryptCerts, type SSLCert } from '@/api/admin'
import { extractError } from '@/api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { Plus, Upload, Trash2, Rocket, ScanSearch } from 'lucide-react'

export function SSLPage() {
  const [certs, setCerts] = useState<SSLCert[]>([])
  const [loading, setLoading] = useState(true)
  const [showUpload, setShowUpload] = useState(false)
  const [scanning, setScanning] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = () => {
    setLoading(true)
    listSSLCerts().then(setCerts).finally(() => setLoading(false))
  }

  useEffect(reload, [])

  const handleDeploy = async (id: number) => {
    try {
      await deploySSLCert(id)
      addToast('证书部署成功', 'success')
      reload()
    } catch (err: unknown) {
      addToast(extractError(err, '部署失败'), 'error')
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确认删除此证书?')) return
    try {
      await deleteSSLCert(id)
      addToast('已删除', 'success')
      reload()
    } catch (err: unknown) {
      addToast(extractError(err, '删除失败'), 'error')
    }
  }

  const daysLeft = (expiresAt: string | null) => {
    if (!expiresAt) return null
    const diff = (new Date(expiresAt).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
    return Math.max(0, Math.floor(diff))
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">SSL 证书管理</h1>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={scanning} onClick={async () => {
            setScanning(true)
            try {
              const res = await scanLetsEncryptCerts()
              if (res.added > 0) {
                addToast(`导入 ${res.added} 个证书: ${res.domains.join(', ')}`, 'success')
                reload()
              } else {
                addToast(`扫描完成，无新证书 (已扫描 ${res.scanned} 个目录)`, 'success')
              }
            } catch (err: unknown) { addToast(extractError(err, '扫描失败'), 'error') }
            finally { setScanning(false) }
          }}>
            <ScanSearch className="h-4 w-4" /> {scanning ? '扫描中...' : '扫描 Let\'s Encrypt'}
          </Button>
          <Button size="sm" onClick={() => setShowUpload(!showUpload)}>
            <Plus className="h-4 w-4" /> 上传证书
          </Button>
        </div>
      </div>

      {showUpload && (
        <UploadCertDialog
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); reload(); addToast('证书上传成功', 'success') }}
        />
      )}

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">域名</th>
                <th className="px-4 py-3">签发者</th>
                <th className="px-4 py-3">到期时间</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">部署</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : certs.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">暂无证书</td></tr>
              ) : (
                certs.map((c) => {
                  const dl = daysLeft(c.expires_at)
                  return (
                    <tr key={c.id} className="border-b last:border-0 hover:bg-accent/50">
                      <td className="px-4 py-3 font-medium">{c.cert_name}</td>
                      <td className="px-4 py-3">{c.domain_name}</td>
                      <td className="px-4 py-3 text-muted-foreground">{c.issuer || '-'}</td>
                      <td className="px-4 py-3">
                        {c.expires_at ? (
                          <span className={dl !== null && dl <= 7 ? 'text-negative' : dl !== null && dl <= 30 ? 'text-warning' : ''}>
                            {new Date(c.expires_at).toLocaleDateString('zh-CN')}
                            {dl !== null && ` (${dl}天)`}
                          </span>
                        ) : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={c.status === 'active' ? 'success' : 'destructive'}>{c.status}</Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={c.is_deployed ? 'success' : 'secondary'}>
                          {c.is_deployed ? '已部署' : '未部署'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1">
                          <Button size="sm" variant="ghost" onClick={() => handleDeploy(c.id)} title="部署">
                            <Rocket className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => handleDelete(c.id)} title="删除">
                            <Trash2 className="h-3.5 w-3.5 text-negative" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

function UploadCertDialog({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const [form, setForm] = useState({ cert_name: '', domain_name: '', cert_content: '', key_content: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleFile = (field: 'cert_content' | 'key_content') => (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setForm({ ...form, [field]: reader.result as string })
    reader.readAsText(file)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await uploadSSLCert(form)
      onUploaded()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '上传失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">上传 SSL 证书</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">证书名称</label>
              <Input value={form.cert_name} onChange={(e) => setForm({ ...form, cert_name: e.target.value })} required />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">域名</label>
              <Input value={form.domain_name} onChange={(e) => setForm({ ...form, domain_name: e.target.value })} required />
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">证书文件 (.pem / .crt)</label>
            <div className="flex gap-2">
              <Input type="file" accept=".pem,.crt" onChange={handleFile('cert_content')} />
              {form.cert_content && <Badge variant="success">已选择</Badge>}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">私钥文件 (.key / .pem)</label>
            <div className="flex gap-2">
              <Input type="file" accept=".pem,.key" onChange={handleFile('key_content')} />
              {form.key_content && <Badge variant="success">已选择</Badge>}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">或粘贴证书 PEM 内容</label>
            <textarea
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
              rows={4}
              value={form.cert_content}
              onChange={(e) => setForm({ ...form, cert_content: e.target.value })}
              placeholder="-----BEGIN CERTIFICATE-----"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">或粘贴私钥 PEM 内容</label>
            <textarea
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
              rows={4}
              value={form.key_content}
              onChange={(e) => setForm({ ...form, key_content: e.target.value })}
              placeholder="-----BEGIN PRIVATE KEY-----"
            />
          </div>
          {error && <p className="text-sm text-negative">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>取消</Button>
            <Button type="submit" disabled={saving}>
              <Upload className="h-4 w-4" />
              {saving ? '上传中...' : '上传'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
