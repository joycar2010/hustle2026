export type DashboardCandidateState = 'loading' | 'ready' | 'error'

interface DashboardEmptyMessageOptions {
  candidateState: DashboardCandidateState
  hasLiveMarketData: boolean
  hasSearch: boolean
  showPositionsOnly: boolean
}

export function dashboardEmptyMessage({
  candidateState,
  hasLiveMarketData,
  hasSearch,
  showPositionsOnly,
}: DashboardEmptyMessageOptions): string {
  if (candidateState === 'loading') return '正在加载候选币种...'
  if (candidateState === 'error') return '候选币种加载失败，请稍后重试'
  if (hasSearch) return '未找到匹配币种'
  if (showPositionsOnly) return '没有持仓币种'
  return hasLiveMarketData
    ? '实时行情已连接，暂无符合条件币种'
    : '暂无符合条件币种'
}
