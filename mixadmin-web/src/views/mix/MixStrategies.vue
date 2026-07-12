<template>
  <div class="stratgrid">
    <div v-for="s in list" :key="s.code" class="scard" :style="{borderColor: META[s.code].color+'55'}" @click="go(s.code)">
      <div class="hd">
        <span class="code" :style="{background:META[s.code].colorBg,color:META[s.code].color}">{{ s.code }}</span>
        <span class="name">{{ s.layer }} · {{ s.name }}</span>
        <el-switch :model-value="s.enabled" size="small" @click.stop @change="toggle(s)" />
      </div>
      <div class="metrics">
        <div><em>坑位</em><b>{{ s.slots || '—' }}</b></div>
        <div><em>名义</em><b>{{ fmt(s.notional) }}</b></div>
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
import { ElMessage } from 'element-plus'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { mixApi } from '../../api/mix'

const list = ref([])
const router = useRouter()
const fmt = n => (n || 0).toLocaleString()
const go = code => router.push(`/mix/strategy/${code}`)
async function toggle(s) { await mixApi.strategyToggle(s.code); ElMessage.success(`${s.code} 启停已受理（202）`) }
onMounted(async () => { list.value = await mixApi.strategies() })
</script>

<style scoped lang="scss">
.stratgrid { display: flex; flex-direction: column; gap: 10px; }
.scard { border: 1px solid; border-radius: 10px; padding: 10px 14px; cursor: pointer; display: flex; flex-direction: column; gap: 8px;
  &:hover { background: var(--el-fill-color-light); } }
.hd { display: flex; align-items: center; gap: 10px;
  .code { padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 13px; }
  .name { font-weight: 700; flex: 1; } }
.metrics { display: flex; gap: 24px; font-size: 12px;
  div { display: flex; gap: 6px; align-items: baseline; }
  em { font-style: normal; color: var(--el-text-color-secondary); font-size: 11px; }
  b { font-size: 14px; } .up { color: #0ECB81; } }
.pipe { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 11px;
  .stage { background: var(--el-fill-color); border-radius: 5px; padding: 2px 8px; display: inline-flex; gap: 5px; align-items: baseline;
    em { font-style: normal; color: var(--el-text-color-secondary); font-size: 10px; } b { font-size: 12px; } }
  .arr { color: var(--el-text-color-placeholder); } }
</style>
