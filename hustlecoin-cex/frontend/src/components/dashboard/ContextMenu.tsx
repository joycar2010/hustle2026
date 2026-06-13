import { useEffect, useRef } from 'react'

interface Position {
  id: number
  sub_account_id: number
  account_note?: string
  symbol: string
  status: string
}

interface ContextMenuProps {
  x: number
  y: number
  symbol: string
  position?: Position
  isPushed?: boolean
  isAccountRow?: boolean
  subAccountId?: number
  onAction: (action: string, extra?: Record<string, unknown>) => void
  onClose: () => void
}

export function ContextMenu({ x, y, symbol, position, isPushed, isAccountRow, subAccountId, onAction }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    if (rect.right > window.innerWidth) {
      el.style.left = `${x - rect.width}px`
    }
    if (rect.bottom > window.innerHeight) {
      el.style.top = `${y - rect.height}px`
    }
  }, [x, y])

  const actions = [
    { key: 'set_rule', label: '单一规则' },
    ...(isPushed
      ? [{ key: 'remove_slot', label: '移除币种（50U保护）' }]
      : [{ key: 'push_symbol', label: '推送借币' }]
    ),
    ...(!position ? [{ key: 'manual_open', label: '手动开仓' }] : []),
    { key: 'resume_slot', label: '恢复下单' },
    { key: 'blacklist', label: '加入黑名单' },
    { key: 'batch_remove', label: '批量移除无持仓' },
  ]

  const accountActions = isAccountRow && subAccountId
    ? [
        { key: 'divider', label: '' },
        { key: 'refresh_borrowable', label: '刷新最大可借' },
        { key: 'partial_repay', label: '部分还币' },
        { key: 'clear_account', label: '清除账户' },
      ]
    : []

  const posActions = position
    ? [
        { key: 'divider', label: '' },
        ...(position.status === 'BORROWED_IDLE' ? [{ key: 'manual_hedge', label: '手动对冲' }] : []),
        ...(position.status === 'PENDING_REPAY' ? [{ key: 'manual_repay', label: '手动还币' }] : []),
        { key: 'force_close', label: '强制平仓' },
        { key: 'transfer', label: '划转资金' },
        { key: 'view_detail', label: '查看详情' },
      ]
    : []

  const allActions = [...actions, ...accountActions, ...posActions]

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[160px] rounded border border-border bg-[#141420] py-1 shadow-xl"
      style={{ left: x, top: y }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="px-3 py-1 text-[10px] text-muted-foreground border-b border-border/50 mb-0.5">
        {symbol}{position ? ` · ${position.account_note || `#${position.sub_account_id}`}` : ''}
        {isAccountRow && subAccountId ? ` · 账户#${subAccountId}` : ''}
      </div>
      {allActions.map((action, i) =>
        action.key === 'divider' ? (
          <div key={i} className="my-0.5 border-t border-border/50" />
        ) : (
          <button
            key={action.key}
            className="flex w-full items-center px-3 py-1 text-[11px] hover:bg-accent/50 transition-colors text-left"
            onClick={() => onAction(action.key, { subAccountId })}
          >
            {action.label}
          </button>
        ),
      )}
    </div>
  )
}
