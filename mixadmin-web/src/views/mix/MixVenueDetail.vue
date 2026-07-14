<template>
  <div class="vdet">
    <RiskStatusBar />
    <div class="card">
      <div class="chd"><b class="vn">{{ venue }}</b> 平台详情
        <span class="mch" :class="modeCls(d.policy?.mode)">{{ d.policy?.mode || 'N/A' }}</span>
        <span class="dim">incident_state {{ d.policy?.incident_state || 'N/A' }}
          · Tier {{ d.policy?.tier || '—' }}</span>
        <el-link class="grow-r" @click="$router.push('/mix/venuerisk')">← 返回工作台</el-link>
      </div>
      <el-tabs v-model="tab">
        <!-- ①概览(KdKdE 八卡精简) -->
        <el-tab-pane label="概览" name="ov">
          <div class="ovgrid">
            <div class="okv"><span>当前状态及原因</span><b>{{ firstReason }}</b></div>
            <div class="okv"><span>暴露权益 / 敞口</span><b>{{ n(d.policy?.equity) }}U / {{ n(d.policy?.exposure_notional) }}U</b></div>
            <div class="okv"><span>风险调整损失(折价)</span><b :class="{bad:(d.policy?.trapped_usdt||0)>0}">{{ d.policy?.haircut_pct ? (d.policy.haircut_pct*100)+'% = '+n(d.policy?.trapped_usdt)+'U' : '无' }}</b></div>
            <div class="okv"><span>恢复阶梯</span><b>{{ d.policy?.recovery ? `阶段${d.policy.recovery.stage}·额度${Math.round(d.policy.recovery.allow_pct*100)}%` : '—' }}</b></div>
            <div class="okv"><span>提现健康</span><b>{{ wdText }}</b></div>
            <div class="okv"><span>命中作用域</span><b class="wrap">{{ hitsText }}</b></div>
            <div class="okv"><span>恢复所需条件</span><b class="wrap">根因关闭+私有查询稳定+受控提现验证/人工确认+RECON零残差+阶梯逐级(不许跳级)</b></div>
            <div class="okv"><span>证据包</span><b>{{ (d.defense_packs||[]).length }} 份(REDUCE+自动生成)</b></div>
          </div>
        </el-tab-pane>
        <!-- ②账户限制时间线(原始错误码+endpoint+首现/最近) -->
        <el-tab-pane :label="`账户限制 ${ (d.restrictions||[]).length }`" name="rest">
          <el-table :data="d.restrictions||[]" size="small">
            <el-table-column prop="signal_type" label="信号" width="150" />
            <el-table-column prop="severity" label="级别" width="90" />
            <el-table-column prop="raw_code" label="原始码" width="140" />
            <el-table-column prop="raw_payload" label="原始载荷" min-width="220" show-overflow-tooltip />
            <el-table-column prop="hit_count" label="命中" width="60" align="right" />
            <el-table-column prop="first_seen" label="首次" width="150" />
            <el-table-column prop="last_seen" label="最近" width="150" />
          </el-table>
        </el-tab-pane>
        <!-- ③提现与网络 -->
        <el-tab-pane :label="`提现与网络 ${ (d.observations||[]).length }`" name="wd">
          <div class="wsum" v-if="d.withdrawal">pending {{ d.withdrawal.pending_count }} · 最老 {{ fmtAge(d.withdrawal.oldest_pending_age_sec) }}
            · p50 {{ mm(d.withdrawal.p50_sec) }} · p95 {{ mm(d.withdrawal.p95_sec) }}(样本{{ d.withdrawal.sample_n }})
            · 失败 {{ d.withdrawal.recent_failures }}</div>
          <el-table :data="d.observations||[]" size="small">
            <el-table-column prop="asset" label="资产" width="80" />
            <el-table-column prop="network" label="网络" width="100" />
            <el-table-column prop="amount" label="金额" width="110" align="right" />
            <el-table-column prop="status" label="状态" width="110" />
            <el-table-column prop="venue_tx_id" label="平台流水号" min-width="140" show-overflow-tooltip />
            <el-table-column prop="chain_tx" label="链上tx" min-width="140" show-overflow-tooltip />
            <el-table-column prop="initiated_at" label="发起" width="150" />
            <el-table-column prop="duration_sec" label="耗时s" width="80" align="right" />
          </el-table>
          <div class="fnote">允许动作=查看事实/停止新增/工单/标记审核/证据包;禁止重复提现、换IP重试、切换未登记账户(V5 §14.4)</div>
        </el-tab-pane>
        <!-- ④敞口与仓位 -->
        <el-tab-pane label="敞口与仓位" name="exp">
          <div class="ovgrid">
            <div class="okv"><span>在场名义</span><b>{{ n(d.policy?.exposure_notional) }}U</b></div>
            <div class="okv"><span>上限 / 预警比</span><b>{{ n(d.policy?.cap_usdt) }}U / {{ d.policy?.warn_ratio ?? '—' }}</b></div>
            <div class="okv"><span>模式历史(近50)</span><b>{{ (d.transitions||[]).length }} 条(下方)</b></div>
          </div>
          <div v-for="(t,i) in d.transitions||[]" :key="i" class="tr">
            <span class="mch sm" :class="modeCls(t.before_mode)">{{ t.before_mode }}</span>→
            <span class="mch sm" :class="modeCls(t.after_mode)">{{ t.after_mode }}</span>
            <span class="dim">{{ String(t.reason||'').slice(0,60) }} · v{{ t.policy_version }} · {{ (t.recorded_at||'').slice(0,16) }}</span>
          </div>
        </el-tab-pane>
        <!-- ⑤条款与证据 -->
        <el-tab-pane label="条款与证据" name="pol">
          <div class="ovgrid" v-if="d.venue_policy">
            <div class="okv"><span>套利条款</span><b>{{ d.venue_policy.arbitrage_status }}</b></div>
            <div class="okv"><span>自动交易 / 子账户</span><b>{{ d.venue_policy.automation_status }} / {{ d.venue_policy.subaccount_status }}</b></div>
            <div class="okv"><span>已复核 / 下次复核</span><b>{{ d.venue_policy.reviewed_at || '未复核' }} / {{ (d.venue_policy.next_review_at||'—').slice(0,10) }}</b></div>
            <div class="okv"><span>复核人</span><b>{{ d.venue_policy.review_owner || '—' }}</b></div>
          </div>
          <div class="chd2">书面 artifact({{ (d.artifacts||[]).length }})<span class="dim">客户经理口头说明不算</span></div>
          <div v-for="(a,i) in d.artifacts||[]" :key="i" class="tr"><b>{{ a.kind }}</b> {{ a.title }} <span class="dim">{{ a.url_or_ref }} · {{ (a.recorded_at||'').slice(0,16) }}</span></div>
          <div class="chd2">证据包({{ (d.defense_packs||[]).length }})</div>
          <div v-for="p in d.defense_packs||[]" :key="p.id" class="tr">#{{ p.id }} <b>{{ p.trigger_rule }}</b> <span class="dim">{{ p.generated_at }}</span></div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const route = useRoute()
const venue = route.params.venue
const d = ref({})
const tab = ref('ov')
const n = v => (v == null ? 'N/A' : Number(v).toLocaleString())
const mm = s => (s == null ? 'N/A' : Math.round(s / 60) + 'm')
const fmtAge = s => (s >= 3600 ? Math.floor(s / 3600) + 'h' : Math.floor((s || 0) / 60) + 'm')
const modeCls = m => ({ NORMAL: 'ok', WATCH: 'watch', NO_NEW_RISK: 'nonew', REDUCE_ONLY: 'red',
  EXIT_ONLY: 'red', FROZEN: 'quar', QUARANTINED: 'quar', RECOVERY_WATCH: 'recov' }[m] || 'unknown')
const firstReason = computed(() => String(d.value.policy?.reason || 'N/A').split('|')[0])
const wdText = computed(() => {
  const w = d.value.withdrawal
  if (!w) return 'N/A(未接/键过期)'
  return `pending ${w.pending_count} · p95 ${mm(w.p95_sec)} · 失败${w.recent_failures}`
})
const hitsText = computed(() => (d.value.policy?.modes_hit || []).map(h => `${h.scope}→${h.mode}`).join(' · ') || 'ok')
onMounted(async () => { try { d.value = await mixApi.riskVenue(venue) } catch (e) { /* 状态条示STALE */ } })
</script>

<style scoped lang="scss">
.vdet { display: flex; flex-direction: column; gap: 10px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 12px; }
.chd { font-size: 13px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 6px; display: flex; align-items: center; gap: 10px; }
.chd2 { font-size: 12px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin: 10px 0 4px; display: flex; gap: 8px; }
.vn { font-size: 15px; }
.grow-r { margin-left: auto; }
.mch { font-weight: 800; font-size: 10.5px; padding: 1px 8px; border-radius: 4px; &.sm { font-size: 9.5px; padding: 0 5px; }
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.watch { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.nonew { background: rgba(255,138,61,.16); color: #FF8A3D; }
  &.red { background: rgba(246,70,93,.16); color: #F6465D; }
  &.quar { background: #8B1E2D; color: #fff; }
  &.recov { background: rgba(140,163,199,.16); color: #8CA3C7; }
  &.unknown { background: rgba(94,102,115,.2); color: #9aa4b2; } }
.ovgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px; margin: 6px 0; }
.okv { background: var(--mix-card2, #1E2329); border: 1px solid var(--mix-border, #262B33); border-radius: 6px; padding: 8px 10px;
  span { display: block; font-size: 10.5px; color: var(--mix-t3, #5E6673); margin-bottom: 3px; }
  b { font-size: 12px; color: var(--mix-t1, #EAECEF); &.bad { color: #F6465D; } &.wrap { white-space: normal; font-weight: 500; } } }
.tr { font-size: 11px; color: var(--mix-t2, #848E9C); padding: 3px 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
  b { color: var(--mix-t1, #EAECEF); } }
.dim { color: var(--mix-t3, #5E6673); }
.bad { color: #F6465D; }
.wsum { font-size: 11.5px; color: var(--mix-t2, #848E9C); margin-bottom: 6px; }
.fnote { font-size: 10px; color: var(--mix-t3, #5E6673); margin-top: 8px; }
</style>
