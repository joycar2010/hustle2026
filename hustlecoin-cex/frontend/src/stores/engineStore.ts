import { create } from 'zustand'
import { getDashboard, getWorkersStatus } from '@/api/engine'

interface WorkerInfo {
  id: number
  account_id: number
  account_note: string
  scope: string
  status: string
  active_positions: number
  cycle_count: number
  last_heartbeat: string | null
}

interface EngineState {
  status: string
  workers: WorkerInfo[]
  openPositions: number
  closedPositions: number
  totalPnl: number
  totalFundingFee: number
  recentTrades: Record<string, unknown>[]
  loading: boolean
  fetchDashboard: () => Promise<void>
  fetchWorkers: () => Promise<void>
  updateWorkerFromWs: (data: Record<string, unknown>) => void
}

export const useEngineStore = create<EngineState>((set) => ({
  status: 'UNKNOWN',
  workers: [],
  openPositions: 0,
  closedPositions: 0,
  totalPnl: 0,
  totalFundingFee: 0,
  recentTrades: [],
  loading: false,

  fetchDashboard: async () => {
    set({ loading: true })
    try {
      const data = await getDashboard()
      set({
        openPositions: data.open_positions ?? 0,
        closedPositions: data.closed_positions ?? 0,
        totalPnl: parseFloat(data.total_pnl ?? '0'),
        totalFundingFee: parseFloat(data.total_funding_fee ?? '0'),
        recentTrades: data.recent_trades ?? [],
        workers: data.workers ?? [],
        status: (data.workers ?? []).some((w: WorkerInfo) => w.status === 'RUNNING') ? 'RUNNING' : 'STOPPED',
      })
    } finally {
      set({ loading: false })
    }
  },

  fetchWorkers: async () => {
    try {
      const data = await getWorkersStatus()
      const workers = data.workers ?? data ?? []
      set({
        workers,
        status: workers.some((w: WorkerInfo) => w.status === 'RUNNING') ? 'RUNNING' : 'STOPPED',
      })
    } catch {
      // keep existing state
    }
  },

  updateWorkerFromWs: (data) => {
    set((state) => {
      const workers = state.workers.map((w) =>
        w.id === data.id ? { ...w, ...data } : w,
      ) as WorkerInfo[]
      return {
        workers,
        status: workers.some((w) => w.status === 'RUNNING') ? 'RUNNING' : 'STOPPED',
      }
    })
  },
}))
