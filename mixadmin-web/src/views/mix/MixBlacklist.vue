<template>
  <div class="mixbl">
    <el-tabs v-model="tab">
    <el-tab-pane label="准入隔离(多作用域)" name="q">
      <div class="qbar">
        <el-select v-model="qf.scope_type" size="small" style="width:170px">
          <el-option v-for="sc in Q_SCOPES" :key="sc.v" :label="sc.t" :value="sc.v" />
        </el-select>
        <el-input v-model="qf.scope_key" size="small" placeholder="作用域键(GLOBAL 免填)" style="width:200px" />
        <el-select v-model="qf.mode" size="small" style="width:150px">
          <el-option v-for="m in ['NO_NEW_RISK','REDUCE_ONLY','EXIT_ONLY','FROZEN']" :key="m" :label="m" :value="m" />
        </el-select>
        <el-input v-model="qf.reason" size="small" placeholder="原因/证据" style="width:220px" />
        <el-button type="warning" size="small" @click="qAdd">加入隔离</el-button>
        <span class="stats">共 {{ qrows.length }} 条 · 解除=追加 NORMAL(非删除,历史保留)</span>
      </div>
      <el-table :data="qrows" size="small" stripe>
        <el-table-column label="作用域" width="140"><template #default="{row}">
          <el-tag size="small" effect="plain" :type="scopeTag(row.scope_type)">{{ row.scope_type }}</el-tag></template></el-table-column>
        <el-table-column prop="scope_key" label="键" width="140" />
        <el-table-column label="模式" width="120"><template #default="{row}">
          <span :class="'m-'+row.mode">{{ row.mode }}</span></template></el-table-column>
        <el-table-column prop="reason" label="原因/证据" min-width="200" show-overflow-tooltip />
        <el-table-column label="强制状态" width="180"><template #default="{row}">
          <span :class="{dim: row.enforce.includes('待接')}">{{ row.enforce }}</span></template></el-table-column>
        <el-table-column prop="created_by" label="创建人" width="100" />
        <el-table-column label="有效期" width="110"><template #default="{row}">{{ row.expires_at ? row.expires_at.slice(0,10) : '不过期' }}</template></el-table-column>
        <el-table-column label="解除" width="90"><template #default="{row}">
          <el-link v-if="row.source==='override'" type="primary" @click="qLift(row)">解除</el-link>
          <span v-else class="dim">coin</span></template></el-table-column>
      </el-table>
      <div class="fnote">V2 §12:8 作用域(venue/主身份组/物理账户/凭证/产品/标的/资产网络/owner-mandate)。
        VENUE/GLOBAL 经 policy 引擎即时强制、SYMBOL 走 C3 黑名单;其余作用域登记+呈现,引擎消费为 risk-ledger 后续接入。解除是新增事件不删历史。</div>
    </el-tab-pane>
    <el-tab-pane label="C3 币种黑名单" name="bl">
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
    </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
const tab = ref('q')
const Q_SCOPES = [{v:'GLOBAL',t:'全局 GLOBAL'},{v:'VENUE',t:'平台 VENUE'},{v:'IDENTITY_GROUP',t:'主身份组'},
  {v:'ACCOUNT',t:'物理账户'},{v:'CREDENTIAL',t:'凭证'},{v:'PRODUCT',t:'产品/route'},
  {v:'SYMBOL',t:'标的 SYMBOL'},{v:'ASSET_NETWORK',t:'资产/网络'},{v:'OWNER_MANDATE',t:'owner/mandate'}]
const qf = ref({scope_type:'VENUE',scope_key:'',mode:'NO_NEW_RISK',reason:''})
const qrows = ref([])
const scopeTag = t => ({GLOBAL:'danger',VENUE:'warning',SYMBOL:'info'}[t]||'')
async function qLoad(){ try{ qrows.value=(await mixApi.quarantine()).rows||[] }catch(e){} }
async function qAdd(){
  try{ await mixApi.quarantineAdd({scope_type:qf.value.scope_type,
    scope_key:qf.value.scope_type==='GLOBAL'?'GLOBAL':qf.value.scope_key, mode:qf.value.mode, reason:qf.value.reason})
    ElMessage.success('已加入隔离(risk-ledger ≤30s 合并)'); qLoad()
  }catch(e){ ElMessage.error(e?.detail||e?.error||'失败') }
}
async function qLift(row){
  try{ await mixApi.quarantineAdd({scope_type:row.scope_type,scope_key:row.scope_key,mode:'NORMAL',reason:'操作员解除隔离'})
    ElMessage.success('已追加 NORMAL 解除(历史保留)'); qLoad()
  }catch(e){ ElMessage.error(e?.detail||'失败') }
}

import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const list = ref([])
const form = reactive({ symbol: '', scopeSel: '*', reason: '' })
const autoRatio = computed(() => list.value.length ? Math.round(list.value.filter(b => b.source !== 'manual').length / list.value.length * 100) : 0)

const srcLabel = s => ({ manual: '手动', auto_borrow_wedge: '自动·借币钉死', auto_3045: '自动·-3045 无券', announcement_delist: '自动·公告下架', risk_trigger: '自动·风控触发' }[s] || s)
const tagType = s => s === 'manual' ? 'info' : s === 'auto_3045' ? 'warning' : 'danger'

async function load() { list.value = await mixApi.blacklist() }
async function add() {
  if (!form.symbol) return ElMessage.warning('请输入币种')
  try {
    await mixApi.blacklistAdd(form.symbol, form.reason)
    ElMessage.success(`${form.symbol.toUpperCase()} 已加入黑名单（coin 权威侧已生效）`)
    form.symbol = ''; form.reason = ''; load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '加入失败') }
}
async function remove(row) {
  await ElMessageBox.confirm(`移除 ${row.symbol}？（重新进入费差候选池）`, '移除黑名单', { type: 'warning' })
  try {
    await mixApi.blacklistRemove(row.symbol)
    ElMessage.success('已移除'); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '移除失败') }
}
onMounted(() => { load(); qLoad() })
</script>

<style scoped lang="scss">
.mixbl { display: flex; flex-direction: column; gap: 10px; }
.bar { display: flex; gap: 8px; align-items: center; .stats { margin-left: auto; font-size: 12px; color: var(--el-text-color-secondary); } }
.red { color: #F6465D; font-weight: 700; }
.ft { font-size: 11px; color: var(--el-text-color-placeholder); }
.qbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.stats { font-size: 11px; color: var(--el-text-color-secondary); margin-left: 8px; }
.fnote { font-size: 10.5px; color: var(--el-text-color-secondary); margin-top: 8px; line-height: 1.6; }
.dim { color: var(--el-text-color-placeholder); }
.m-NO_NEW_RISK { color: #FF8A3D; font-weight: 700; } .m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; font-weight: 700; }
.m-FROZEN, .m-KILLED { color: #8B1E2D; font-weight: 700; } .m-QUARANTINED { color: #8B1E2D; font-weight: 700; }
</style>
