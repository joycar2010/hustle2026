<script setup lang="ts">
/**
 * VirtualPositionTable —— 币种主行 ↳账户子行 两级虚拟滚动表（对照清单契约版）
 *
 * 关键设计：币种行兼列头 —— 同一列位，币种行渲染文字标签(columnLabels)，
 * 账户子行渲染真实数值(values)；混合策略平铺时每行自带本策略标签。
 * 干预操作全部在右键菜单（右键 / 行尾 ⋮ / 移动端长按）；行内只留高频钮(移/还/平)。
 */
import { computed, onMounted, onUnmounted, reactive, ref, shallowRef, watchEffect } from 'vue'
import type { AccountSubRow, MenuItem, PositionRow, SortDir, SortKey, SubRowState } from './types'
import { STRATEGY_META } from './types'
import { CONTEXT_MENUS, INLINE_ACTIONS } from './strategyColumns'
import { useInflight } from './useInflight'

const props = withDefaults(defineProps<{
  rows: PositionRow[]
  sortKey?: SortKey
  sortDir?: SortDir
  height?: number
  deadlineWarnMs?: number
}>(), {
  sortKey: 'opened_at',
  sortDir: 'asc',
  height: 640,
  deadlineWarnMs: 30 * 60 * 1000,
})

const emit = defineEmits<{
  action: [payload: { action: string; rowId: string; accountId?: string; confirm?: boolean }]
  ruleOverride: [rowId: string]
}>()

const ROW_H = 27
const SUB_H = 24
const OVERSCAN = 8

/* ---------- 折叠（默认全展） ---------- */
const collapsed = reactive(new Set<string>())
const toggleCoin = (id: string) => (collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id))
const expandAll = () => collapsed.clear()
const collapseAll = () => props.rows.forEach(r => collapsed.add(r.id))

/* ---------- 排序（后端字段） ---------- */
const sorted = computed(() => {
  const rs = [...props.rows]
  const dir = props.sortDir === 'asc' ? 1 : -1
  rs.sort((a, b) => {
    if (props.sortKey === 'pnl') return ((a.pnl ?? -Infinity) - (b.pnl ?? -Infinity)) * dir
    const ta = a.openedAt ? Date.parse(a.openedAt) : Infinity
    const tb = b.openedAt ? Date.parse(b.openedAt) : Infinity
    return (ta - tb) * dir
  })
  return rs
})

/* ---------- 拍平 + 前缀和 ---------- */
type Item =
  | { kind: 'main'; row: PositionRow; h: number }
  | { kind: 'sub'; row: PositionRow; sub: AccountSubRow; h: number }

const items = shallowRef<Item[]>([])
const offsets = shallowRef<number[]>([])
const totalH = ref(0)

watchEffect(() => {
  const list: Item[] = []
  for (const row of sorted.value) {
    list.push({ kind: 'main', row, h: ROW_H })
    if (!collapsed.has(row.id)) for (const sub of row.subRows || []) list.push({ kind: 'sub', row, sub, h: SUB_H })
  }
  const offs = new Array<number>(list.length)
  let acc = 0
  for (let i = 0; i < list.length; i++) { offs[i] = acc; acc += list[i].h }
  items.value = list; offsets.value = offs; totalH.value = acc
})

/* ---------- 虚拟窗口 ---------- */
const scrollTop = ref(0)
const viewport = ref<HTMLElement | null>(null)
const onScroll = () => { scrollTop.value = viewport.value?.scrollTop ?? 0 }
/* height=0 ⇒ 自适应填满父容器(ResizeObserver 实测视口高,页面级无滚动条) */
const measuredH = ref(640)
let ro: ResizeObserver | null = null
onMounted(() => {
  if (props.height === 0 && viewport.value) {
    measuredH.value = viewport.value.clientHeight || 640
    ro = new ResizeObserver(() => { measuredH.value = viewport.value?.clientHeight || 640 })
    ro.observe(viewport.value)
  }
})
onUnmounted(() => { ro?.disconnect(); ro = null })
const effHeight = computed(() => (props.height === 0 ? measuredH.value : props.height))
function lowerBound(offs: number[], t: number): number {
  let lo = 0, hi = offs.length - 1, ans = 0
  while (lo <= hi) { const m = (lo + hi) >> 1; if (offs[m] <= t) { ans = m; lo = m + 1 } else hi = m - 1 }
  return ans
}
const visible = computed(() => {
  const offs = offsets.value
  if (!offs.length) return { slice: [] as Item[], start: 0, padTop: 0 }
  const start = Math.max(0, lowerBound(offs, scrollTop.value) - OVERSCAN)
  let end = start
  const bottom = scrollTop.value + effHeight.value
  while (end < offs.length && offs[end] < bottom) end++
  end = Math.min(offs.length, end + OVERSCAN)
  return { slice: items.value.slice(start, end), start, padTop: offs[start] }
})

/* ---------- 倒计时预警：<30min 整行左→右金色渐变 ---------- */
const now = ref(Date.now())
setInterval(() => { now.value = Date.now() }, 1000)
const isWarn = (r: PositionRow) =>
  r.keyDeadlineTs != null && r.keyDeadlineTs > now.value && r.keyDeadlineTs - now.value < props.deadlineWarnMs

/* ---------- 右键菜单（右键 / ⋮ / 长按 同源） ---------- */
const menu = reactive<{ open: boolean; x: number; y: number; row: PositionRow | null; accountId?: string }>({
  open: false, x: 0, y: 0, row: null,
})
function openMenu(e: MouseEvent, row: PositionRow, accountId?: string) {
  e.preventDefault()
  menu.open = true
  menu.x = Math.min(e.clientX, window.innerWidth - 190)
  menu.y = Math.min(e.clientY, window.innerHeight - 280)
  menu.row = row; menu.accountId = accountId
}
let pressTimer: ReturnType<typeof setTimeout> | null = null
function onTouchStart(e: TouchEvent, row: PositionRow, accountId?: string) {
  pressTimer = setTimeout(() => {
    const t = e.touches[0]
    menu.open = true; menu.x = t.clientX; menu.y = t.clientY; menu.row = row; menu.accountId = accountId
  }, 500)
}
function onTouchEnd() { if (pressTimer) clearTimeout(pressTimer) }
const closeMenu = () => { menu.open = false }
const menuItems = computed<MenuItem[]>(() => (menu.row ? CONTEXT_MENUS[menu.row.strategyCode] : []))

/* ---------- 操作（inflight 防重入） ---------- */
const { isInflight, guard, keyOf } = useInflight()
async function fire(action: string, row: PositionRow, accountId?: string, confirm?: boolean) {
  closeMenu()
  await guard(keyOf(action, row.id, accountId), async () => {
    emit('action', { action, rowId: row.id, accountId, confirm })
  })
}
function onMenuClick(it: MenuItem) {
  if (!menu.row) return
  if (it.key === 'rule_override') { emit('ruleOverride', menu.row.id); closeMenu(); return }
  fire(it.key, menu.row, menu.accountId, it.confirm)
}
function inlineDisabled(row: PositionRow, key: string): boolean {
  if (key === 'move' && !row.allowRemove) return true
  if (key === 'repay' && !row.allowRepay) return true
  return isInflight(keyOf(key, row.id))
}

function tone(t?: string, sc?: string): string {
  switch (t) {
    case 'up': return '#0ECB81'
    case 'down': return '#F6465D'
    case 'muted': return '#5E6673'
    case 'accent': return '#F0B90B'
    case 'strategy': return sc ?? '#EAECEF'
    default: return '#EAECEF'
  }
}
function stateStyle(s: SubRowState): { bg: string; fg: string } {
  switch (s.kind) {
    case 'api_error': return { bg: '#F6465D', fg: '#fff' }
    case 'borrowing': return { bg: '#2DD4BF', fg: '#0B0E11' }
    case 'repay_paused': return { bg: '#F0B90B', fg: '#0B0E11' }
    default: return { bg: 'transparent', fg: '#848E9C' }
  }
}
</script>

<template>
  <div class="vpt" :class="{ fill: height === 0 }" @click="closeMenu">
    <div class="vpt-toolbar">
      <button class="chip chip-on" @click="expandAll">全展</button>
      <button class="chip" @click="collapseAll">全收</button>
      <slot name="toolbar" />
      <span class="hint">币种行=列标签 · ↳账户行=数值 · 右键 / ⋮ / 长按呼出干预菜单</span>
    </div>

    <div ref="viewport" class="vpt-viewport" :style="height === 0 ? {} : { height: height + 'px' }" @scroll.passive="onScroll">
      <div :style="{ height: totalH + 'px', position: 'relative' }">
        <div :style="{ transform: `translateY(${visible.padTop}px)` }">
          <template v-for="(it, i) in visible.slice" :key="visible.start + i">

            <!-- 币种主行（兼列头） -->
            <div v-if="it.kind === 'main'"
                 class="row main" :class="{ warn: isWarn(it.row), frozen: it.row.phase === 'FROZEN' }"
                 :style="{ height: ROW_H + 'px' }"
                 @click="toggleCoin(it.row.id)"
                 @contextmenu="openMenu($event, it.row)"
                 @touchstart="onTouchStart($event, it.row)" @touchend="onTouchEnd">
              <span class="caret" :style="collapsed.has(it.row.id) ? {} : { color: STRATEGY_META[it.row.strategyCode].color }">
                {{ it.row.positionCount ? (collapsed.has(it.row.id) ? '▸' : '▾') : '·' }}
              </span>
              <span class="sym" :class="{ dead: it.row.mark === 'dead' }">
                {{ it.row.symbol }}<i v-if="it.row.positionCount" class="cnt">×{{ it.row.positionCount }}</i>
                <i v-if="it.row.mark === 'dead'" class="mk dead-chip">停</i><i v-else-if="it.row.mark === 'risk'" class="mk risk">险</i>
              </span>
              <span class="sbadge" :style="{ background: STRATEGY_META[it.row.strategyCode].colorBg, color: STRATEGY_META[it.row.strategyCode].color }">{{ it.row.strategyCode }}</span>
              <span class="phase">{{ it.row.phaseLabel }}</span>
              <span v-for="l in it.row.columnLabels" :key="l" class="cell lbl">{{ l }}</span>
              <span class="params">
                <i v-for="p in it.row.marketParams" :key="p.label"><em>{{ p.label }}</em><b :style="{ color: tone(p.tone) }">{{ p.value }}</b></i>
              </span>
              <span class="push">{{ it.row.pushStatus }}</span>
              <span class="ratio" :style="{ color: (it.row.fundingRateRatio || '').startsWith('-') ? '#F6465D' : '#0ECB81' }">{{ it.row.fundingRateRatio }}</span>
              <span class="single">{{ it.row.singleRuleBrief }}</span>
              <b class="pnl" :style="{ color: it.row.pnl == null ? '#5E6673' : it.row.pnl >= 0 ? '#0ECB81' : '#F6465D' }">
                {{ it.row.pnl == null ? '—' : (it.row.pnl >= 0 ? '+' : '') + it.row.pnl.toFixed(2) }}
              </b>
              <span class="ops" @click.stop>
                <button v-for="a in INLINE_ACTIONS[it.row.strategyCode]" :key="a.key"
                        class="op" :class="{ ban: inlineDisabled(it.row, a.key) && !isInflight(keyOf(a.key, it.row.id)) }"
                        :disabled="inlineDisabled(it.row, a.key)"
                        @click="fire(a.key, it.row)">{{ isInflight(keyOf(a.key, it.row.id)) ? '…' : a.label }}</button>
                <button class="op more" @click="openMenu($event, it.row)">⋮</button>
              </span>
              <span class="rule" :class="{ gold: it.row.ruleScope === 'override' }" @click.stop="emit('ruleOverride', it.row.id)">
                {{ it.row.ruleScope === 'template' ? '通用规则' : '单一规则' }}
              </span>
            </div>

            <!-- ↳ 账户子行（真实数值，与主行标签同列位） -->
            <div v-else class="row sub" :style="{ height: SUB_H + 'px' }"
                 @contextmenu="openMenu($event, it.row, it.sub.executingAccount)"
                 @touchstart="onTouchStart($event, it.row, it.sub.executingAccount)" @touchend="onTouchEnd">
              <span class="caret"></span>
              <span class="sym acct">
                ↳ <i class="kind" :class="it.sub.accountKind">{{ it.sub.accountKind === 'master' ? '主' : '子' }}</i>
                {{ it.sub.executingAccount }}
              </span>
              <span class="sbadge dimb">{{ it.sub.venue }}</span>
              <span class="phase"></span>
              <span v-for="(v, vi) in it.sub.values" :key="vi" class="cell val"
                    :style="{ color: v.dim ? '#5E6673' : tone(v.tone, STRATEGY_META[it.row.strategyCode].color) }">{{ v.value }}</span>
              <span class="params">
                <i v-for="p in (it.sub.econParams || [])" :key="p.label"><em>{{ p.label }}</em><b :style="{ color: tone(p.tone) }">{{ p.value }}</b></i>
              </span>
              <span class="push">
                <i v-if="it.sub.state.kind !== 'plain' && it.sub.state.kind !== 'holding'" class="stchip"
                   :style="{ background: stateStyle(it.sub.state).bg, color: stateStyle(it.sub.state).fg }">{{ it.sub.state.text }}</i>
                <template v-else>{{ it.sub.state.text }}</template>
              </span>
              <span class="ratio">{{ it.sub.fundingRateRatio ?? '—' }}</span>
              <span class="single"></span>
              <b class="pnl rate">{{ it.sub.borrowRatePerSec ?? '' }}</b>
              <span class="ops ban-cd" :class="{ hot: !!it.sub.banCountdown }">{{ it.sub.banCountdown ?? '—' }}</span>
              <span class="rule restricted">{{ it.sub.apiRestricted ? '被币安 API 限制' : '' }}</span>
            </div>

          </template>
        </div>
      </div>
    </div>

    <!-- 右键菜单（Teleport，右键 / ⋮ / 长按同源） -->
    <Teleport to="body">
      <div v-if="menu.open && menu.row" class="vpt-ctx" :style="{ left: menu.x + 'px', top: menu.y + 'px' }" @click.stop>
        <div class="ctx-h">{{ menu.row.symbol }}{{ menu.accountId ? ' · ↳ ' + menu.accountId : '' }}</div>
        <template v-for="it in menuItems" :key="it.key">
          <div v-if="it.dividerBefore" class="ctx-div" />
          <div class="ctx-item" :class="it.kind"
               :aria-disabled="isInflight(keyOf(it.key, menu.row.id, menu.accountId))"
               @click="onMenuClick(it)">
            {{ it.label }}<span v-if="isInflight(keyOf(it.key, menu.row.id, menu.accountId))"> …</span>
          </div>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<style scoped lang="scss">
$bg: #0B0E11; $card: #181B21; $card2: #20242C; $border: #262B33;
$t1: #EAECEF; $t2: #848E9C; $t3: #5E6673; $gold: #F0B90B;

.vpt { background: $card; border: 1px solid $border; border-radius: 12px; font-size: 12px; color: $t1;
  /* height=0 自适应: 父容器为 flex 列时填满剩余高度,页面级不出滚动条 */
  &.fill { flex: 1 1 auto; min-height: 260px; display: flex; flex-direction: column;
    .vpt-viewport { flex: 1; min-height: 0; } } }
.vpt-toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid $border;
  .chip { background: $card2; border: 1px solid $border; color: $t2; border-radius: 5px; padding: 3px 10px; cursor: pointer;
    &.chip-on { background: $gold; border-color: $gold; color: $bg; font-weight: 700; } }
  .hint { margin-left: auto; color: $t3; font-size: 11px; } }
.vpt-viewport { overflow-y: auto; overflow-x: auto; }

.row { display: flex; align-items: center; gap: 9px; padding: 0 12px; cursor: pointer; line-height: 1;
  font-variant-numeric: tabular-nums; min-width: 1460px; /* 窄窗横向滚动兜底,列绝不压碎 */
  &.main { font-weight: 600;
    &.warn { background: linear-gradient(90deg, rgba(240,185,11,.19), rgba(240,185,11,.02)); box-shadow: inset 0 0 0 1px rgba(240,185,11,.4); border-radius: 5px; }
    &.frozen { box-shadow: inset 0 0 0 1px rgba(246,70,93,.4); border-radius: 5px; } }
  &.sub { background: #12151A; font-weight: 400; } }

.caret { width: 12px; color: $t3; font-size: 10px; }
.sym { min-width: 118px; font-weight: 800; font-size: 11px;
  &.dead { color: #F6465D; }
  &.acct { color: #fff; font-weight: 700; font-size: 10px; }
  .cnt { font-style: normal; color: $t3; font-size: 9px; margin-left: 3px; }
  .mk { font-style: normal; margin-left: 4px; font-size: 9px; font-weight: 800; padding: 0 4px; border-radius: 3px;
    &.dead-chip { background: rgba(246,70,93,.16); color: #F6465D; }
    &.risk { background: rgba(240,185,11,.16); color: $gold; } }
  .kind { font-style: normal; padding: 0 4px; border-radius: 3px; font-size: 9px; font-weight: 700; margin: 0 2px;
    &.master { background: rgba(240,185,11,.15); color: $gold; }
    &.sub { background: rgba(132,142,156,.15); color: $t2; } } }
.sbadge { width: 44px; text-align: center; padding: 1px 0; border-radius: 4px; font-size: 9px; font-weight: 800;
  &.dimb { background: $card2; color: $t3; font-weight: 500; } }
.phase { width: 56px; color: $t2; font-size: 10px; }
.cell { flex: 1; min-width: 62px; text-align: right; white-space: nowrap; overflow: hidden;
  &.lbl { color: $t3; font-size: 10px; font-weight: 500; }
  &.val { font-size: 11.5px; font-weight: 600; } }
/* 右侧信息区: 弹性宽(min~max)+逐项 nowrap,长条目(费差 venue)不再把列挤成竖条 */
.params { flex: 1 1 230px; min-width: 170px; max-width: 320px; display: inline-flex; gap: 9px;
  justify-content: flex-end; overflow: hidden; white-space: nowrap;
  i { font-style: normal; display: inline-flex; gap: 3px; align-items: baseline; white-space: nowrap; flex: none;
    em { font-style: normal; color: $t3; font-size: 9.5px; } b { font-size: 10.5px; font-weight: 600; } } }
.push { width: 96px; text-align: right; color: $t3; font-size: 10.5px; flex: none;
  .stchip { font-style: normal; padding: 1px 6px; border-radius: 3px; font-size: 9.5px; font-weight: 700; } }
.ratio { width: 54px; text-align: right; font-size: 11px; font-weight: 700; color: $t2; flex: none; }
.single { width: 56px; text-align: right; color: $gold; font-size: 10px; flex: none; }
.pnl { width: 78px; text-align: right; font-weight: 800; font-size: 12px; flex: none;
  &.rate { color: $t2; font-weight: 500; font-size: 10.5px; } }
.ops { display: inline-flex; gap: 5px; width: 78px; justify-content: flex-end; flex: none;
  .op { background: $card2; border: 1px solid $border; color: $gold; border-radius: 4px; padding: 2px 7px; cursor: pointer; font-weight: 700; font-size: 10.5px;
    &.more { color: $t2; }
    &.ban { color: #F6465D; }
    &:disabled { opacity: .6; cursor: not-allowed; } }
  &.ban-cd { color: $t3; font-size: 10px; align-items: center; &.hot { color: #F6465D; font-weight: 800; } } }
.rule { width: 68px; text-align: right; color: #4A9CFF; font-size: 10.5px; flex: none;
  &.gold { color: $gold; }
  &.restricted { color: #F6465D; font-weight: 700; font-size: 9.5px; } }
</style>

<style lang="scss">
/* 菜单 Teleport 到 body，不能 scoped */
.vpt-ctx { position: fixed; z-index: 9999; width: 176px; background: #1E232B; border: 1px solid #262B33;
  border-radius: 10px; padding: 5px; box-shadow: 0 8px 24px rgba(0,0,0,.6); font-size: 10.5px; color: #EAECEF;
  .ctx-h { padding: 5px 10px 4px; color: #5E6673; font-size: 8.5px; font-weight: 600; }
  .ctx-div { height: 1px; background: #262B33; margin: 2px 0; }
  .ctx-item { padding: 6px 10px; border-radius: 6px; font-weight: 600; cursor: pointer;
    &:hover { background: #20242C; }
    &.danger { color: #F6465D; }
    &.strategy { color: #A78BFA; }
    &.link { color: #4A9CFF; }
    &[aria-disabled='true'] { opacity: .5; pointer-events: none; } } }
</style>
