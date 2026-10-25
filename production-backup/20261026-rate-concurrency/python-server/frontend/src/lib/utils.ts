import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatNumber(value: number | string, decimals = 2): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '-'
  return num.toLocaleString('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function formatPercent(value: number | string, decimals = 4): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '-'
  return `${num >= 0 ? '+' : ''}${num.toFixed(decimals)}%`
}

export function formatPnl(value: number | string): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '-'
  const prefix = num >= 0 ? '+' : ''
  return `${prefix}${formatNumber(num)}`
}

export function pnlColor(value: number | string): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num) || num === 0) return 'text-muted-foreground'
  return num > 0 ? 'text-positive' : 'text-negative'
}

export function spreadColor(value: number): string {
  if (value >= 1.0) return 'text-positive'
  if (value >= 0.5) return 'text-yellow-400'
  if (value >= 0) return 'text-muted-foreground'
  return 'text-negative'
}

export function statusColor(status: string): string {
  switch (status.toUpperCase()) {
    case 'RUNNING': return 'bg-positive/20 text-positive'
    case 'STOPPED': return 'bg-negative/20 text-negative'
    case 'OPEN': return 'bg-primary/20 text-primary'
    case 'CLOSED': return 'bg-muted text-muted-foreground'
    default: return 'bg-muted text-muted-foreground'
  }
}
