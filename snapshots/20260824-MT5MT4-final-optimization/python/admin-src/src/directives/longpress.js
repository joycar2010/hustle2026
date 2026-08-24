// v-longpress: 长按(默认550ms)触发, 移动端友好(touch+mouse), 移动误触/滚动自动取消。
// 用法: v-longpress="fn"  或  v-longpress:600="fn"(自定义毫秒)。触发时给元素加 .lp-active 视觉反馈。
export default {
  mounted(el, binding){
    const ms = parseInt(binding.arg) || 550
    let timer=null, fired=false, sx=0, sy=0
    const start=(e)=>{
      fired=false
      const t=e.touches?e.touches[0]:e; sx=t.clientX; sy=t.clientY
      el.classList.add('lp-active')
      timer=setTimeout(()=>{ fired=true; el.classList.remove('lp-active')
        if(typeof binding.value==='function') binding.value(e)
        // 触觉反馈(支持的设备)
        try{ if(navigator.vibrate) navigator.vibrate(15) }catch(_){}
      }, ms)
    }
    const move=(e)=>{ if(!timer)return; const t=e.touches?e.touches[0]:e
      if(Math.abs(t.clientX-sx)>10 || Math.abs(t.clientY-sy)>10) cancel() }
    const cancel=()=>{ if(timer){ clearTimeout(timer); timer=null } el.classList.remove('lp-active') }
    // 长按触发后吞掉随后的 click(避免误触行点击)
    const clickGuard=(e)=>{ if(fired){ e.stopPropagation(); e.preventDefault(); fired=false } }
    el.__lp__={start,move,cancel,clickGuard}
    el.addEventListener('touchstart',start,{passive:true})
    el.addEventListener('touchmove',move,{passive:true})
    el.addEventListener('touchend',cancel)
    el.addEventListener('touchcancel',cancel)
    el.addEventListener('mousedown',start)
    el.addEventListener('mousemove',move)
    el.addEventListener('mouseup',cancel)
    el.addEventListener('mouseleave',cancel)
    el.addEventListener('click',clickGuard,true)
  },
  unmounted(el){
    const h=el.__lp__; if(!h)return
    el.removeEventListener('touchstart',h.start); el.removeEventListener('touchmove',h.move)
    el.removeEventListener('touchend',h.cancel); el.removeEventListener('touchcancel',h.cancel)
    el.removeEventListener('mousedown',h.start); el.removeEventListener('mousemove',h.move)
    el.removeEventListener('mouseup',h.cancel); el.removeEventListener('mouseleave',h.cancel)
    el.removeEventListener('click',h.clickGuard,true)
    delete el.__lp__
  }
}
