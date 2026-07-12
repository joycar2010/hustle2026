// useLiveRefresh: 活保型轮询管理器(qhadmin 无 WS, 以健壮轮询等价实现 WS 的三性质):
//   ① 可见性暂停 — 标签页隐藏(document.hidden)时停轮询, 省流/省后端; 回到前台立即刷一次并恢复。
//   ② 指数退避 — 请求失败按 base×2^n 退避(封顶 maxMs), 成功即复位, 避免后端抖动时轮询风暴。
//   ③ 前台/联网自愈 — visibilitychange 回前台 + window online 事件, 均立即重连刷新。
// 用法(在 setup 内):
//   const live = useLiveRefresh(async ()=>{ await load() }, { interval: 10000 })
//   onMounted(live.start); onBeforeUnmount(live.stop)
import { onBeforeUnmount } from 'vue'
export function useLiveRefresh(fn, opts={}){
  const interval = opts.interval || 10000
  const base = opts.backoffBase || interval
  const maxMs = opts.backoffMax || 60000
  let timer=null, stopped=true, fails=0, running=false
  function _delay(){ return fails>0 ? Math.min(maxMs, base*Math.pow(2,fails)) : interval }
  async function _tick(){
    if(stopped) return
    if(document.hidden){ _schedule(); return }   // 隐藏时跳过(仍排下一轮, 复现后立即执行)
    if(running){ _schedule(); return }
    running=true
    try{ await fn(); fails=0 }               // 成功复位退避
    catch(e){ fails=Math.min(fails+1, 6) }   // 失败累计(封顶 2^6)
    finally{ running=false; _schedule() }
  }
  function _schedule(){ if(stopped)return; clearTimeout(timer); timer=setTimeout(_tick, _delay()) }
  async function _refreshNow(){ if(stopped)return; clearTimeout(timer)
    if(!document.hidden){ try{ await fn(); fails=0 }catch(e){ fails=Math.min(fails+1,6) } }
    _schedule() }
  const onVis=()=>{ if(!document.hidden) _refreshNow() }   // 回前台立即刷
  const onOnline=()=>{ fails=0; _refreshNow() }            // 联网恢复立即刷
  function start(){ if(!stopped)return; stopped=false; fails=0
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('online', onOnline)
    _refreshNow() }
  function stop(){ stopped=true; clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVis)
    window.removeEventListener('online', onOnline) }
  onBeforeUnmount(stop)   // 组件卸载兜底停止
  return { start, stop, refreshNow:_refreshNow }
}
