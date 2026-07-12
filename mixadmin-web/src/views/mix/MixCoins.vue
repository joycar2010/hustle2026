<template>
  <div class="mixcoins">
    <div class="bar">
      <span v-for="f in filters" :key="f.key" class="chip" :class="{on:filter===f.key}" @click="filter=f.key">
        {{ f.label }} {{ countOf(f.key) }}
      </span>
      <span class="hint">状态流转：启用 ⇄ 观察 ⇄ 暂停 → 下架；冻结为风控态，仅人工解冻；暂停/下架不动存量仓</span>
    </div>

    <el-table :data="shown" size="small" stripe>
      <el-table-column label="币种" width="90"><template #default="{row}"><b>{{ row.symbol }}</b></template></el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{row}">
          <el-tag size="small" :type="stateTag(row.state)" :effect="row.state==='frozen'?'dark':'plain'">{{ stateLabel(row.state) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="参与策略" width="150">
        <template #default="{row}">
          <span v-for="s in row.strategies" :key="s" class="sbadge" :style="{background:META[s].colorBg,color:META[s].color}">{{ s }}</span>
          <span v-if="!row.strategies.length" class="none">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="venues" label="上架交易所" min-width="200" />
      <el-table-column label="8h 费率差" width="100" align="right">
        <template #default="{row}"><span :class="String(row.rate8h).startsWith('-')?'dn':'up'">{{ row.rate8h }}</span></template>
      </el-table-column>
      <el-table-column label="点差 (bps)" width="90" align="right"><template #default="{row}">{{ row.spreadBps ?? '—' }}</template></el-table-column>
      <el-table-column prop="vol24h" label="24h 量" width="90" align="right" />
      <el-table-column label="在管" width="70" align="right">
        <template #default="{row}"><span :class="{red:row.state==='frozen'&&row.managed}">{{ row.managed }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="130" align="right">
        <template #default="{row}">
          <el-link v-if="row.state==='enabled'" type="warning" @click="act(row,'pause','暂停')">暂停</el-link>
          <el-link v-else-if="row.state==='paused'||row.state==='watch'" type="success" @click="act(row,'enable','上架')">上架</el-link>
          <el-link v-else-if="row.state==='frozen'" type="danger" @click="act(row,'unfreeze','解冻')">解冻</el-link>
          <el-link v-else type="info" disabled>下架中</el-link>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { mixApi } from '../../api/mix'

const coins = ref([])
const filter = ref('all')
const filters = [
  { key: 'all', label: '全部' }, { key: 'enabled', label: '启用' }, { key: 'watch', label: '观察' },
  { key: 'paused', label: '暂停' }, { key: 'frozen', label: '冻结' }, { key: 'delisted', label: '下架' },
]
const shown = computed(() => filter.value === 'all' ? coins.value : coins.value.filter(c => c.state === filter.value))
const countOf = k => k === 'all' ? coins.value.length : coins.value.filter(c => c.state === k).length
const stateLabel = s => ({ enabled: '启用', watch: '观察', paused: '暂停', frozen: '冻结', delisted: '下架' }[s] || s)
const stateTag = s => ({ enabled: 'success', watch: 'warning', paused: 'info', frozen: 'danger', delisted: 'info' }[s])

async function act(row, action, label) {
  try {
    if (action === 'unfreeze') await ElMessageBox.confirm(`解冻 ${row.symbol}？冻结为风控态（借币钉死/裸空触发）`, '人工解冻', { type: 'warning' })
    await mixApi.coinAction(row.symbol, action)
    ElMessage.success(`${row.symbol} ${label}已受理`)
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '被拒绝') }
}
async function load() { coins.value = await mixApi.coins() }
onMounted(load)
</script>

<style scoped lang="scss">
.mixcoins { display: flex; flex-direction: column; gap: 10px; }
.bar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
  .chip { padding: 3px 10px; border-radius: 6px; border: 1px solid var(--el-border-color); cursor: pointer; font-size: 12px; color: var(--el-text-color-secondary);
    &.on { background: #F0B90B; border-color: #F0B90B; color: #0B0E11; font-weight: 700; } }
  .hint { margin-left: auto; font-size: 11px; color: var(--el-text-color-placeholder); } }
.sbadge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 800; margin-right: 3px; }
.none { color: var(--el-text-color-placeholder); }
.up { color: #0ECB81; } .dn { color: #F6465D; } .red { color: #F6465D; font-weight: 800; }
</style>
