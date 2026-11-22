<template>
  <div class="strategies-page">

    <!-- ===== 策略运行状态栏（只读监控） ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary px-4 py-3 mb-4">
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-2">
          <div class="w-2.5 h-2.5 rounded-full" :class="runningStrategies.length ? 'bg-green-500 animate-pulse' : 'bg-gray-500'"></div>
          <span class="text-sm font-semibold">策略运行状态</span>
          <span class="text-xs text-text-tertiary">({{ runningStrategies.length }} 个运行中)</span>
        </div>
        <button @click="fetchRunningStrategies" class="text-xs text-primary hover:text-primary-hover">刷新</button>
      </div>
      <div v-if="runningStrategies.length" class="flex flex-wrap gap-2">
        <div v-for="rs in runningStrategies" :key="rs.strategy_id || rs.id"
          class="flex items-center gap-2 bg-dark-200 rounded-lg px-3 py-1.5 text-xs">
          <div class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div>
          <span class="font-medium text-text-primary">{{ rs.strategy_type || rs.name || rs.strategy_id }}</span>
          <span v-if="rs.pair_code" class="text-primary font-bold">{{ rs.pair_code }}</span>
          <span class="text-text-tertiary">{{ rs.status || '运行中' }}</span>
          <button @click="stopStrategy(rs)" class="text-red-400 hover:text-red-300 font-bold ml-1">停止</button>
        </div>
      </div>
      <div v-else class="text-xs text-text-tertiary">暂无运行中的策略</div>
    </div>

    <!-- 只读说明 -->
    <div class="mb-4 px-4 py-2.5 bg-blue-900/15 border border-blue-800/40 rounded-lg flex items-start gap-2">
      <span class="text-blue-400 text-sm leading-none mt-0.5">ℹ</span>
      <div class="text-xs text-text-secondary leading-relaxed">
        本页为<b class="text-text-primary">只读引擎时序预览</b>：展示「自动阶梯式套利」连续执行链路与全局执行引擎参数（超时/重试/单腿检查延迟等，对所有用户策略生效）。
        参数由系统统一调优，<b class="text-text-primary">此处不提供修改入口</b>；时段风控请到「Guard 规则」页。
      </div>
    </div>

    <!-- ===== 视图切换（引擎配置内 2 Tab） ===== -->
    <div class="flex gap-2 mb-4">
      <button @click="viewMode = 'workflow'" :class="['px-4 py-1.5 rounded-lg text-sm font-medium border transition-colors', viewMode === 'workflow' ? 'bg-primary text-dark-300 border-primary' : 'bg-dark-100 text-text-secondary border-border-primary']">流程预览</button>
      <button @click="viewMode = 'compare'; loadAllEffective()" :class="['px-4 py-1.5 rounded-lg text-sm font-medium border transition-colors', viewMode === 'compare' ? 'bg-primary text-dark-300 border-primary' : 'bg-dark-100 text-text-secondary border-border-primary']">四策略参数对比</button>
    </div>

    <!-- ===== 四策略并排对比视图（只读诊断） ===== -->
    <div v-if="viewMode === 'compare'" class="bg-dark-100 rounded-2xl border border-border-primary overflow-hidden mb-4">
      <div class="px-4 py-3 border-b border-border-secondary">
        <span class="font-semibold text-sm">四策略参数对比</span>
        <span class="text-xs text-text-tertiary ml-2">差异项高亮显示（只读）</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead><tr class="border-b border-border-secondary text-text-tertiary">
            <th class="text-left px-4 py-2.5 sticky left-0 bg-dark-100 min-w-[160px]">参数</th>
            <th v-for="t in strategyTypes" :key="t.type" class="text-center px-3 py-2.5 min-w-[120px]">
              <span class="font-bold" :class="t.type === activeType ? 'text-primary' : ''">{{ t.label }}</span>
            </th>
          </tr></thead>
          <tbody>
            <template v-for="grp in configGroups" :key="grp.key">
              <tr class="bg-dark-50"><td :colspan="5" class="px-4 py-1.5 font-bold text-text-secondary text-[10px]">{{ grp.label }}</td></tr>
              <tr v-for="f in configFields.filter(x => x.group === grp.key)" :key="f.key"
                class="border-b border-border-secondary hover:bg-dark-50" :class="isFieldDifferent(f.key) ? 'bg-yellow-900/10' : ''">
                <td class="px-4 py-2 text-text-secondary sticky left-0 bg-dark-100">{{ f.label }} <span class="text-text-tertiary">({{ f.unit }})</span></td>
                <td v-for="t in strategyTypes" :key="t.type" class="text-center px-3 py-2 font-mono"
                  :class="isFieldDifferent(f.key) && compareEffective[t.type]?.[f.key] !== compareMinVal(f.key) ? 'font-bold text-primary' : 'text-text-primary'">
                  {{ compareEffective[t.type]?.[f.key] ?? '--' }}
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 策略类型选择卡 (only in workflow mode) -->
    <div v-show="viewMode === 'workflow'" class="type-selector">
      <div
        v-for="t in strategyTypes" :key="t.type"
        @click="switchStrategy(t.type)"
        :class="['type-card', activeType === t.type && 'active']"
      >
        <span class="type-icon">{{ t.icon }}</span>
        <span class="type-label">{{ t.label }}</span>
      </div>
    </div>

    <!-- ── VueFlow 工作流画布（只读全链路预览） ── -->
    <div v-show="viewMode === 'workflow'" class="workflow-canvas">
      <div class="canvas-header">
        <div class="header-left">
          <h2>{{ strategyName }} · 自动阶梯套利执行全链路</h2>
          <span class="readonly-badge">🔒 只读预览</span>
        </div>
        <div class="header-actions">
          <div class="legend">
            <span class="lg-item"><span class="lg-dot main"></span>主干</span>
            <span class="lg-item"><span class="lg-dot guard"></span>护栏旁路</span>
            <span class="lg-item"><span class="lg-dot recover"></span>循环/恢复</span>
          </div>
        </div>
      </div>

      <VueFlow
        v-model="elements"
        :default-zoom="0.6"
        :min-zoom="0.3"
        :max-zoom="1.5"
        :nodes-draggable="false"
        :nodes-connectable="false"
        :elements-selectable="false"
        class="workflow-flow"
      >
        <Background />
        <Controls />

        <template #node-custom="{ data }">
          <div :class="['custom-node', data.type]">
            <div class="node-header">
              <span class="node-icon">{{ data.icon }}</span>
              <span class="node-title">{{ data.label }}</span>
            </div>
            <div v-if="data.params && data.params.length" class="node-content">
              <div v-for="param in data.params" :key="param.key" class="param-row-ro">
                <span class="param-label-ro">{{ param.label }}</span>
                <span class="param-val-ro">{{ param.value }}<span class="param-unit-ro">{{ param.unit }}</span></span>
              </div>
            </div>
            <div v-if="data.description" class="node-description">{{ data.description }}</div>
            <div v-if="data.impact" class="node-impact">💡 {{ data.impact }}</div>
          </div>
        </template>
      </VueFlow>
    </div>

    <!-- ── 当前有效引擎参数（只读展示，替代原 CRUD） ── -->
    <div v-show="viewMode === 'workflow'" class="crud-section">
      <div class="crud-header" @click="crudOpen = !crudOpen">
        <span class="font-semibold text-sm">当前有效引擎参数（{{ strategyName }}）</span>
        <span class="text-xs text-text-tertiary">{{ crudOpen ? '▲ 收起' : '▼ 展开' }}</span>
      </div>
      <template v-if="crudOpen">
        <div v-if="effectiveConfig" class="effective-bar">
          <div class="flex items-center gap-2 mb-2">
            <div class="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
            <span class="text-sm font-bold text-primary">当前有效配置</span>
            <span class="text-xs text-text-tertiary">{{ effectiveConfig.config_level || 'global' }} · {{ effectiveConfig.strategy_type || '全局' }}</span>
            <span class="text-[10px] text-text-tertiary ml-auto">优先级：实例 &gt; 策略类型 &gt; 全局</span>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
            <div v-for="f in configFields" :key="f.key">
              <div class="text-text-tertiary mb-0.5">{{ f.label }}</div>
              <div class="font-mono font-semibold">{{ effectiveConfig[f.key] ?? '--' }}{{ f.unit ?? '' }}</div>
            </div>
          </div>
        </div>
        <div v-else class="py-3 px-5 text-center text-xs text-text-tertiary">
          {{ loadingEffective ? '加载中...' : '当前策略类型暂无有效配置（将回退全局默认）' }}
        </div>
      </template>
    </div>

    <!-- Toast -->
    <Teleport to="body">
      <div v-if="toast.show" class="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-5 py-3 rounded-xl shadow-xl text-sm font-medium"
        :class="toast.type === 'success' ? 'bg-success text-dark-300' : 'bg-danger text-white'">
        {{ toast.msg }}
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import api from '@/services/api.js'

// ── 策略类型 ────────────────────────────────────────────────────
const strategyTypes = [
  { type: 'forward_opening',  label: '正套开仓',  icon: '↗' },
  { type: 'reverse_opening',  label: '反套开仓',  icon: '↙' },
  { type: 'forward_closing',  label: '正套平仓',  icon: '↘' },
  { type: 'reverse_closing',  label: '反套平仓',  icon: '↖' },
]

// 引擎参数字段 — 对应 strategy_timing_configs 表（只读展示/对比）
const configFields = [
  { key: 'trigger_check_interval', label: '触发检查间隔', unit: 's', group: 'trigger' },
  { key: 'opening_trigger_count',  label: '开仓触发次数', unit: '次', group: 'trigger' },
  { key: 'closing_trigger_count',  label: '平仓触发次数', unit: '次', group: 'trigger' },
  { key: 'binance_timeout',        label: 'Binance超时', unit: 's', group: 'order' },
  { key: 'bybit_timeout',          label: 'Bybit超时',   unit: 's', group: 'order' },
  { key: 'order_check_interval',   label: '订单检查间隔', unit: 's', group: 'order' },
  { key: 'spread_check_interval',  label: '点差监控间隔', unit: 's', group: 'order' },
  { key: 'mt5_deal_sync_wait',     label: 'MT5同步等待', unit: 's', group: 'order' },
  { key: 'api_spam_prevention_delay',             label: 'API防频繁延迟',  unit: 's', group: 'flow' },
  { key: 'delayed_single_leg_check_delay',        label: '单腿检测延迟',   unit: 's', group: 'flow' },
  { key: 'delayed_single_leg_second_check_delay', label: '单腿二次延迟',   unit: 's', group: 'flow' },
  { key: 'api_retry_times',          label: 'API重试次数',        unit: '次', group: 'retry' },
  { key: 'api_retry_delay',          label: 'API重试延迟',        unit: 's',  group: 'retry' },
  { key: 'max_binance_limit_retries',label: 'Binance最大轮询次数', unit: '次', group: 'retry' },
  { key: 'open_wait_after_cancel_no_trade',  label: '开仓撤单未成交等待', unit: 's', group: 'wait' },
  { key: 'open_wait_after_cancel_part',      label: '开仓撤单部分等待',   unit: 's', group: 'wait' },
  { key: 'close_wait_after_cancel_no_trade', label: '平仓撤单未成交等待', unit: 's', group: 'wait' },
  { key: 'close_wait_after_cancel_part',     label: '平仓撤单部分等待',   unit: 's', group: 'wait' },
  { key: 'status_polling_interval', label: '状态轮询间隔', unit: 's', group: 'frontend' },
  { key: 'debounce_delay',          label: '防抖延迟',     unit: 's', group: 'frontend' },
]

const configGroups = [
  { key: 'trigger',  label: '🎯 触发控制' },
  { key: 'order',    label: '📝 订单执行' },
  { key: 'flow',     label: '🔄 流程控制' },
  { key: 'retry',    label: '⚡ 重试配置' },
  { key: 'wait',     label: '⏳ 等待延迟' },
  { key: 'frontend', label: '🖥️ 前端交互' },
]

// ── 状态 ──────────────────────────────────────────────────────
const activeType       = ref('forward_opening')
const viewMode         = ref('workflow')
const crudOpen         = ref(false)
const configData       = ref({})
const effectiveConfig  = ref(null)
const loadingEffective = ref(false)
const runningStrategies = ref([])
const compareEffective = ref({})
const toast = ref({ show: false, type: 'success', msg: '' })

function showToast(type, msg) {
  toast.value = { show: true, type, msg }
  setTimeout(() => { toast.value.show = false }, 2600)
}

const strategyName = computed(() => ({
  forward_opening: '正向开仓', forward_closing: '正向平仓',
  reverse_opening: '反向开仓', reverse_closing: '反向平仓',
}[activeType.value] || activeType.value))

const isOpening = computed(() => activeType.value.endsWith('_opening'))

// ──────────────────────────────────────────────────────────────
// 自动阶梯套利全链路工作流（基于 continuous_executor V2 真实执行链路）
// 主干(main) + 护栏旁路(guard) + 循环/恢复(recover)
// 节点 data: { id, type, icon, label, description, impact, params:[{key,label,value,unit}] }
// params 仅用于只读展示；value 由 loadEffectiveIntoNodes() 用有效配置回填。
// ──────────────────────────────────────────────────────────────
function p(key, label, unit) { return { key, label, value: '--', unit } }

function makeElements(strategyType) {
  const opening = strategyType.endsWith('_opening')
  const triggerCountParam = opening
    ? p('opening_trigger_count', '开仓触发次数', '次')
    : p('closing_trigger_count', '平仓触发次数', '次')
  const X = (n) => n              // 列 x
  const Y = (n) => n              // 行 y
  const COL = { main: 360, guard: 0, side: 720 }

  const nodes = [
    // ── 主干（中列，自上而下） ──
    { id:'n1', type:'custom', position:{x:COL.main,y:Y(-40)}, data:{ id:'n1', type:'start', icon:'▶', label:'用户启动 → 构造执行器',
        description:'execute_continuous_opening/closing 读有效引擎参数(TimingConfig)注入执行器，写 strategy_active 键(TTL 3600s)', impact:'本页参数即此处注入的全局引擎参数', params:[] } },
    { id:'n2', type:'custom', position:{x:COL.main,y:Y(150)}, data:{ id:'n2', type:'loop', icon:'🔁', label:'V2 主循环 + 心跳',
        description:'while is_running and not stop_requested；每轮更新 _last_heartbeat（看门狗监控点）', impact:'挂死>90s→看门狗 cancel+开市自恢复', params:[] } },
    { id:'n3', type:'custom', position:{x:COL.main,y:Y(330)}, data:{ id:'n3', type:'sys', icon:'⚙', label:'热重载 / 活跃键刷新',
        description:'配置热重载(3s 回读DB重建阶梯mapper) + Redis 活跃键 30s 续期(防 scan 超时提前过期)', impact:'运行中改阶梯/参数≤3s生效', params:[] } },
    { id:'n4', type:'custom', position:{x:COL.main,y:Y(510)}, data:{ id:'n4', type:'data', icon:'📊', label:'读持仓 → 账本对账 → 读点差',
        description:'_get_live_position(8s超时) + flat 时清陈旧账本 + _get_current_spread', impact:'读取失败→sleep 触发间隔后重试',
        params:[ p('trigger_check_interval','触发检查间隔','s') ] } },
    { id:'n5', type:'custom', position:{x:COL.main,y:Y(700)}, data:{ id:'n5', type:'ladder', icon:'🪜', label:'阶梯定位（顺序填充）',
        description:'LadderRangeMapper 按持仓段定位活跃阶梯+remaining_capacity；先填满低阶再进高阶。12s 周期重判防锁死', impact:'持仓0却跳阶梯=选择器bug(已修为按段定位)', params:[] } },
    { id:'n6', type:'custom', position:{x:COL.main,y:Y(890)}, data:{ id:'n6', type:'trigger', icon:'🎯', label:'触发计数 + 二次校验',
        description:'轮询点差，累计满足 trigger_count 次进入下单；触发后再读点差二次确认仍达阈值，否则 reset', impact:'次数越多越稳、响应越慢',
        params:[ triggerCountParam, p('trigger_check_interval','检查间隔','s'), p('spread_check_interval','点差监控间隔','s') ] } },
    { id:'n7', type:'custom', position:{x:COL.main,y:Y(1080)}, data:{ id:'n7', type:'calc', icon:'🧮', label:'计算本轮下单量',
        description:'order_qty = min(order_qty_limit, remaining)；开仓再按 opening_ceiling 持仓上限钳制', impact:'容量护栏运行中缩容会撤在途单', params:[] } },
    { id:'n8', type:'custom', position:{x:COL.main,y:Y(1270)}, data:{ id:'n8', type:'order', icon:'📝', label:'A腿 Binance 限价单(POST_ONLY)',
        description:'挂单→轮询成交→点差朝不利方向偏离>容差则撤→超时撤单', impact:'撤单容差太紧→maker 老被撤(单向放宽0.35)',
        params:[ p('binance_timeout','挂单超时','s'), p('order_check_interval','成交检查间隔','s'), p('max_binance_limit_retries','最大轮询次数','次') ] } },
    { id:'n9', type:'custom', position:{x:COL.main,y:Y(1460)}, data:{ id:'n9', type:'bybit', icon:'⚡', label:'B腿 MT5 市价对冲',
        description:'A腿成交后按 hedge_multiplier 折算B腿手数下市价单；retcode 10018→标记停市冻结', impact:'未对冲零头(U.H.X)累积到下轮',
        params:[ p('bybit_timeout','下单等待','s'), p('mt5_deal_sync_wait','MT5成交同步等待','s') ] } },
    { id:'n10', type:'custom', position:{x:COL.main,y:Y(1650)}, data:{ id:'n10', type:'verify', icon:'🔄', label:'成交验证 / 补单',
        description:'读 MT5 deals 验证实际成交量，不足阈值则按重试次数补单', impact:'重试越多越保双边成交、越耗时',
        params:[ p('api_retry_times','补单重试次数','次'), p('api_retry_delay','重试间隔','s') ] } },
    { id:'n11', type:'custom', position:{x:COL.main,y:Y(1840)}, data:{ id:'n11', type:'record', icon:'🧾', label:'记账 + 前端推送',
        description:'record_opening/closing 累加主腿成交量、写 pos_open_ledger(平均点差/阶梯进度唯一源)，WS 推持仓快照', impact:'每轮成交量以 Binance 主腿计入',
        params:[ p('api_spam_prevention_delay','执行后防频繁延迟','s') ] } },
    { id:'n12', type:'custom', position:{x:COL.main,y:Y(2030)}, data:{ id:'n12', type:'complete', icon:'✅', label:'完成判断',
        description:'current_position ≥ total_qty → 进下一阶梯；平仓 position_exhausted(MT5无持仓) → 结束', impact:'未达总手数→回主循环下一轮', params:[] } },

    // ── 下单前置闸（主干右侧，紧贴 n8 之前的闸） ──
    { id:'g_pre', type:'custom', position:{x:COL.side,y:Y(1170)}, data:{ id:'g_pre', type:'gate', icon:'🚦', label:'下单前置闸（4道）',
        description:'① 清理遗留 s-挂单 ② MT5 trade_mode 预检(10s缓存) ③ MT5 临时停市冻结闸 ④ 交易网关准入', impact:'任一不过→defer 本轮不下单', params:[] } },
    // ── 异步单腿防线（主干右侧，紧贴 n11） ──
    { id:'s_leg', type:'custom', position:{x:COL.side,y:Y(1740)}, data:{ id:'s_leg', type:'check', icon:'🔍', label:'单腿防线（异步 Phase2）',
        description:'成交后延迟实盘总量对账：一腿成交另一腿缺口→大红告警+用户收口(只读)', impact:'延迟越长越准、告警越滞后',
        params:[ p('delayed_single_leg_check_delay','第一次检测延迟','s'), p('delayed_single_leg_second_check_delay','第二次检测延迟','s') ] } },

    // ── 横切护栏旁路（左列泳道，虚线接主循环） ──
    { id:'gv1', type:'custom', position:{x:COL.guard,y:Y(150)}, data:{ id:'gv1', type:'guard', icon:'🛡', label:'背离护栏',
        description:'ICMarkets XAUUSD vs Bybit XAU+ 中价背离：Redis quote_divergence:state，trip 0.7 软暂停 / recover 0.3 恢复', impact:'软暂停期只等不下单', params:[] } },
    { id:'gv2', type:'custom', position:{x:COL.guard,y:Y(330)}, data:{ id:'gv2', type:'guard', icon:'🕒', label:'停市护栏',
        description:'距 MT5 收盘≤15min 硬停(stop_reason=market_close)；开市自动恢复+预热(XAU 1min/ICXAU 2min)', impact:'休市期杜绝单腿', params:[] } },
    { id:'gv3', type:'custom', position:{x:COL.guard,y:Y(510)}, data:{ id:'gv3', type:'guard', icon:'📉', label:'滑点保护',
        description:'成交后比对实际点差：L1 偏离暂停(约3min自恢复)，L2 连续超阈需手动确认', impact:'maker 滑点两道护栏', params:[] } },
    { id:'gv4', type:'custom', position:{x:COL.guard,y:Y(700)}, data:{ id:'gv4', type:'guard', icon:'📦', label:'容量护栏',
        description:'运行中热重载把阶梯累计上限调小至<已开+在途→撤在途 s-单并结束本阶梯', impact:'仅撤策略自己的单(保留人工)', params:[] } },
    { id:'gv5', type:'custom', position:{x:COL.guard,y:Y(890)}, data:{ id:'gv5', type:'guard', icon:'💓', label:'心跳看门狗',
        description:'后台监控 _last_heartbeat，>90s 判挂死→强制 cancel+标记，开市由 ResumeMonitor 自恢复(15min>3次则停)', impact:'治"按钮在跑却不交易"', params:[] } },
    { id:'gv6', type:'custom', position:{x:COL.guard,y:Y(1080)}, data:{ id:'gv6', type:'guard', icon:'🛑', label:'紧急停止',
        description:'risk_monitor emergency_stop（Redis 键）激活→全员策略停下单', impact:'风控总闸', params:[] } },

    // ── 主干边 ──
    { id:'e1', source:'n1', target:'n2', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'} },
    { id:'e2', source:'n2', target:'n3', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'} },
    { id:'e3', source:'n3', target:'n4', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'} },
    { id:'e4', source:'n4', target:'n5', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'} },
    { id:'e5', source:'n5', target:'n6', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'}, label:'定位到活跃阶梯' },
    { id:'e6', source:'n6', target:'n7', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'}, label:'触发达成' },
    { id:'e7', source:'n7', target:'n8', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'} },
    { id:'e8', source:'n8', target:'n9', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'}, label:'A腿成交→对冲' },
    { id:'e9', source:'n9', target:'n10', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'} },
    { id:'e10', source:'n10', target:'n11', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'}, label:'达标→记账' },
    { id:'e11', source:'n11', target:'n12', type:'smoothstep', animated:true, style:{stroke:'#4CAF50'} },
    // 循环/恢复边
    { id:'e12', source:'n12', target:'n2', type:'smoothstep', style:{stroke:'#4ade80',strokeDasharray:'6,4'}, label:'未达总手数→下一轮' },
    { id:'e_break', source:'n12', target:'n5', type:'smoothstep', style:{stroke:'#4ade80',strokeDasharray:'6,4'}, label:'本阶梯满→重选阶梯' },
    // 前置闸 / 单腿
    { id:'e_pre', source:'g_pre', target:'n8', type:'smoothstep', style:{stroke:'#FF9800'}, label:'四闸通过才下单' },
    { id:'e_leg', source:'n11', target:'s_leg', type:'smoothstep', style:{stroke:'#a78bfa',strokeDasharray:'5,5'}, label:'异步对账' },
    // 护栏旁路（虚线汇入主循环）
    { id:'eg1', source:'gv1', target:'n2', type:'smoothstep', style:{stroke:'#f6465d',strokeDasharray:'4,4'} },
    { id:'eg2', source:'gv2', target:'n2', type:'smoothstep', style:{stroke:'#f6465d',strokeDasharray:'4,4'} },
    { id:'eg3', source:'gv3', target:'n2', type:'smoothstep', style:{stroke:'#f6465d',strokeDasharray:'4,4'} },
    { id:'eg4', source:'gv4', target:'n7', type:'smoothstep', style:{stroke:'#f6465d',strokeDasharray:'4,4'} },
    { id:'eg5', source:'gv5', target:'n2', type:'smoothstep', style:{stroke:'#f6465d',strokeDasharray:'4,4'} },
    { id:'eg6', source:'gv6', target:'n2', type:'smoothstep', style:{stroke:'#f6465d',strokeDasharray:'4,4'} },
  ]
  return nodes
}

const elements = ref(makeElements('forward_opening'))

// 将有效引擎参数回填到节点 params（只读展示）
function loadEffectiveIntoNodes() {
  const cfg = effectiveConfig.value || {}
  elements.value.forEach(el => {
    if (el.data && Array.isArray(el.data.params)) {
      el.data.params.forEach(prm => {
        if (cfg[prm.key] !== undefined && cfg[prm.key] !== null) prm.value = cfg[prm.key]
      })
    }
  })
}

// ── 切换策略类型（只读：重画节点 + 拉有效配置回填） ──
async function switchStrategy(type) {
  activeType.value = type
  elements.value = makeElements(type)
  await fetchEffective()
  loadEffectiveIntoNodes()
}

// ── 只读读取 ──────────────────────────────────────────────────
async function fetchEffective() {
  loadingEffective.value = true
  effectiveConfig.value = null
  try {
    const r = await api.get(`/api/v1/timing-configs/effective/${activeType.value}`)
    effectiveConfig.value = r.data
    configData.value = r.data || {}
  } catch { effectiveConfig.value = null }
  finally { loadingEffective.value = false }
}

async function fetchRunningStrategies() {
  try {
    const r = await api.get('/api/v1/automation/strategies/running')
    runningStrategies.value = Array.isArray(r.data) ? r.data : r.data?.strategies || []
  } catch { runningStrategies.value = [] }
}

async function stopStrategy(rs) {
  const id = rs.strategy_id || rs.id
  if (!id || !confirm('确定要停止策略 ' + (rs.strategy_type || id) + ' 吗？')) return
  try {
    await api.post('/api/v1/automation/strategies/' + id + '/stop')
    showToast('success', '策略已停止')
    await fetchRunningStrategies()
  } catch (e) { showToast('error', '停止失败: ' + (e.response?.data?.detail || e.message)) }
}

async function loadAllEffective() {
  const results = {}
  await Promise.all(strategyTypes.map(async t => {
    try {
      const r = await api.get('/api/v1/timing-configs/effective/' + t.type)
      results[t.type] = r.data
    } catch { results[t.type] = null }
  }))
  compareEffective.value = results
}

function isFieldDifferent(key) {
  const vals = strategyTypes.map(t => compareEffective.value[t.type]?.[key])
  const defined = vals.filter(v => v != null)
  if (defined.length <= 1) return false
  return new Set(defined.map(String)).size > 1
}

function compareMinVal(key) {
  const vals = strategyTypes.map(t => compareEffective.value[t.type]?.[key]).filter(v => v != null)
  return vals.length ? Math.min(...vals) : null
}

onMounted(async () => {
  await Promise.all([fetchEffective(), fetchRunningStrategies()])
  loadEffectiveIntoNodes()
})
</script>

<style scoped>
.strategies-page { display: flex; flex-direction: column; gap: 0; min-height: 100vh; background: #1a1d23; }

/* 策略类型选择 */
.type-selector { display: flex; gap: 12px; padding: 16px 20px; background: #252930; border-bottom: 1px solid #2d3139; }
.type-card { display: flex; align-items: center; gap: 8px; padding: 10px 20px; background: #2d3139; border: 1px solid #3d4451; border-radius: 8px; cursor: pointer; transition: all 0.2s; color: #b0b8c4; font-size: 14px; }
.type-card:hover { border-color: #4CAF50; color: #e0e0e0; }
.type-card.active { background: #4CAF50; border-color: #4CAF50; color: white; font-weight: 600; }
.type-icon { font-size: 18px; }

/* 画布 */
.workflow-canvas { display: flex; flex-direction: column; height: 920px; background: #1a1d23; border-bottom: 1px solid #2d3139; }
.canvas-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; background: #252930; border-bottom: 1px solid #2d3139; flex-wrap: wrap; gap: 10px; }
.header-left { display: flex; align-items: center; gap: 12px; }
.canvas-header h2 { margin: 0; font-size: 15px; color: #e0e0e0; }
.readonly-badge { padding: 3px 10px; background: #475569; color: #e2e8f0; border-radius: 4px; font-size: 12px; }
.header-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.legend { display: flex; gap: 14px; align-items: center; }
.lg-item { display: flex; align-items: center; gap: 5px; font-size: 12px; color: #b0b8c4; }
.lg-dot { width: 18px; height: 0; border-top: 2px solid; display: inline-block; }
.lg-dot.main { border-color: #4CAF50; }
.lg-dot.guard { border-color: #f6465d; border-top-style: dashed; }
.lg-dot.recover { border-color: #4ade80; border-top-style: dashed; }
.workflow-flow { flex: 1; background: #1a1d23; }

/* 节点 */
:deep(.custom-node) { background: #252930; border: 1px solid #3d4451; border-radius: 8px; min-width: 210px; max-width: 270px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
:deep(.custom-node.start)    { border-color: #22c55e; }
:deep(.custom-node.loop)     { border-color: #4CAF50; }
:deep(.custom-node.sys)      { border-color: #64748b; }
:deep(.custom-node.data)     { border-color: #38bdf8; }
:deep(.custom-node.ladder)   { border-color: #f0b90b; }
:deep(.custom-node.trigger)  { border-color: #2196F3; }
:deep(.custom-node.calc)     { border-color: #14b8a6; }
:deep(.custom-node.order)    { border-color: #FF9800; }
:deep(.custom-node.bybit)    { border-color: #9C27B0; }
:deep(.custom-node.verify)   { border-color: #F44336; }
:deep(.custom-node.record)   { border-color: #4ade80; }
:deep(.custom-node.complete) { border-color: #4ade80; }
:deep(.custom-node.gate)     { border-color: #FF9800; }
:deep(.custom-node.check)    { border-color: #a78bfa; }
:deep(.custom-node.guard)    { border-color: #f6465d; background: #2a2228; }
:deep(.node-header) { display:flex; align-items:center; gap:8px; padding:9px 12px; border-bottom:1px solid #2d3139; background:#2d3139; border-radius:8px 8px 0 0; }
:deep(.node-icon) { font-size:15px; }
:deep(.node-title) { font-size:12.5px; font-weight:600; color:#e0e0e0; }
:deep(.node-content) { padding:8px 12px; }
:deep(.param-row-ro) { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:2px 0; }
:deep(.param-label-ro) { font-size:11px; color:#8899aa; }
:deep(.param-val-ro) { font-size:12px; font-family:monospace; color:#e0e0e0; font-weight:600; }
:deep(.param-unit-ro) { font-size:10px; color:#8899aa; margin-left:1px; }
:deep(.node-description) { padding:6px 12px; font-size:11px; color:#8899aa; border-top:1px solid #2d3139; line-height:1.5; }
:deep(.node-impact) { padding:4px 12px 8px; font-size:11px; color:#4CAF50; line-height:1.4; }

/* 有效参数（只读） */
.crud-section { background: #252930; border-top: 1px solid #2d3139; }
.crud-header { display:flex; align-items:center; justify-content:space-between; padding: 12px 20px; cursor:pointer; user-select:none; }
.crud-header:hover { background: #2d3139; }
.effective-bar { margin: 0 20px 12px; padding: 12px; background: linear-gradient(to right, rgba(76,175,80,0.1), transparent); border: 1px solid rgba(76,175,80,0.3); border-radius: 12px; }
</style>
