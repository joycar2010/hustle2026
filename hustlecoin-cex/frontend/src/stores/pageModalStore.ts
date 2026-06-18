import { create } from 'zustand'

// 顶部导航"单击弹模态"的全局状态:记录当前以模态形式打开的页面路由与标题。
// route=null 表示无模态。双击导航项时由调用方先 close() 再 window.open 新标签。
interface PageModalState {
  route: string | null
  label: string | null
  open: (route: string, label: string) => void
  close: () => void
}

export const usePageModalStore = create<PageModalState>((set) => ({
  route: null,
  label: null,
  open: (route, label) => set({ route, label }),
  close: () => set({ route: null, label: null }),
}))
