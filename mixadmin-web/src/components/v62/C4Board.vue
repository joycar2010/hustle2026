<template>
  <div v-if="data" class="c4bd">
    <div class="hd">
      <b>C4 期现交割 · 持有到期</b><i>现货多 + 交割空 · 基差硬锚</i>
      <span class="fill"></span>
      <i class="ts">数据源 R12-C4 + 采样器 · 30s 自刷</i>
    </div>
    <div v-for="p in rows" :key="p.pos_id" class="prow" :class="{bad: p.missing}">
      <div class="l1">
        <b class="sym">{{ p.symbol }}</b>
        <span class="ven">· {{ p.venue }}</span>
        <span class="chip" :class="p.missing ? 'red' : 'ok'">{{ p.missing ? '交割腿缺失!' : '账实一致' }}</span>
        <span class="fill"></span>
        <span class="exp">剩 {{ p.expiry_days != null ? p.expiry_days + ' 天' : '—' }}</span>
      </div>
      <div class="band">
        <span class="bc"><i>数量</i><b>{{ p.ledger_qty }}</b></span>
        <span class="bc"><i>实盘空腿</i><b>{{ p.live_qty != null ? p.live_qty : '—' }}</b></span>
        <span class="bc"><i>当前毛年化</i><b :class="cls(p.ann_pct)">{{ pct(p.ann_pct) }}</b></span>
        <span class="bc"><i>净/占用年化</i><b :class="cls(p.net_ann)">{{ pct(p.net_ann) }}</b></span>
        <span class="bc"><i>强平距</i><b :class="liqCls(p.dist_liq_pct)">{{ p.dist_liq_pct != null ? n1(p.dist_liq_pct) + '%' : '—' }}</b></span>
      </div>
    </div>
    <div v-if="!rows.length" class="empty">无 C4 持仓</div>
    <div class="ft">现货腿不入衍生品归并,净敞口/孤儿按 c4 账回补;liq&lt;20% 预警 &lt;10% 致命;执行=B机 c4_exec(两钥匙,平时 SHADOW)</div>
  </div>
</template>

<script setup>
// C4 期现交割持仓卡 —— 只读展示(/api/v1/research/c4/positions);
// 账面(c4_position)vs 实盘(risk-ledger R12-C4)vs 当前净年化(采样器)三方一屏。
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { mixApi } from '../../api/mix'

const data = ref(null)
let timer = null

async function load () {
  try {
    data.value = await mixApi.c4Positions()
  } catch (e) {
    // 端点缺失/未授权时静默隐藏(卡片不冒充数据);401 由全局拦截器接管
    if (!data.value) data.value = null
  }
}
onMounted(() => { load(); timer = setInterval(load, 30000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })

const rows = computed(() => {
  const ps = data.value?.positions || []
  const bn = data.value?.basis_now || []
  return ps.map(p => {
    const b = bn.find(x => x.instrument_id === p.symbol && x.venue === p.venue) || {}
    return { ...p, ann_pct: b.ann_pct, net_ann: b.net_ann_capital_pct, missing: p.live_qty == null }
  })
})

function pct (x) { return x != null ? (x > 0 ? '+' : '') + Number(x).toFixed(2) + '%' : '—' }
function n1 (x) { return Number(x).toFixed(1) }
function cls (x) { return x == null ? '' : (x > 0 ? 'up' : (x < 0 ? 'dn' : '')) }
function liqCls (x) { return x == null ? '' : (x < 10 ? 'red' : (x < 20 ? 'warn' : 'okc')) }
</script>

<style scoped>
.c4bd { margin: 10px 0 4px; border: 1px solid rgba(212,175,55,.30); border-radius: 8px;
        background: linear-gradient(180deg, rgba(212,175,55,.06), rgba(212,175,55,.02)); padding: 8px 10px; }
.hd { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.hd b { color: #e8c266; font-size: 13px; }
.hd i { color: #8b8f98; font-size: 11px; font-style: normal; }
.hd .ts { font-size: 10px; }
.fill { flex: 1; }
.prow { padding: 6px 8px; border: 1px solid rgba(255,255,255,.07); border-radius: 6px;
        background: rgba(255,255,255,.02); margin-bottom: 6px; }
.prow.bad { border-color: rgba(239,68,68,.55); background: rgba(239,68,68,.06); }
.l1 { display: flex; align-items: center; gap: 6px; }
.sym { color: #eef1f6; font-size: 13px; }
.ven { color: #8b8f98; font-size: 11px; }
.exp { color: #a9aeb8; font-size: 11px; }
.chip { font-size: 10px; padding: 1px 7px; border-radius: 9px; }
.chip.ok { color: #58d68d; background: rgba(88,214,141,.10); border: 1px solid rgba(88,214,141,.35); }
.chip.red { color: #ff6b6b; background: rgba(255,107,107,.12); border: 1px solid rgba(255,107,107,.5); }
.band { display: flex; gap: 14px; margin-top: 5px; flex-wrap: wrap; }
.bc { display: flex; flex-direction: column; min-width: 74px; }
.bc i { color: #7c8089; font-size: 10px; font-style: normal; }
.bc b { color: #dfe3ea; font-size: 12px; font-weight: 600; }
.bc b.up { color: #58d68d; }
.bc b.dn { color: #ff6b6b; }
.bc b.red { color: #ff6b6b; }
.bc b.warn { color: #f5b041; }
.bc b.okc { color: #58d68d; }
.empty { color: #8b8f98; font-size: 11px; padding: 4px 2px; }
.ft { color: #6f747d; font-size: 10px; margin-top: 2px; }
</style>
