<template>
  <div class="mixllm">
    <!-- LLM 服务健康(testauto /infra 同款:熔断器状态+手动恢复) -->
    <div class="card" :class="{cbopen: d.circuit_open}">
      <div class="chd"><b>LLM 服务健康</b>
        <span class="hdr">
          <el-tag size="small" :type="d.circuit_open ? 'danger' : (d.status==='ok' ? 'success' : 'info')" effect="dark">
            {{ d.circuit_open ? '熔断中' : (d.status || '—') }}</el-tag>
          <el-button v-if="d.circuit_open" size="small" type="danger" plain :loading="resetting" @click="resetCircuit">手动恢复</el-button>
          <el-button size="small" @click="load">刷新</el-button>
        </span>
      </div>
      <div class="hgrid">
        <div class="hcell"><span>主模型</span><b class="mono">{{ d.primary_model || d.model || '—' }}</b>
          <i v-if="d.primary_relay">{{ d.primary_relay }}</i></div>
        <div class="hcell"><span>降级模型</span><b class="mono warn2">{{ d.fallback_model || '—' }}</b></div>
        <div class="hcell"><span>当前生效</span><b class="mono" :class="{warn2: d.degraded}">{{ d.model || '—' }}</b>
          <i v-if="d.degraded" class="warn2">已降级到备用站</i><i v-else-if="d.relay">{{ d.relay }}</i></div>
        <div class="hcell"><span>连续失败</span>
          <b :class="(d.recent_failures||0) > 0 ? 'warn2' : ''">{{ d.recent_failures ?? 0 }} / {{ d.failure_threshold ?? '—' }}</b></div>
        <div class="hcell"><span>熔断/退避</span>
          <b>{{ d.consecutive_trips || 0 }} 次触发 · 冷却 {{ d.current_cooldown_s || '—' }}s</b>
          <i>{{ d.failure_threshold || 2 }}连败→120s×2ⁿ 指数退避,封顶1h</i></div>
        <div class="hcell"><span>最近一轮延迟</span><b>{{ d.latency_ms ? d.latency_ms + ' ms' : '—' }}</b>
          <i>{{ ts }}</i></div>
        <div class="hcell" v-if="d.usage"><span>tokens(in/out)</span>
          <b class="mono">{{ d.usage.prompt_tokens }} / {{ d.usage.completion_tokens }}</b></div>
      </div>
      <div v-if="d.circuit_open" class="cbline">⚠ 熔断中(第{{ d.consecutive_trips }}次):advisor 跳轮不调用,自动到期恢复;或点「手动恢复」立即复位</div>
    </div>

    <!-- 中转站管理(主账号/备用账号各可挂多地址·热加载,advisor 每轮 15min 生效) -->
    <div class="card">
      <div class="chd"><b>中转站管理</b><small>主账号 + 备用账号,每个账号可挂多个地址(调用不同模型)· 失效转移=启用主账号地址优先,再启用备用地址 · 热加载</small></div>

      <template v-for="grp in accountGroups" :key="grp.role">
        <div class="acchd">
          <span class="accname">{{ grp.label }}</span>
          <span class="dim">{{ grp.list.length }} 个地址 · {{ grp.list.filter(x=>x.enabled).length }} 启用</span>
          <span class="spacer" />
          <el-button size="small" type="warning" plain @click="openAdd(grp.role)">+ 添加地址</el-button>
        </div>
        <div v-if="showAdd===grp.role" class="addbox">
          <input v-model="nr.name" class="inp" :placeholder="grp.role==='primary'?'名称,如 主站-地址2':'名称,如 shengshengToken'" />
          <input v-model="nr.base_url" class="inp wide" placeholder="OpenAI兼容地址,如 https://api.xxx.com/v1" />
          <input v-model="nr.api_key" class="inp wide" type="password" placeholder="API Key" />
          <input v-model="nr.model" class="inp" placeholder="模型,如 gpt-5.5" />
          <el-button size="small" type="warning" @click="addRelay(grp.role)">添加到{{ grp.label }}</el-button>
          <el-button size="small" @click="showAdd=null">取消</el-button>
        </div>
        <div v-if="!grp.list.length" class="dim" style="padding:6px 4px 10px">此账号暂无地址,点「+ 添加地址」</div>

        <div v-for="rs in grp.list" :key="rs.id" class="rsrow" :class="{primary: rs.role==='primary'}">
        <div class="rshd" @click="expand = expand===rs.id ? null : rs.id">
          <span class="rolebadge" :class="rs.role">{{ rs.role==='primary' ? '主' : '备' }}</span>
          <b>{{ rs.name }}</b>
          <span class="tagx" :class="rs.enabled ? 'ok' : 'bad'">{{ rs.enabled ? '启用' : '停用' }}</span>
          <span class="mono dim">{{ rs.model }}</span>
          <span class="mono dim host">{{ hostOf(rs.base_url) }}</span>
          <span class="spacer" />
          <el-button size="small" text type="warning" @click.stop="moveAccount(rs)">移到{{ rs.role==='primary'?'备用':'主' }}账号</el-button>
          <el-button size="small" text :type="rs.enabled ? 'danger' : 'success'" @click.stop="toggle(rs)">{{ rs.enabled ? '停用' : '启用' }}</el-button>
          <el-button size="small" text type="danger" @click.stop="del(rs)">删除</el-button>
          <span class="dim">{{ expand===rs.id ? '▼' : '▶' }}</span>
        </div>
        <div v-if="expand===rs.id" class="rsbody">
          <div class="frow"><label>地址</label><input v-model="rs.base_url" class="inp wide" /></div>
          <div class="frow"><label>API Key</label>
            <input v-model="rs._newKey" class="inp wide" type="password" :placeholder="`留空保留(${rs.api_key_masked})`" /></div>
          <div class="frow"><label>模型({{ (rs.available_models||[]).length }})</label>
            <el-select v-model="rs.model" filterable allow-create default-first-option size="small" style="width:220px"
                       placeholder="选择或输入任意模型名">
              <el-option v-for="m in rs.available_models" :key="m" :value="m" :label="m" />
            </el-select>
            <el-button size="small" type="warning" plain :loading="rs._testing" @click="testModel(rs)">⚡ 测试模型</el-button>
            <el-button size="small" :loading="rs._refreshing" @click="refreshModels(rs)">🔄 拉取模型列表</el-button>
            <input v-model="rs._newModel" class="inp" placeholder="手动加模型名" @keyup.enter="addCustomModel(rs)" />
            <el-button size="small" @click="addCustomModel(rs)">+ 加入列表</el-button>
          </div>
          <div class="frow cmrow" v-if="(rs.custom_models||[]).length"><label>手动名单</label>
            <span v-for="m in rs.custom_models" :key="m" class="cmchip" :class="{cur: m===rs.model, ok: (rs._chipTest||{})[m]==='ok', bad: (rs._chipTest||{})[m]==='bad'}">
              <b class="cmname" :title="m===rs.model ? '当前使用中' : '点击设为当前模型'" @click="useModel(rs, m)">
                <i v-if="m===rs.model" class="cmcur">●</i>{{ m }}
              </b>
              <i class="cmact test" title="测试此模型(真调一次)" @click="testModel(rs, m)">
                {{ (rs._chipTesting||{})[m] ? '…' : ((rs._chipTest||{})[m]==='ok' ? '✓' : (rs._chipTest||{})[m]==='bad' ? '✗' : '⚡') }}
              </i>
              <i class="cmact use" v-if="m!==rs.model" title="设为当前模型" @click="useModel(rs, m)">启用</i>
              <i class="cmact rm" title="从手动名单移除(保存后生效)" @click="removeCustomModel(rs, m)">×</i>
            </span>
            <i class="dim">⚡测试真调一次 · 「启用」设为当前模型 · ×移除;测试/移除/启用后点「保存配置」持久化</i>
          </div>
          <div class="frow"><label>单价 $/1M</label>
            <span class="dim">in</span><input v-model.number="rs.price_in_per_m" class="inp num" type="number" step="0.1" />
            <span class="dim">out</span><input v-model.number="rs.price_out_per_m" class="inp num" type="number" step="0.1" />
            <span class="dim">(每日消费成本按此折算)</span></div>
          <div class="frow">
            <el-button size="small" type="warning" @click="save(rs)">保存配置(热生效)</el-button>
            <span v-if="rs._st" class="stmsg" :class="{okc: rs._st.startsWith('✅')}">{{ rs._st }}</span>
          </div>
        </div>
        </div>
      </template>
      <div v-if="!relays.length" class="dim" style="text-align:center;padding:14px">尚无中转站——添加后 advisor 自动切换到管理配置;未添加时回落引擎 env 单站</div>
    </div>

    <!-- AI 智能体接入(开关+运维助手回答范围;写单行权威表→dcm:llm:config 热生效) -->
    <div class="card">
      <div class="chd"><b>AI 智能体接入</b><small>开关热生效:运维助手=下次对话即生效;评审顾问=下轮(≤15min)生效,停用即跳轮不烧钱</small></div>
      <div class="agrid">
        <div class="agrow">
          <el-switch v-model="ag.advisor_enabled" @change="saveAgents" />
          <div class="agtxt"><b>LLM 评审顾问</b><i>每 15 分钟组合级评审(dcm:advisor:llm)·只读只建议,顾问播报的数据源</i></div>
        </div>
        <div class="agrow">
          <el-switch v-model="ag.ops_chat_enabled" @change="saveAgents" />
          <div class="agtxt"><b>运维助手</b><i>右下 AI 浮框对话·注入实时系统快照·永远无执行权</i></div>
        </div>
        <div class="agrow">
          <el-radio-group v-model="ag.chat_scope" size="small" :disabled="!ag.ops_chat_enabled" @change="saveAgents">
            <el-radio-button value="site">限本站</el-radio-button>
            <el-radio-button value="open">无限制</el-radio-button>
          </el-radio-group>
          <div class="agtxt"><b>运维助手回答范围</b><i>限本站=只答系统运维话题,跑题礼貌拉回;无限制=可自由聊天,涉本站数据仍只依据快照绝不编造</i></div>
        </div>
      </div>
      <div v-if="agSt" class="dim" style="margin-top:6px">{{ agSt }}</div>
    </div>

    <!-- 每日消费明细 -->
    <div class="card">
      <div class="chd"><b>每日消费明细</b><small>llm_usage_log 逐调用真账(含失败),成本=tokens×中转站单价</small>
        <span class="hdr">
          <el-radio-group v-model="usageDays" size="small" @change="loadUsage">
            <el-radio-button :value="7">7天</el-radio-button><el-radio-button :value="14">14天</el-radio-button><el-radio-button :value="30">30天</el-radio-button>
          </el-radio-group>
        </span>
      </div>
      <div class="statbar" v-if="usage.rows?.length">
        <span>今日 <b class="mono">{{ fmtInt(todayTokens) }}</b> tokens · <b>{{ todayCalls }}</b> 次</span>
        <span>{{ usageDays }}天合计 <b class="mono">{{ fmtInt(sumTokens) }}</b> tokens</span>
        <span>估算成本 <b class="mono gold">${{ sumCost.toFixed(4) }}</b></span>
        <span v-if="sumFails" class="warn2">失败 {{ sumFails }} 次</span>
      </div>
      <el-table :data="usage.rows || []" size="small" max-height="320">
        <el-table-column prop="date" label="日期" width="100" />
        <el-table-column prop="relay" label="中转站" width="110" />
        <el-table-column prop="model" label="模型" width="140" show-overflow-tooltip />
        <el-table-column prop="calls" label="调用" width="60" align="right" />
        <el-table-column label="失败" width="60" align="right">
          <template #default="{row}"><span :class="row.fails ? 'warn2' : 'dim'">{{ row.fails }}</span></template>
        </el-table-column>
        <el-table-column label="tokens in/out" width="130" align="right">
          <template #default="{row}"><span class="mono">{{ fmtInt(row.tokens_in) }} / {{ fmtInt(row.tokens_out) }}</span></template>
        </el-table-column>
        <el-table-column prop="avg_latency_ms" label="均延迟ms" width="90" align="right" />
        <el-table-column label="成本$" width="90" align="right">
          <template #default="{row}"><span class="mono gold">{{ row.cost_usd.toFixed(4) }}</span></template>
        </el-table-column>
        <el-table-column />
      </el-table>
      <div v-if="!(usage.rows||[]).length" class="dim" style="text-align:center;padding:10px">暂无用量记录(advisor 每 15 分钟一轮,部署后自然累积)</div>
    </div>

    <!-- 最近评审意见 + 建议历史(原有保留) -->
    <div class="card">
      <div class="chd"><b>最近评审意见(commentary)</b></div>
      <pre class="cmt">{{ d.commentary || '（暂无）' }}</pre>
    </div>
    <div class="card">
      <div class="chd"><b>建议历史(llm_advice_log · shadow 对照证据链)</b>
        <el-button size="small" @click="loadHist">刷新</el-button>
      </div>
      <el-table :data="hist" size="small" max-height="420">
        <el-table-column prop="ts" label="时间" width="110" />
        <el-table-column prop="model" label="模型" width="110" show-overflow-tooltip />
        <el-table-column prop="symbol" label="币种" width="110">
          <template #default="{row}">{{ row.symbol || '组合级' }}</template>
        </el-table-column>
        <el-table-column label="动作" width="90">
          <template #default="{row}">
            <el-tag size="small" effect="plain"
                    :type="{endorse:'success',caution:'warning',avoid:'danger',watch:'info'}[row.action]||'info'">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="理由" min-width="260" show-overflow-tooltip />
        <el-table-column prop="latency_ms" label="延迟ms" width="80" align="right" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const d = ref({})
const hist = ref([])
const relays = ref([])
const usage = ref({})
const usageDays = ref(14)
const expand = ref(null)
const showAdd = ref(null)   // 'primary' | 'backup' | null:哪个账号正在展开添加框
const resetting = ref(false)
const nr = reactive({ name: '', base_url: 'https://api.chesspnt.com/v1', api_key: '', model: '' })
const hostOf = u => String(u || '').replace(/^https?:\/\//, '').split('/')[0]
const accountGroups = computed(() => [
  { role: 'primary', label: '主账号', list: relays.value.filter(x => x.role === 'primary') },
  { role: 'backup', label: '备用账号', list: relays.value.filter(x => x.role !== 'primary') },
])
const ts = computed(() => d.value.ts ? new Date(d.value.ts * 1000).toLocaleString() : '—')
const fmtInt = n => (n != null ? Number(n).toLocaleString() : '—')
const today = () => new Date().toISOString().slice(0, 10)
const todayRows = computed(() => (usage.value.rows || []).filter(r => r.date === today()))
const todayTokens = computed(() => todayRows.value.reduce((s, r) => s + r.tokens_in + r.tokens_out, 0))
const todayCalls = computed(() => todayRows.value.reduce((s, r) => s + r.calls, 0))
const sumTokens = computed(() => (usage.value.rows || []).reduce((s, r) => s + r.tokens_in + r.tokens_out, 0))
const sumCost = computed(() => (usage.value.rows || []).reduce((s, r) => s + (r.cost_usd || 0), 0))
const sumFails = computed(() => (usage.value.rows || []).reduce((s, r) => s + (r.fails || 0), 0))

let t
async function load() { try { d.value = await mixApi.system.llm() } catch (e) { /* 降级 */ } }
async function loadHist() { try { hist.value = await mixApi.llmHistory() } catch (e) { hist.value = [] } }
async function loadRelays() {
  try {
    const r = await mixApi.system.llmRelays()
    relays.value = (r.items || []).map(x => ({ ...x, _newKey: '', _newModel: '', _refreshing: false, _testing: false, _chipTesting: {}, _chipTest: {}, _st: '' }))
  } catch (e) { relays.value = [] }
}
async function loadUsage() { try { usage.value = await mixApi.system.llmUsageDaily(usageDays.value) } catch (e) { usage.value = {} } }

async function resetCircuit() {
  resetting.value = true
  try { await mixApi.system.llmCircuitReset(); ElMessage.success('熔断器已重置,advisor 下轮恢复调用'); load() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '重置失败') }
  finally { resetting.value = false }
}
function openAdd(role) {
  showAdd.value = showAdd.value === role ? null : role
  Object.assign(nr, { name: '', api_key: '', model: '', base_url: 'https://api.chesspnt.com/v1' })
}
async function addRelay(role) {
  try {
    const r = await mixApi.system.llmRelayAdd({ ...nr })
    // 新增默认 role=backup;若加到主账号则移动过去
    if (role === 'primary' && r?.item?.id) { try { await mixApi.system.llmRelayRole(r.item.id, 'primary') } catch (e) { /* 忽略 */ } }
    ElMessage.success(`已添加到${role === 'primary' ? '主账号' : '备用账号'};热配置已发布`)
    showAdd.value = null; Object.assign(nr, { name: '', api_key: '', model: '' })
    loadRelays()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '添加失败') }
}
async function save(rs) {
  try {
    // 防丢单:el-select allow-create 直接敲出来的模型名只落在 rs.model,不在名单里——
    // 保存时自动并入手动名单,否则下次加载从列表消失(「保存后列表没新模型」的根因之一)
    if (rs.model && !(rs.available_models || []).includes(rs.model)) {
      rs.custom_models = Array.from(new Set([...(rs.custom_models || []), rs.model]))
    }
    await mixApi.system.llmRelaySave(rs.id, {
      name: rs.name, base_url: rs.base_url, api_key: rs._newKey || '',
      model: rs.model, price_in_per_m: rs.price_in_per_m, price_out_per_m: rs.price_out_per_m,
      custom_models: rs.custom_models,
    })
    // 保存后从服务器回读(权威口径),不再依赖本地态——所见即所存
    await loadRelays()
    const fresh = relays.value.find(x => x.id === rs.id)
    if (fresh) {
      fresh._st = '✅ 已保存并发布(advisor 下轮生效)'
      setTimeout(() => { fresh._st = '' }, 4000)
    }
  } catch (e) { rs._st = '❌ ' + (e?.detail || e?.error || '保存失败') }
}
function addCustomModel(rs) {
  const m = String(rs._newModel || '').trim()
  if (!m) return
  rs.custom_models = Array.from(new Set([...(rs.custom_models || []), m]))
  rs.available_models = Array.from(new Set([...(rs.available_models || []), m])).sort()
  rs._newModel = ''
  rs._st = `已加入列表:${m}(点「保存配置」持久化)`
}
function removeCustomModel(rs, m) {
  rs.custom_models = (rs.custom_models || []).filter(x => x !== m)
  rs.available_models = (rs.available_models || []).filter(x => x !== m)
  rs._st = `已从手动名单移除:${m}(点「保存配置」持久化)`
}
// 真调一次指定模型(不传=下拉当前选中);手动名单 chip 也复用此函数,按 model 记录 ✓/✗
async function testModel(rs, model) {
  const m = String(model || rs.model || '').trim()
  if (!m) { rs._st = '❌ 先选择/输入模型'; return }
  const chip = model != null
  if (chip) { rs._chipTesting = { ...(rs._chipTesting || {}), [m]: true } }
  else { rs._testing = true }
  rs._st = `测试 ${m} 中...`
  try {
    const r = await mixApi.system.llmRelayTest(rs.id, m)
    rs._st = r.ok
      ? `✅ ${r.model} 可用 · ${r.latency_ms}ms · 回复:${r.reply}`
      : `❌ ${r.model} 不可用(${r.latency_ms}ms):${r.error}`
    if (chip) rs._chipTest = { ...(rs._chipTest || {}), [m]: r.ok ? 'ok' : 'bad' }
  } catch (e) {
    rs._st = '❌ ' + (e?.detail || e?.error || '测试失败')
    if (chip) rs._chipTest = { ...(rs._chipTest || {}), [m]: 'bad' }
  } finally {
    if (chip) { const t = { ...(rs._chipTesting || {}) }; delete t[m]; rs._chipTesting = t }
    else rs._testing = false
  }
}
// 从名单里把某模型设为该站当前生效模型(启用);写下拉 v-model,需「保存配置」持久化+发布
function useModel(rs, m) {
  if (rs.model === m) return
  rs.model = m
  rs._st = `已设为当前模型:${m}（点「保存配置」持久化并热发布）`
}
async function moveAccount(rs) {
  const to = rs.role === 'primary' ? 'backup' : 'primary'
  try {
    await mixApi.system.llmRelayRole(rs.id, to)
    ElMessage.success(`已移到${to === 'primary' ? '主账号' : '备用账号'}`)
    loadRelays()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '失败') }
}
async function toggle(rs) {
  try { await mixApi.system.llmRelayToggle(rs.id, !rs.enabled); loadRelays() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '失败') }
}
async function del(rs) {
  try {
    await ElMessageBox.confirm(`删除中转站「${rs.name}」?`, '删除', { type: 'warning' })
    await mixApi.system.llmRelayDel(rs.id); loadRelays()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '失败') }
}
async function refreshModels(rs) {
  rs._refreshing = true
  try {
    const r = await mixApi.system.llmRelayModels(rs.id)
    // 与本地未保存的手动名单合并——原先直接替换会把刚「加入列表」还没保存的模型冲掉(根因之二)
    if (r.ok) { rs.available_models = Array.from(new Set([...(r.available_models || []), ...(rs.custom_models || [])])).sort(); rs._st = `✅ ${r.count} 模型` }
    else rs._st = '❌ ' + r.error
  } catch (e) { rs._st = '❌ ' + (e?.detail || e?.error || '失败') }
  finally { rs._refreshing = false; setTimeout(() => { rs._st = '' }, 5000) }
}

// ---- AI 智能体接入 ----
const ag = reactive({ advisor_enabled: true, ops_chat_enabled: true, chat_scope: 'site' })
const agSt = ref('')
async function loadAgents() { try { Object.assign(ag, await mixApi.system.llmAgentsGet()) } catch (e) { /* 默认全开 */ } }
async function saveAgents() {
  try {
    const r = await mixApi.system.llmAgentsPut({ ...ag })
    Object.assign(ag, r.agents || {})
    agSt.value = `✅ 已保存并热发布:评审顾问=${ag.advisor_enabled ? '开' : '关'} · 运维助手=${ag.ops_chat_enabled ? '开' : '关'} · 范围=${ag.chat_scope === 'open' ? '无限制' : '限本站'}`
    setTimeout(() => { agSt.value = '' }, 5000)
  } catch (e) {
    agSt.value = '❌ ' + (e?.detail || e?.error || '保存失败')
    loadAgents()
  }
}

onMounted(() => { load(); loadHist(); loadRelays(); loadUsage(); loadAgents(); t = setInterval(load, 30000) })
onUnmounted(() => clearInterval(t))
</script>

<style scoped lang="scss">
.mixllm { display: flex; flex-direction: column; gap: 12px; max-width: 1080px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 12px 14px;
  &.cbopen { border-color: rgba(246,70,93,.6); } }
.chd { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; b { font-size: 13px; }
  small { color: var(--el-text-color-placeholder); font-size: 10.5px; flex: 1; } .hdr { margin-left: auto; display: flex; gap: 8px; align-items: center; } }
.hgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
.hcell { display: flex; flex-direction: column; gap: 2px; border: 1px solid rgba(255,255,255,.05); border-radius: 6px; padding: 6px 9px;
  span { font-size: 10px; color: var(--el-text-color-placeholder); } b { font-size: 12.5px; }
  i { font-style: normal; font-size: 9.5px; color: var(--el-text-color-placeholder); } }
.cbline { margin-top: 8px; font-size: 11px; color: #F6465D; }
.mono { font-family: monospace; }
.gold { color: #F0B90B; }
.warn2 { color: #f59e0b; }
.dim { color: var(--el-text-color-placeholder); font-size: 11px; }
.okc { color: #0ECB81 !important; }
.acchd { display: flex; align-items: center; gap: 10px; margin: 12px 0 6px; padding-bottom: 4px; border-bottom: 1px solid var(--mix-border, #262B33);
  .accname { font-size: 12.5px; font-weight: 800; color: #F0B90B; } .spacer { flex: 1; } }
.acchd:first-of-type { margin-top: 4px; }
.addbox { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; border: 1px dashed rgba(240,185,11,.4); border-radius: 6px; padding: 10px; margin-bottom: 10px; }
.rshd .host { font-size: 10px; opacity: .7; }
.inp { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF; font-size: 11.5px; padding: 5px 8px; width: 150px;
  &.wide { width: 300px; } &.num { width: 64px; text-align: right; }
  &:focus { outline: none; border-color: #F0B90B; } }
.rsrow { border: 1px solid var(--mix-border, #262B33); border-radius: 8px; margin-bottom: 8px; overflow: hidden;
  &.primary { border-color: rgba(240,185,11,.5); } }
.rshd { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer; background: rgba(255,255,255,.02);
  b { font-size: 12.5px; } .spacer { flex: 1; } }
.rolebadge { font-size: 10px; font-weight: 800; border-radius: 4px; padding: 1px 7px;
  &.primary { background: rgba(240,185,11,.2); color: #F0B90B; }
  &.backup { background: rgba(255,255,255,.06); color: var(--el-text-color-secondary); } }
.tagx { font-size: 10px; border-radius: 4px; padding: 1px 7px;
  &.ok { background: rgba(14,203,129,.15); color: #0ECB81; } &.bad { background: rgba(246,70,93,.15); color: #F6465D; } }
.rsbody { padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }
.frow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  label { font-size: 11px; color: var(--el-text-color-secondary); width: 88px; } }
.stmsg { font-size: 11px; color: #F6465D; }
.statbar { display: flex; gap: 18px; font-size: 11.5px; color: var(--el-text-color-secondary); padding: 4px 2px 10px;
  b { color: #EAECEF; } }
.cmrow { align-items: flex-start; }
.cmchip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid rgba(240,185,11,.35); background: rgba(240,185,11,.08);
  color: #F0B90B; border-radius: 12px; padding: 2px 6px 2px 9px; font-size: 10.5px; margin: 0 6px 6px 0; font-family: monospace;
  &.cur { border-color: #F0B90B; font-weight: 700; background: rgba(240,185,11,.16); }
  &.ok { border-color: rgba(14,203,129,.5); } &.bad { border-color: rgba(246,70,93,.5); }
  .cmname { display: inline-flex; align-items: center; gap: 3px; cursor: pointer; &:hover { text-decoration: underline; }
    .cmcur { font-style: normal; color: #0ECB81; font-size: 8px; } }
  .cmact { font-style: normal; cursor: pointer; border-radius: 8px; padding: 0 5px; font-size: 10px; line-height: 16px;
    &.test { background: rgba(240,185,11,.18); &:hover { background: rgba(240,185,11,.35); } }
    &.use { background: rgba(14,203,129,.16); color: #0ECB81; &:hover { background: rgba(14,203,129,.32); } }
    &.rm { color: var(--el-text-color-placeholder); &:hover { color: #F6465D; } } }
  &.ok .cmact.test { color: #0ECB81; } &.bad .cmact.test { color: #F6465D; } }
.agrid { display: flex; flex-direction: column; gap: 10px; }
.agrow { display: flex; align-items: center; gap: 12px; }
.agtxt { display: flex; flex-direction: column; gap: 1px;
  b { font-size: 12px; } i { font-style: normal; font-size: 10.5px; color: var(--el-text-color-placeholder); } }
.cmt { font-size: 12px; color: var(--mix-t1, #EAECEF); white-space: pre-wrap; max-height: 320px; overflow: auto; margin: 0; }
</style>
