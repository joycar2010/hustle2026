/**
 * 行内操作防重入（inflight guard）
 *
 * 历史教训（testgo 手动交易防重入失效）：
 *  - inflight 标志必须在发起瞬间置位（不是等 202 回来才置）；
 *  - 必须带 watchdog：请求挂死/网络黑洞时 8s 强制复位，否则按钮永久锁死；
 *  - key 粒度 = `${action}:${rowId}:${accountId}`，同行不同动作互不阻塞，
 *    同动作重复点击一律吞掉。
 */
import { reactive, readonly } from 'vue'

const WATCHDOG_MS = 8_000

interface InflightEntry {
  since: number
  timer: ReturnType<typeof setTimeout>
}

const store = reactive(new Map<string, InflightEntry>())

function release(key: string) {
  const e = store.get(key)
  if (e) {
    clearTimeout(e.timer)
    store.delete(key)
  }
}

export function useInflight() {
  /** 是否有在途请求（模板里绑 disabled / loading） */
  function isInflight(key: string): boolean {
    return store.has(key)
  }

  /**
   * 守卫执行：已在途 → 直接返回 null（吞掉重复点击，不排队）。
   * 置位 → 执行 → finally 复位；watchdog 到期强制复位并告警上报。
   */
  async function guard<T>(key: string, fn: () => Promise<T>): Promise<T | null> {
    if (store.has(key)) return null
    const timer = setTimeout(() => {
      // watchdog 强制复位：请求可能仍在途，复位仅解锁 UI，结果以 WS 推送对账为准
      release(key)
      console.warn(`[inflight] watchdog 复位 ${key}（>${WATCHDOG_MS}ms 未返回）`)
      // TODO: 上报告警通道（飞书/告警时间线），级别 WARN
    }, WATCHDOG_MS)
    store.set(key, { since: Date.now(), timer })
    try {
      return await fn()
    } finally {
      release(key)
    }
  }

  /** 组合 key 的便捷方法 */
  function keyOf(action: string, rowId: string, accountId?: string): string {
    return accountId ? `${action}:${rowId}:${accountId}` : `${action}:${rowId}`
  }

  return { isInflight, guard, keyOf, inflight: readonly(store) }
}
