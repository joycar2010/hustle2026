<template>
  <!-- V6·旧 C3.S 对比与淘汰页(设计帧 oBZch 1:1):仅管理员·迁移期;差异>0 阻止下线步骤推进 -->
  <div class="v6lg">
    <V6StatusBar :snap="snap" :stale="stale" :can-open="canOpen" :ago="ago"/>
    <div class="body">
      <div class="pghd">
        <div class="l">
          <div class="tabs">
            <span class="tb on">新版工作台</span>
            <span class="tb">旧版对比</span>
          </div>
          <i>仅管理员可进入 · 迁移期</i>
        </div>
        <div class="r">
          <span class="m"><i>同一截至时间</i><b>{{ asofT }}</b></span>
          <span class="m"><i>差异数</i><b :class="diffCount>0?'redtxt':'green'">{{ diffCount }} 项</b></span>
          <span class="m"><i>最后同步</i><b>{{ ago }}</b></span>
        </div>
      </div>
      <div class="cmp">
        <!-- V6 快照 -->
        <div class="side">
          <div class="shd"><b>V6 统一工作台快照</b><span class="badge ok">权威写入口</span></div>
          <div class="sbody">
            <div v-for="s in v6Slots" :key="s.pit" class="cr">
              <span class="pit">{{ s.pit }}</span>
              <span class="acct">{{ s.account }}</span>
              <span class="stage green">{{ s.stage_detail || s.stage }}</span>
              <span class="usd">{{ s.usdt!=null?s.usdt+' U':'N/A' }}</span>
              <span class="pnl" :class="s.confirmed_pnl>=0?'green':'redtxt'">{{ s.confirmed_pnl!=null?(s.confirmed_pnl>=0?'+':'')+s.confirmed_pnl+' U':'N/A' }}</span>
            </div>
            <div v-if="!v6Slots.length" class="empty">V6 投影当前无 C3.S 坑位</div>
          </div>
        </div>
        <!-- 旧 C3.S 快照 -->
        <div class="side">
          <div class="shd"><b>旧 C3.S 坑位工作台快照</b><span class="badge no">只读·不会下单</span></div>
          <div class="sbody">
            <div v-for="s in legacySlots" :key="s.pit" class="cr dim">
              <span class="pit">{{ s.pit }}</span>
              <span class="acct">{{ s.account }}</span>
              <span class="stage">{{ s.stage }}</span>
              <span class="usd">{{ s.usdt!=null?s.usdt+' U':'N/A' }}</span>
              <span class="pnl t3">{{ s.borrowed!=null?'借 '+s.borrowed:'—' }}</span>
            </div>
            <div v-if="!legacySlots.length" class="empty">旧 C3.S 引擎当前无非终态坑位</div>
            <div class="watermark">旧版只读 · 所有写按钮与写 API 已撤销</div>
          </div>
        </div>
      </div>
      <!-- diff 明细(有差异才显示) -->
      <div v-if="diffs.length" class="diffs">
        <b class="dt">差异明细（{{ diffs.length }}）—— 差异>0 时置顶红字并阻止步骤推进</b>
        <div v-for="(d,i) in diffs" :key="i" class="drow">
          <span class="dp">{{ d.pit }}</span><span class="dd">{{ d.dim }}</span>
          <span class="dl">旧: {{ d.legacy ?? '—' }}</span><span class="dv">V6: {{ d.v6 ?? '—' }}</span>
          <span class="dn">{{ d.note || '' }}</span>
        </div>
      </div>
      <!-- 下线过程 -->
      <div class="offline">
        <b class="ot">下线过程（任何回滚都不能把旧版重新变成第二写入口）</b>
        <div class="steps">
          <template v-for="(s,i) in STEPS" :key="i">
            <span class="st" :class="s.cls">{{ s.k }}</span>
            <em v-if="i<STEPS.length-1" class="ar">›</em>
          </template>
        </div>
        <p class="onote">自动比较：坑位·账户·阶段·借币·成交·对冲·买回·还币·收益·允许动作 —— 差异>0 时置顶红字并阻止步骤推进 ｜ 连续 {{ zeroStreak }} 次零差异（门槛=连续14天/全场景 P0/P1 零差异+旧写接口14天零调用）</p>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { mixApi } from '../../api/mix'
import { useV6Snapshot } from '../../composables/useV6'
import V6StatusBar from '../../components/V6StatusBar.vue'

const { snap, stale, canOpen, ago } = useV6Snapshot()
const cmp = ref(null)
const zeroStreak = ref(0)

const v6Slots = computed(() => cmp.value?.v6?.slots || [])
const legacySlots = computed(() => cmp.value?.legacy?.slots || [])
const diffs = computed(() => cmp.value?.diffs || [])
const diffCount = computed(() => cmp.value?.diff_count ?? 0)
const asofT = computed(() => cmp.value?.as_of ? cmp.value.as_of.slice(11, 19) : (snap.value?.as_of?.slice(11, 19) || 'N/A'))

const STEPS = computed(() => {
  // 当前处于阶段③(V6 默认写入口·旧版只读30天),按记忆:C3.S 收编待分步授权
  return [
    { k: '① V6 只读影子 · 旧版继续执行', cls: 'done' },
    { k: '② V6 单账户/小额写入 · 旧版对应范围只读', cls: 'done' },
    { k: '③ V6 默认写入口 · 旧版只读对比 30 天（当前）', cls: 'cur' },
    { k: '④ 旧 URL 跳转 V6 · 仅审计归档', cls: 'todo' },
  ]
})

async function load() {
  try { cmp.value = await mixApi.v6LegacyCompare() } catch (e) { /* 只读 */ }
  try { const r = await mixApi.v6LegacyRuns(); zeroStreak.value = r?.zero_diff_streak ?? 0 } catch (e) { /* noop */ }
}
onMounted(load)
</script>
<style scoped>
.v6lg{height:100%;display:flex;flex-direction:column;background:var(--mix-bg);min-height:0}
.body{flex:1;display:flex;flex-direction:column;gap:8px;padding:8px 12px;min-height:0;overflow:auto}
.pghd{display:flex;justify-content:space-between;align-items:center}
.pghd .l{display:flex;align-items:center;gap:8px}
.tabs{display:flex;gap:2px;background:var(--mix-panel);border-radius:6px;padding:2px}
.tb{font-size:11.5px;color:var(--mix-t2);padding:4px 13px;border-radius:5px;cursor:pointer}
.tb.on{background:var(--mix-card2);color:var(--mix-t1);font-weight:700}
.pghd i{font-size:10px;color:var(--mix-t3);font-style:normal}
.pghd .r{display:flex;gap:12px}
.m{display:flex;gap:5px;align-items:center}
.m i{font-size:9.5px;color:var(--mix-t3);font-style:normal}
.m b{font-size:11px;color:var(--mix-t1)}
.cmp{display:flex;gap:8px;min-height:200px}
.side{flex:1;background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;display:flex;flex-direction:column;overflow:hidden}
.shd{display:flex;align-items:center;justify-content:space-between;padding:8px 12px 6px;border-bottom:1px solid var(--mix-border)}
.shd b{font-size:12px;color:var(--mix-t1)}
.badge{font-size:9px;font-weight:700;border-radius:4px;padding:2px 8px}
.badge.ok{background:#0ECB8114;color:var(--mix-green)}
.badge.no{background:#F6465D14;color:var(--mix-red)}
.sbody{flex:1;padding:6px 12px;position:relative}
.cr{display:flex;align-items:center;height:30px;border-bottom:1px solid var(--mix-border);gap:4px}
.cr.dim{opacity:.75}
.cr span{font-size:9.5px;padding:0 4px}
.pit{width:100px;color:var(--mix-t1);font-weight:700}
.acct{width:90px;color:var(--mix-t2)}
.stage{flex:1}
.usd{width:70px;color:var(--mix-t2)}
.pnl{width:80px;font-weight:700}
.watermark{margin-top:12px;background:#F6465D0D;border:1px solid #F6465D33;border-radius:6px;height:44px;display:flex;align-items:center;justify-content:center;color:var(--mix-red);font-size:10px;font-weight:700}
.diffs{background:var(--mix-card);border:1px solid #F6465D66;border-radius:8px;padding:8px 12px}
.dt{font-size:11.5px;color:var(--mix-red)}
.drow{display:flex;gap:10px;font-size:10px;padding:4px 0;border-bottom:1px solid var(--mix-border)}
.dp{width:90px;font-weight:700;color:var(--mix-t1)}
.dd{width:60px;color:var(--mix-accent)}
.dl,.dv{flex:1;color:var(--mix-t2)}
.dn{color:var(--mix-t3)}
.offline{background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;padding:8px 12px}
.ot{font-size:11.5px;color:var(--mix-t1)}
.steps{display:flex;align-items:center;gap:4px;margin:8px 0}
.st{flex:1;height:34px;display:flex;align-items:center;justify-content:center;text-align:center;border-radius:6px;font-size:9.5px;font-weight:700;border:1px solid var(--mix-border);padding:0 8px}
.st.done{background:#0ECB810F;color:var(--mix-green)}
.st.cur{background:#F0B90B14;color:var(--mix-accent);border-color:#F0B90B4D}
.st.todo{background:var(--mix-panel);color:var(--mix-t3)}
.ar{color:var(--mix-t3);flex:none}
.onote{font-size:9.5px;color:var(--mix-t3);margin:0;line-height:1.5}
.empty{padding:20px;text-align:center;color:var(--mix-t3);font-size:11px}
.green{color:var(--mix-green)}.redtxt{color:var(--mix-red)}.t3{color:var(--mix-t3)}
</style>
