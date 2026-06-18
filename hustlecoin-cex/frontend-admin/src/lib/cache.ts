// 轻量 sessionStorage 缓存:弱网/刷新时先显示就近数据,避免白屏(对齐 coin 端 store loadCached 模式)。
// 仅本会话有效;失败静默(配额/隐私模式)。带时间戳,调用方可判"是否过时"。

export function loadCache<T>(key: string): { data: T; ts: number } | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (raw) return JSON.parse(raw) as { data: T; ts: number }
  } catch { /* ignore */ }
  return null
}

export function saveCache<T>(key: string, data: T): number {
  const ts = Date.now()
  try {
    sessionStorage.setItem(key, JSON.stringify({ data, ts }))
  } catch { /* ignore quota/private-mode */ }
  return ts
}
