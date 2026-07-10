// 共享格式化工具
export const fmt = (v, d = 2) => (v == null ? '–' : (+v).toFixed(d))
export const cls = (v) => (v == null ? '' : (v >= 0 ? 'pos' : 'neg'))
export const shortTs = (s) => (s ? String(s).replace('T', ' ').slice(5, 19) : '')
