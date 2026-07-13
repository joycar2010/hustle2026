<template>
  <div class="stratgrid">
    <div v-for="s in list" :key="s.code" class="scard" :style="{borderColor: META[s.code].color+'55'}" @click="go(s.code)">
      <div class="hd">
        <span class="code" :style="{background:META[s.code].colorBg,color:META[s.code].color}">{{ s.code }}</span>
        <span class="name">{{ s.layer }} · {{ s.name }}</span>
        <!-- 模式切换：仅 S2 可网页热切（armed 需 ARM 二次确认）；其余只读标注 -->
        <span class="modebox" @click.stop>
          <el-radio-group v-if="s.modeSwitchable" :model-value="s.mode" size="small" @change="switchMode(s, $event)">
            <el-radio-button value="shadow">影子</el-radio-button>
            <el-radio-button value="armed">武装</el-radio-button>
          </el-radio-group>
          <el-tag v-else size="small" :type="s.mode==='armed'?'danger':'info'" effect="plain">{{ modeLabel(s.mode) }}</el-tag>
        </span>
      </div>
      <div class="metrics">
        <div><em>坑位</em><b>{{ s.slots || '—' }}</b></div>
        <div><em>持仓</em><b>{{ fmt(s.notional) }}</b></div>
        <div><em>今日</em><b class="up">+{{ s.pnlToday }}</b></div>
        <div><em>累计</em><b class="up">+{{ fmt(s.pnlTotal) }}</b></div>
        <div><em>E 通过</em><b>{{ s.ePass }}</b></div>
      </div>
      <div class="pipe">
        <template v-for="(v,k,i) in s.pipeline" :key="k">
          <span class="stage"><em>{{ k }}</em><b>{{ v }}</b></span>
          <span v-if="i < Object.keys(s.pipeline).length-1" class="arr">›</span>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { mixApi } from '../../api/mix'

const list = ref([])
const router = useRouter()
const fmt = n => (n || 0).toLocaleString()
const go = code => router.push(`/mix/strategy/${code}`)
const modeLabel = m => ({ shadow: '影子', armed: '武装', 未启用: '未启用' }[m] || m || '—')
async function load() { list.value = await mixApi.strategies() }
async function switchMode(s, mode) {
  try {
    let confirm
    if (mode === 'armed') {
      const { value } = await ElMessageBox.prompt(
        `切换 ${s.code} 为「武装」= 真金下单。输入 ARM 确认（gateway 联锁要求风控全绿）`,
        '武装确认', { inputPattern: /^ARM$/, inputErrorMessage: '必须输入 ARM' })
      confirm = value
    } else {
      await ElMessageBox.confirm(`切换 ${s.code} 为「影子」（停真金下单，仅决策记账）？`, '模式切换', { type: 'warning' })
    }
    const r = await mixApi.strategyMode(s.code, mode, confirm)
    ElMessage.success(`${s.code} 已切 ${modeLabel(mode)}（${r.note}）`)
    load()
  } catch (e) { if (e !== 'cancel') { ElMessage.error(e?.detail || e?.error || '切换失败'); load() } }
}
onMounted(load)
</script>

<style scoped lang="scss">
.stratgrid { display: flex; flex-direction: column; gap: 10px; }
.scard { border: 1px solid; border-radius: 10px; padding: 10px 14px; cursor: pointer; display: flex; flex-direction: column; gap: 8px;
  &:hover { background: var(--el-fill-color-light); } }
.hd { display: flex; align-items: center; gap: 10px;
  .code { padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 13px; }
  .name { font-weight: 700; flex: 1; }
  .modebox { display: inline-flex; align-items: center; } }
.metrics { display: flex; gap: 24px; font-size: 12px;
  div { display: flex; gap: 6px; align-items: baseline; }
  em { font-style: normal; color: var(--el-text-color-secondary); font-size: 11px; }
  b { font-size: 14px; } .up { color: #0ECB81; } }
.pipe { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 11px;
  .stage { background: var(--el-fill-color); border-radius: 5px; padding: 2px 8px; display: inline-flex; gap: 5px; align-items: baseline;
    em { font-style: normal; color: var(--el-text-color-secondary); font-size: 10px; } b { font-size: 12px; } }
  .arr { color: var(--el-text-color-placeholder); } }
</style>
