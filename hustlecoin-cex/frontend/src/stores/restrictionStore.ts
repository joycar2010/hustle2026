import { create } from 'zustand'

// 逐子账户"被币安API限制"状态(账户级:IP封禁/超频/Key失效/无权限…)
export interface RestrictionInfo {
  label: string       // 中文提示(如 "IP 被封禁"/"请求超频"/"API Key/IP 异常")
  remaining: number   // 收到时的剩余秒(0=无倒计时);前端按 updatedAt 推算实时剩余
  updatedAt: number
}

interface RestrictionState {
  restrictions: Map<number, RestrictionInfo>   // sub_account_id -> 限制态(无=未限制)
  setRestriction: (subAccountId: number, info: { label?: string; remaining?: number } | null) => void
}

export const useRestrictionStore = create<RestrictionState>((set) => ({
  restrictions: new Map(),
  setRestriction: (subAccountId, info) => {
    set((state) => {
      const next = new Map(state.restrictions)
      if (!info || !info.label) {
        next.delete(subAccountId)          // None/空 → 解除(自愈)
      } else {
        next.set(subAccountId, { label: info.label, remaining: info.remaining ?? 0, updatedAt: Date.now() })
      }
      return { restrictions: next }
    })
  },
}))
