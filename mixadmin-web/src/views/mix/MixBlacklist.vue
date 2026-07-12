<template>
  <div class="mixbl">
    <div class="bar">
      <el-input v-model="form.symbol" size="small" placeholder="币种，如 NULS" style="width:160px" />
      <el-select v-model="form.scopeSel" size="small" style="width:150px">
        <el-option label="全局" value="*" />
        <el-option v-for="c in ['S1','S2','S3','S4','S5','S6']" :key="c" :label="`仅 ${c}`" :value="c" />
      </el-select>
      <el-input v-model="form.reason" size="small" placeholder="原因备注" style="width:220px" />
      <el-button type="danger" size="small" @click="add">加入黑名单</el-button>
      <span class="stats">当前 {{ list.length }} 币 · 自动加入占比 {{ autoRatio }}%</span>
    </div>

    <el-table :data="list" size="small" stripe>
      <el-table-column label="币种" width="90"><template #default="{row}"><b>{{ row.symbol }}</b></template></el-table-column>
      <el-table-column label="来源" width="150">
        <template #default="{row}">
          <el-tag size="small" :type="tagType(row.source)" effect="plain">{{ srcLabel(row.source) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="生效范围" width="110">
        <template #default="{row}">
          <el-tag v-for="s in row.scope" :key="s" size="small" :type="s==='*'?'info':'warning'" effect="plain" style="margin-right:2px">
            {{ s === '*' ? '全局' : '仅 ' + s }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="原因备注" min-width="240" />
      <el-table-column prop="addedAt" label="加入时间" width="110" />
      <el-table-column label="到期" width="110">
        <template #default="{row}"><span :class="{red:row.until==='永久'||row.until==='人工解除'}">{{ row.until }}</span></template>
      </el-table-column>
      <el-table-column prop="hits" label="命中拦截" width="80" align="right" />
      <el-table-column label="操作" width="80" align="right">
        <template #default="{row}"><el-link type="warning" @click="remove(row)">移除</el-link></template>
      </el-table-column>
    </el-table>

    <div class="ft">三来源自动联动：公告命中「下架/维护」、借币 -3045 无券冷却、风控滑点/单腿触发；命中即禁入费差候选，存量持仓走正常退出，不强平。</div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const list = ref([])
const form = reactive({ symbol: '', scopeSel: '*', reason: '' })
const base = import.meta.env.VITE_MIX_API || 'http://localhost:8100/api/v1'
const autoRatio = computed(() => list.value.length ? Math.round(list.value.filter(b => b.source !== 'manual').length / list.value.length * 100) : 0)

const srcLabel = s => ({ manual: '手动', auto_borrow_wedge: '自动·借币钉死', auto_3045: '自动·-3045 无券', announcement_delist: '自动·公告下架', risk_trigger: '自动·风控触发' }[s] || s)
const tagType = s => s === 'manual' ? 'info' : s === 'auto_3045' ? 'warning' : 'danger'

async function load() { list.value = await mixApi.blacklist() }
async function add() {
  if (!form.symbol) return ElMessage.warning('请输入币种')
  await fetch(`${base}/blacklist`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ symbol: form.symbol, reason: form.reason, scope: [form.scopeSel] }) })
  ElMessage.success(`${form.symbol.toUpperCase()} 已加入黑名单（${form.scopeSel === '*' ? '全局' : '仅 ' + form.scopeSel}）`)
  form.symbol = ''; form.reason = ''; load()
}
async function remove(row) {
  await ElMessageBox.confirm(`移除 ${row.symbol}？（重新进入费差候选池）`, '移除黑名单', { type: 'warning' })
  await fetch(`${base}/blacklist/remove`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ symbol: row.symbol }) })
  ElMessage.success('已移除'); load()
}
onMounted(load)
</script>

<style scoped lang="scss">
.mixbl { display: flex; flex-direction: column; gap: 10px; }
.bar { display: flex; gap: 8px; align-items: center; .stats { margin-left: auto; font-size: 12px; color: var(--el-text-color-secondary); } }
.red { color: #F6465D; font-weight: 700; }
.ft { font-size: 11px; color: var(--el-text-color-placeholder); }
</style>
