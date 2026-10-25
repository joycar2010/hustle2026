import { create } from 'zustand'

interface ConfirmOptions {
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  danger?: boolean   // true=确认按钮用警示红(平仓/还币/清账等高危操作)
}

interface ConfirmState {
  open: boolean
  opts: ConfirmOptions
  _resolve: ((v: boolean) => void) | null
  show: (opts: ConfirmOptions) => Promise<boolean>
  _close: (v: boolean) => void
}

const useConfirmStore = create<ConfirmState>((set, get) => ({
  open: false,
  opts: { message: '' },
  _resolve: null,
  show: (opts) =>
    new Promise<boolean>((resolve) => {
      set({ open: true, opts, _resolve: resolve })
    }),
  _close: (v) => {
    const r = get()._resolve
    if (r) r(v)
    set({ open: false, _resolve: null })
  },
}))

/** Promise 化确认框,替代原生 confirm():`if (await confirmDialog({message:'...'})) {...}` */
export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  return useConfirmStore.getState().show(opts)
}

/** 挂在应用根部,渲染主界面风格的确认弹窗(暗色卡片 + 模态遮罩,与 SymbolRuleDialog 一致) */
export function ConfirmHost() {
  const open = useConfirmStore((s) => s.open)
  const opts = useConfirmStore((s) => s.opts)
  const close = useConfirmStore((s) => s._close)

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      onClick={() => close(false)}
    >
      <div
        className="w-full max-w-[400px] rounded-lg border border-border bg-[#141420] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {opts.title && (
          <div className="border-b border-border px-4 py-3 text-sm font-semibold text-foreground">
            {opts.title}
          </div>
        )}
        <div className="px-4 py-4 text-[13px] leading-relaxed text-foreground whitespace-pre-line">
          {opts.message}
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <button
            onClick={() => close(false)}
            className="rounded border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {opts.cancelText || '取消'}
          </button>
          <button
            onClick={() => close(true)}
            className={`rounded px-4 py-1.5 text-xs font-medium ${
              opts.danger
                ? 'bg-negative/20 text-negative hover:bg-negative/30'
                : 'bg-primary/20 text-primary hover:bg-primary/30'
            }`}
          >
            {opts.confirmText || '确认'}
          </button>
        </div>
      </div>
    </div>
  )
}
