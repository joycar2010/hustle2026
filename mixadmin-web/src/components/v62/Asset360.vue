<template>
  <!-- Asset 360 单币全景抽屉/全屏（MIX-V6.2-ASSET360-PATCH-01 A1-A4）
       统一入口：今日工作/策略表/机会墙/AiCoin搜索点币种→打开同一抽屉；需深度研判再切全屏。
       A1阶段：顶部摘要+六所价格/资金费表（复用REV4基建）；A2补充提/A3韩国市值/A4研判表单。 -->
  <div class="a360" :class="{fullscreen:fullscreen}">
    <div class="a360hd">
      <div class="title">
        <b>{{ asset?.canonical_symbol || assetId }}</b>
        <span class="id" v-if="asset?.identity_status">{{ asset.identity_status }}</span>
        <span class="asof">数据截至 {{ ago }}s 前</span>
      </div>
      <div class="acts">
        <el-button size="small" :icon="RefreshRight" :loading="loading" @click="load">刷新</el-button>
        <el-button size="small" :icon="fullscreen?Close:FullScreen" @click="$emit('toggle-fullscreen')">{{ fullscreen?'返回':'全屏' }}</el-button>
        <el-button size="small" :icon="Close" @click="$emit('close')" v-if="!fullscreen">关闭</el-button>
      </div>
    </div>
    <div class="a360sum" v-if="snap">
      <span class="f"><i>币安市值</i><b class="amtx">{{ fmtBig(gs.reported_market_cap_usd?.value) }}</b></span>
      <span class="f"><i>参考价</i><b>{{ mv(gs.reference_spot_price_usd) }}</b></span>
      <span class="f"><i>全所OI</i><b>{{ mv(gs.all_venue_oi_usd) }}</b></span>
      <span class="f"><i>上市平台</i><b>{{ gs.listed_venue_count?.value || '—' }}</b></span>
      <span class="f"><i>数据质量</i><b>{{ snap.quality_summary?.coverage_pct || '—' }}%</b></span>
      <span class="ksep" v-if="krRows.length"></span>
      <span class="f kf" v-for="k in krRows" :key="k.venue">
        <i>韩·{{ k.venue==='upbit'?'Upbit':'Bithumb' }}</i>
        <b><span class="amtx">{{ fmtNum(k.normalized_price_usd, 2) }}</span>
          <em class="kprem" :class="premCls(k.normalized_price_usd)">{{ premTxt(k.normalized_price_usd) }}</em></b>
      </span>
      <span class="f kf" v-if="!krRows.length"><i>韩国</i><b class="t3">未上市</b></span>
    </div>

    <div class="a360tbl" v-if="snap">
      <!-- 单页整合(用户拍板弃tab):研判→执行一档→韩国→充提,一屏下滑全看完 -->
      <div class="sect">逐所全景 · 现货/合约成交量 · 持仓量 · 杠杆 · 费率 · 充提(WS秒级)</div>
      <div class="thead trow pano">
        <span class="c-venue">平台</span>
        <span class="c-num r">现货量</span>
        <span class="c-num r">24h合约量</span>
        <span class="c-num r">合约持仓</span>
        <span class="c-cap">全仓</span>
        <span class="c-cap">逐仓</span>
        <span class="c-num r">当期费率</span>
        <span class="c-num r">周期h</span>
        <span class="c-cap">提</span>
        <span class="c-cap">充</span>
        <span class="c-price r">现货价</span>
        <span class="c-price r">合约价</span>
      </div>
      <div v-for="v in snap.venue_rows" :key="'p'+v.venue" class="trow pano">
        <span class="c-venue"><b :class="'vx-'+v.venue">{{ v.venue }}</b></span>
        <span class="c-num r amtx">{{ fmtBig(v.spot_vol_24h_usd?.value) }}</span>
        <span class="c-num r amtx">{{ fmtBig(v.perp_vol_24h_usd?.value) }}</span>
        <span class="c-num r amtx">{{ fmtBig(v.oi_usd?.value) }}</span>
        <span class="c-cap" :class="capCls(v.has_cross)">{{ capTxt(v.has_cross) }}</span>
        <span class="c-cap" :class="capCls(v.has_isolated)">{{ capTxt(v.has_isolated) }}</span>
        <span class="c-num r" :class="cls0(v.funding_daily_pct?.value)">{{ fmtMv(v.funding_daily_pct) }}</span>
        <span class="c-num r">{{ fmtMv(v.funding_interval_h) }}</span>
        <span class="c-cap" :class="wdCls(v.withdraw_status)">{{ ioTxt(v.withdraw_status) }}</span>
        <span class="c-cap" :class="wdCls(v.deposit_status)">{{ ioTxt(v.deposit_status) }}</span>
        <span class="c-price r">{{ midOf(v.spot_l1) }}</span>
        <span class="c-price r">{{ midOf(v.perp_l1) }}</span>
      </div>
      <div class="placeholder" style="font-size:9.5px">成交量/持仓/价格=WS秒级;全仓逐仓=交易所能力;费率=当期资金费%/日;<b>提/充=待B机充提采集(批二授权后点亮,现"?")</b>。</div>

      <div class="sect">执行一档 · 现货+永续买卖1(判断能不能做)</div>
      <div class="sect">充提网络</div>
      <div class="placeholder">逐网络充提状态需签名API,留A5统一采集(cred-agent缓存)</div>
    </div>
    <div class="a360ft" v-if="snap">
      A1阶段：身份映射+六所价格/资金费（复用REV4批A/C基建）；24h量/OI/充提/韩国/市值留后续批次。
      未知≠0：NOT_CONNECTED=数据源未接入，STALE=过期，MAINTENANCE=维护。
    </div>
    <div v-if="err" class="err">{{ err }}</div>
  </div>
</template>
<script setup>
import { ref, computed, watch } from 'vue'
import { RefreshRight, FullScreen, Close } from '@element-plus/icons-vue'
import { mixApi } from '../../api/mix'

const mv0 = (v) => (v == null ? '—' : Number(v) >= 1e6 ? (v/1e6).toFixed(1)+'M' : Number(v) >= 1e3 ? (v/1e3).toFixed(1)+'K' : String(Math.round(v)))
const props = defineProps({
  assetId: { type: String, required: true },
  fullscreen: { type: Boolean, default: false },
})
defineEmits(['close', 'toggle-fullscreen'])

const snap = ref(null); const asset = ref(null); const err = ref(''); const loading = ref(false)
const preset = ref('research'); const tick = ref(0)
const gs = computed(() => snap.value?.global_summary || {})
const ago = computed(() => {
  void tick.value
  if (!snap.value?.generated_at) return '—'
  return Math.max(0, Math.floor((Date.now() - new Date(snap.value.generated_at).getTime()) / 1000))
})
function mv(e) { return e?.value != null ? e.value : (e?.state === 'NOT_CONNECTED' ? '未接入' : '—') }
function fmtMv(e) {
  if (!e || e.state === 'NOT_CONNECTED') return '—'
  if (e.state === 'STALE') return '过期'
  if (e.value == null) return '—'
  const v = Number(e.value)
  return Math.abs(v) >= 1000 ? v.toLocaleString('en-US', { maximumFractionDigits: 2 }) : v.toFixed(e.unit === '%' ? 3 : 2)
}
function fmtTime(ts) {
  if (!ts) return '—'
  const d = new Date(Number(ts) * 1000)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`
}
function fmtNum(v, dp = 2) {
  if (v == null) return '—'
  const n = Number(v)
  return n >= 1000 ? n.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp }) : n.toFixed(dp)
}
function cls0(v) { return v == null ? '' : (Number(v) >= 0 ? 'up' : 'dn') }
function fmtBig(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (n >= 1e12) return (n / 1e12).toFixed(2) + '万亿'
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(1) + '万'
  return String(Math.round(n))
}
function capTxt(e) { const v = e?.value; return v === true ? '有' : v === false ? '无' : '?' }
function capCls(e) { const v = e?.value; return v === true ? 'up' : v === false ? 't3' : 't3' }
function ioTxt(e) { const s = e?.value || e?.state; return s === 'OPEN' ? '开' : s === 'CLOSED' ? '关' : '?' }
function wdCls(e) { const s = e?.value || e?.state; return s === 'OPEN' ? 'up' : s === 'CLOSED' ? 'dn' : 't3' }
function midOf(l1) {
  if (!l1 || l1.state !== 'PRESENT' || l1.bid == null || l1.ask == null) return l1?.state === 'NOT_APPLICABLE' ? '—' : '·'
  const m = (Number(l1.bid) + Number(l1.ask)) / 2
  return m >= 1 ? m.toLocaleString('en-US', { maximumFractionDigits: 2 }) : m.toPrecision(4)
}
const krRows = computed(() => (snap.value?.korea_rows) || [])
function premTxt(usd) {
  const ref = Number(gs.value?.reference_spot_price_usd?.value)
  if (!usd || !ref) return ''
  const p = (usd / ref - 1) * 100
  return (p >= 0 ? '+' : '') + p.toFixed(1) + '%'
}
function premCls(usd) {
  const ref = Number(gs.value?.reference_spot_price_usd?.value)
  if (!usd || !ref) return 't3'
  return usd / ref >= 1 ? 'up' : 'dn'
}
function liqCls(d) { if (d == null) return ''; return d < 50 ? 'dn' : (d < 80 ? 'warn' : '') }
async function load() {
  loading.value = true; err.value = ''
  try {
    const r = await mixApi.asset360Snapshot(props.assetId)
    snap.value = r; asset.value = { canonical_symbol: r.canonical_symbol, identity_status: 'VERIFIED' }
  } catch (e) { err.value = typeof e?.detail === 'string' ? e.detail : '加载失败' }
  finally { loading.value = false }
}
watch(() => props.assetId, () => load(), { immediate: true })
setInterval(() => tick.value++, 1000)
</script>
<style scoped>
.a360{display:flex;flex-direction:column;gap:8px;background:var(--mix-card,#181B21);border:1px solid var(--mix-border,#262B33);border-radius:8px;overflow:hidden;
  position:fixed;top:0;right:0;bottom:0;width:60%;z-index:9000;box-shadow:-4px 0 24px rgba(0,0,0,0.3)}
.a360.fullscreen{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;z-index:9999;border-radius:0}
.a360hd{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid var(--mix-border,#262B33);background:var(--mix-panel,#12151A)}
.title{display:flex;align-items:center;gap:8px}
.title b{font-size:16px;color:var(--mix-t1,#EAECEF)}
.id{font-size:9px;color:var(--mix-green,#0ECB81);border:1px solid #0ECB8155;border-radius:3px;padding:1px 5px}
.asof{font-size:9px;color:var(--mix-t3,#5E6673)}
.acts{display:flex;gap:6px}
.a360sum{display:flex;align-items:center;gap:16px;padding:8px 12px;overflow-x:auto;white-space:nowrap;border-bottom:1px solid var(--mix-border,#262B33)}
.f{display:inline-flex;flex-direction:column;gap:1px;flex:none}
.f i{font-style:normal;font-size:8.5px;color:var(--mix-t3,#5E6673)}
.f b{font-size:11.5px;color:var(--mix-t1,#EAECEF);font-variant-numeric:tabular-nums}
.a360tabs{display:flex;gap:2px;padding:4px 12px;background:var(--mix-panel,#12151A);border-bottom:1px solid var(--mix-border,#262B33)}
.a360tabs a{font-size:10.5px;color:var(--mix-t2,#848E9C);padding:4px 12px;border-radius:4px;cursor:pointer}
.a360tabs a.on{background:var(--mix-card,#181B21);color:var(--mix-t1,#EAECEF);font-weight:600}
.a360tbl{overflow-x:auto;flex:1;overflow:auto;min-height:0}
.trow{display:flex;align-items:center;gap:8px;min-width:880px;padding:0 12px;min-height:30px;border-bottom:1px solid var(--mix-border,#262B33);font-size:10.5px;color:var(--mix-t2,#848E9C)}
.thead{position:sticky;top:0;z-index:2;background:var(--mix-panel,#12151A);color:var(--mix-t3,#5E6673);font-size:9.5px;min-height:24px}
.trow>span{flex-shrink:0;min-width:0}
.c-venue{width:90px}
.c-pair{width:100px}
.c-price{width:90px}
.c-num{width:80px}
.c-time{width:70px;font-size:9px}
.r{text-align:right;font-variant-numeric:tabular-nums}
.trow b{color:var(--mix-t1,#EAECEF)}
.up{color:var(--mix-green,#0ECB81)}.dn{color:var(--mix-red,#F6465D)}.warn{color:#FF8A3D}
.a360ft{font-size:8px;color:var(--mix-t3,#5E6673);line-height:1.4;padding:6px 12px;border-top:1px solid var(--mix-border,#262B33)}
.placeholder{padding:40px;text-align:center;color:var(--mix-t3,#5E6673);font-size:11px}
.err{padding:20px;text-align:center;color:var(--mix-red,#F6465D);font-size:11px}
.thin{color:#F6465D!important}
.t3{color:var(--mix-t3)}
.sect{font-size:10.5px;font-weight:800;color:var(--mix-gold,#F0B90B);padding:8px 2px 4px;border-bottom:1px solid var(--mix-border,#262B33);margin-bottom:4px}
.trow.pano{display:grid;grid-template-columns:62px 76px 76px 76px 30px 30px 62px 34px 26px 26px 82px 82px;gap:5px;align-items:center;font-size:10px;padding:3px 12px;border-bottom:1px solid var(--mix-border,#262B33);min-width:770px}
.trow.pano.thead{color:var(--mix-t3,#5E6673);font-size:9px;background:var(--mix-panel,#12151A)}
.trow.pano span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums;min-width:0;width:auto !important}
.c-cap{text-align:center;font-size:9.5px}
.kf i{color:#8CA3C7 !important}.ksep{width:1px;height:22px;background:var(--mix-border,#262B33);flex:none}
.kprem{font-style:normal;font-size:9px;margin-left:3px}
</style>
