<template>
  <div class="mixcoins">
    <el-tabs v-model="ctab" @tab-change="onCtab">
    <el-tab-pane label="Instrument Matrix" name="inst" lazy>
      <div class="rbar">
        <el-select v-model="ivenue" size="small" style="width:130px" @change="loadInst">
          <el-option v-for="v in ['binance','bybit','okx','gate','bitget','hyperliquid']" :key="v" :value="v" /></el-select>
        <el-input v-model="isearch" size="small" placeholder="筛选 symbol" style="width:140px" clearable />
        <el-button size="small" :loading="ibusy" @click="loadInst">刷新</el-button>
        <span class="dimtxt">{{ instShown.length }}/{{ instCount }} 合约 · 状态≠开仓资格(资格看 policy+经济闸)</span>
      </div>
      <el-table :data="instShown" size="small" stripe max-height="440">
        <el-table-column prop="instrument_id" label="合约" width="130" />
        <el-table-column prop="market_type" label="类型" width="70" />
        <el-table-column prop="linear_inverse" label="正/反" width="70" />
        <el-table-column prop="multiplier" label="乘数" width="70" align="right" />
        <el-table-column prop="quote" label="计价" width="70" />
        <el-table-column prop="settle_ccy" label="结算" width="70" />
        <el-table-column prop="contract_type" label="合约型" width="90" />
        <el-table-column label="到期" width="110"><template #default="{row}">{{ row.expiry || '永续' }}</template></el-table-column>
        <el-table-column prop="tick_size" label="Tick" width="90" align="right" />
        <el-table-column prop="min_qty" label="最小量" width="80" align="right" />
        <el-table-column prop="status" label="状态" width="80" />
      </el-table>
      <div class="fnote">Instrument Matrix 实时采集(i1 公开端点无需key);合约规格是准入基础设施,Registry 状态≠开仓资格。</div>
    </el-tab-pane>
    <el-tab-pane label="Route Registry" name="route" lazy>
      <div class="rbar"><b>权威路由表</b><span class="dimtxt">route_assignments · 开仓资格另看 policy_eligibility</span>
        <el-button size="small" @click="loadRoutes" style="margin-left:auto">刷新</el-button></div>
      <el-table :data="routes" size="small" stripe max-height="440">
        <el-table-column prop="symbol" label="标的" width="120" />
        <el-table-column prop="engine" label="引擎" width="90" />
        <el-table-column label="状态" width="90"><template #default="{row}"><span :class="'rs-'+row.state">{{ row.state }}</span></template></el-table-column>
        <el-table-column prop="venue_long" label="多腿" width="90" />
        <el-table-column prop="venue_short_" label="空腿" width="90" />
        <el-table-column prop="target_notional" label="目标U" width="90" align="right" />
        <el-table-column label="Policy 资格" min-width="180"><template #default="{row}">
          <span :class="row.policy_eligibility==='OK'?'ok':'bad'">{{ row.policy_eligibility }}</span></template></el-table-column>
      </el-table>
      <div class="fnote">Route Registry 只是权威路由;开仓资格=Policy Eligibility + 经济闸 + 数据健康。</div>
    </el-tab-pane>
    <el-tab-pane label="Asset / Network" name="asset" lazy>
      <div class="rbar"><b>资产/网络充提状态</b><span class="dimtxt">{{ assetNet.length }} 资产 · 持仓币提现关=下架/脱锚前兆</span>
        <el-button size="small" @click="loadAsset" style="margin-left:auto">刷新</el-button></div>
      <el-table :data="assetNet" size="small" stripe max-height="440">
        <el-table-column prop="asset" label="资产" width="100" />
        <el-table-column label="充值" width="90"><template #default="{row}"><span :class="row.deposit?'ok':'bad'">{{ row.deposit?'可充':'关闭' }}</span></template></el-table-column>
        <el-table-column label="提现" width="90"><template #default="{row}"><span :class="row.withdraw?'ok':'bad'">{{ row.withdraw?'可提':'关闭' }}</span></template></el-table-column>
        <el-table-column label="更新" min-width="160"><template #default="{row}">{{ row.ts ? new Date(row.ts*1000).toLocaleString('zh') : 'N/A' }}</template></el-table-column>
      </el-table>
    </el-tab-pane>
    <el-tab-pane label="币种准入" name="coins">
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
    </el-tab-pane>
    </el-tabs>
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
const ctab = ref('inst')
const ivenue = ref('binance'); const isearch = ref(''); const ibusy = ref(false)
const instruments = ref([]); const instCount = ref(0); const routes = ref([]); const assetNet = ref([])
const instShown = computed(() => isearch.value ? instruments.value.filter(r => r.instrument_id.includes(isearch.value.toUpperCase())) : instruments.value)
async function loadInst(){ ibusy.value=true; try{ const d=await mixApi.regInstruments(ivenue.value); instruments.value=d.rows||[]; instCount.value=d.count||0 }catch(e){}finally{ibusy.value=false} }
async function loadRoutes(){ try{ routes.value=(await mixApi.regRoutes())?.rows||[] }catch(e){} }
async function loadAsset(){ try{ assetNet.value=(await mixApi.regAssetNetwork())?.rows||[] }catch(e){} }
function onCtab(){ if(ctab.value==='inst'&&!instruments.value.length)loadInst(); if(ctab.value==='route'&&!routes.value.length)loadRoutes(); if(ctab.value==='asset'&&!assetNet.value.length)loadAsset(); if(ctab.value==='coins')load() }
onMounted(() => loadInst())
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
.rbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; b { font-size: 13px; } }
.dimtxt { color: var(--el-text-color-secondary); font-size: 10.5px; }
.fnote { font-size: 10px; color: var(--el-text-color-secondary); margin-top: 8px; }
.ok { color: #0ECB81; font-weight: 700; } .bad { color: #F6465D; }
.rs-active { color: #0ECB81; } .rs-off, .rs-draining { color: #F0B90B; } .rs-proposed { color: #4A9CFF; }
</style>
