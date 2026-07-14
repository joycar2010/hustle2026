<template>
  <div class="mixops-panel">
    <!-- 三机服务心跳分组点阵 -->
    <div class="card">
      <div class="chd"><b>服务健康 · 三机拓扑</b>
        <span class="sub">{{ okN }}/{{ allN }} 在线 · dcm:hb:* 真相源</span>
        <el-button size="small" @click="load">刷新</el-button>
      </div>
      <div class="machines">
        <div v-for="m in machines" :key="m.key" class="mbox">
          <div class="mhd"><b>{{ m.key }} 机</b><span>{{ m.desc }}</span>
            <i class="mcount" :class="{bad: m.services.some(s=>!s.ok)}">{{ m.services.filter(s=>s.ok).length }}/{{ m.services.length }}</i>
          </div>
          <div class="sgrid">
            <span v-for="s in m.services" :key="s.proc" class="svc" :title="`${s.proc} · ${s.age}`">
              <i class="dot" :class="{bad: !s.ok}"></i>{{ s.proc }}<em>{{ s.age }}</em>
            </span>
            <span v-if="!m.services.length" class="empty">无</span>
          </div>
        </div>
      </div>
    </div>

    <!-- V5 Camva:唯一权威 fencing 版本 + venue 风险快照网格(心跳绿≠健康) -->
    <div class="card">
      <div class="chd"><b>风险权威与 Fencing 版本</b>
        <span class="sub">心跳绿≠健康:须同看数据年龄与最后成功周期</span></div>
      <div class="fencerow">
        <div class="fc"><span>policy epoch·version</span><b>e{{ hv.policy_epoch ?? '—' }}·v{{ hv.policy_version ?? '—' }}</b></div>
        <div class="fc"><span>策略快照新鲜度</span><b :class="hv.policy_fresh?'ok':'bad'">{{ hv.policy_age_sec==null?'N/A':hv.policy_age_sec+'s' }}{{ hv.fail_closed?' · fail-closed':'' }}</b></div>
        <div class="fc"><span>max saga_version</span><b>{{ hv.max_saga_version ?? 'N/A' }}</b></div>
      </div>
      <div class="vgrid">
        <div v-for="g in hv.venue_grid||[]" :key="g.venue" class="vg" :class="{stale:!g.fresh}">
          <div class="vgh"><b>{{ g.venue }}</b><span :class="'m-'+g.mode">{{ g.mode }}</span></div>
          <div class="vgk">incident {{ g.incident_state || 'N/A' }} · cred epoch {{ g.credential_epoch ?? 'N/A' }}</div>
          <div class="vgk">{{ g.fresh ? '新鲜' : 'STALE · fail-closed' }} · 权益 {{ g.equity ?? 'N/A' }}U</div>
        </div>
      </div>
    </div>

    <div class="grid2">
      <!-- 数据库 -->
      <div class="card">
        <div class="chd"><b>数据库</b><el-button size="small" type="warning" :loading="busy==='db'" @click="run('db')">立即备份 pg_dump×2</el-button></div>
        <div class="kv" v-for="(v,k) in st.db || {}" :key="k"><span>{{ k }}</span><b>{{ v }}</b></div>
      </div>
      <!-- SSL -->
      <div class="card">
        <div class="chd"><b>SSL 证书</b><el-button size="small" type="warning" :loading="busy==='ssl'" @click="run('ssl')">续期检查</el-button></div>
        <div class="kv"><span>到期</span><b>{{ st.ssl?.cert_expiry || '—' }}</b></div>
        <div class="kv"><span>自动续期</span><b>{{ st.ssl?.auto_renew || '—' }}</b></div>
      </div>
    </div>

    <!-- 数据源健康 + 备份文件 -->
    <div class="grid2">
      <div class="card">
        <div class="chd"><b>数据源自检</b></div>
        <div class="kv"><span>PG 主库</span><b :class="ds.pg_configured?'up':'down'">{{ ds.pg_configured?'已配置':'未配置' }}</b></div>
        <div class="kv"><span>Redis 总线</span><b :class="ds.redis_configured?'up':'down'">{{ ds.redis_configured?'已配置':'未配置' }}</b></div>
        <div class="kv"><span>总线在线服务</span><b>{{ ds.bus_services_seen ?? '—' }}</b></div>
      </div>
      <div class="card">
        <div class="chd"><b>备份文件</b>
          <el-button size="small" type="warning" :loading="busy==='snap'" @click="run('snap')">部署态快照</el-button>
        </div>
        <div class="tr th"><span>文件</span><span class="r">MB</span><span class="r">时间</span></div>
        <div v-for="b in st.backups || []" :key="b.file" class="tr">
          <span class="fn">{{ b.file }}</span><span class="r">{{ b.size_mb }}</span><span class="r">{{ b.mtime }}</span>
        </div>
        <div v-if="!(st.backups||[]).length" class="fnote">暂无备份</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'

// 服务→机器映射（三机拓扑事实；未列出的归"其它"）
const MACHINE_OF = {
  A: { desc: '数据面 52.193.224.137', svcs: ['feed-cex', 'universe-sync', 'funding-sync', 'depth-sampler', 'basis-sampler', 'event-calendar', 'borrow-monitor', 'transfer-monitor'] },
  B: { desc: '执行面 54.65.42.207', svcs: ['engine-dualperp', 'engine-basis', 'engine-lending', 'pnl-recorder', 'account-snapshot', 'lending-advisor', 'cred-agent'] },
  C: { desc: '控制面 57.181.130.126', svcs: ['gateway', 'decision', 'risk-ledger', 'carry-advisor', 'fund-scheduler', 'llm-advisor', 'coin-bridge', 'mix-backend', 'mix-ws-hub'] },
}
const hbs = ref([])
const st = ref({})
const ds = ref({})
const busy = ref('')
const okN = computed(() => hbs.value.filter(h => h.ok).length)
const allN = computed(() => hbs.value.length)
const machines = computed(() => {
  const byProc = Object.fromEntries(hbs.value.map(h => [h.proc, h]))
  return Object.entries(MACHINE_OF).map(([key, m]) => ({
    key, desc: m.desc,
    services: m.svcs.filter(p => byProc[p]).map(p => byProc[p]),
  }))
})
const hv = ref({})
async function loadHv(){ try{ hv.value = await mixApi.healthV2() }catch(e){} }
async function load() {
  try {
    ;[hbs.value, st.value, ds.value] = await Promise.all([
      mixApi.monitor.heartbeats(), mixApi.system.status(), mixApi.datasources()])
  } catch (e) { ElMessage.error(e?.detail || '加载失败') }
}
async function run(kind) {
  busy.value = kind
  try {
    if (kind === 'db') { const r = await mixApi.system.backupDb(); ElMessage.success('备份完成：' + JSON.stringify(r.results)) }
    else if (kind === 'ssl') { const r = await mixApi.system.sslRenew(); ElMessage.success('续期检查 code=' + r.code) }
    else if (kind === 'snap') { const r = await mixApi.system.backupSnapshot(); ElMessage.success('快照：' + r.file + '（' + r.size_mb + 'MB）') }
    load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '操作失败') } finally { busy.value = '' }
}
onMounted(() => { load(); loadHv() })
</script>

<style scoped lang="scss">
.mixops-panel { display: flex; flex-direction: column; gap: 12px; }
.card { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 12px 14px; background: var(--mix-card, #181B21); }
.chd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
  b { font-size: 13px; } .sub { flex: 1; color: var(--el-text-color-secondary); font-size: 11px; } }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.machines { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.mbox { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 10px; }
.mhd { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--el-border-color);
  b { font-size: 12px; color: #F0B90B; } span { flex: 1; font-size: 10px; color: var(--el-text-color-placeholder); }
  .mcount { font-style: normal; font-size: 10px; font-weight: 800; color: #0ECB81; &.bad { color: #F6465D; } } }
.sgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 8px; }
.svc { font-size: 11px; color: var(--el-text-color-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  em { font-style: normal; color: var(--el-text-color-placeholder); margin-left: 4px; font-size: 9px; } }
.empty { color: var(--el-text-color-placeholder); font-size: 11px; }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #0ECB81; margin-right: 5px;
  &.bad { background: #F6465D; } }
.kv { display: flex; justify-content: space-between; font-size: 12px; color: var(--el-text-color-secondary); padding: 3px 0;
  b { color: var(--el-text-color-primary); } .up { color: #0ECB81; } .down { color: #F6465D; } }
.tr { display: grid; grid-template-columns: 1fr 60px 90px; gap: 6px; font-size: 11px; padding: 2px 0;
  &.th { color: var(--el-text-color-placeholder); font-weight: 700; } .fn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
.r { text-align: right; }
.fnote { font-size: 10.5px; color: var(--el-text-color-placeholder); margin-top: 6px; }
.up { color: #0ECB81; } .down { color: #F6465D; }
.fencerow { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.fc { background: var(--mix-panel,#12151A); border: 1px solid var(--mix-border,#262B33); border-radius: 6px; padding: 7px 12px;
  span { font-size: 10px; color: var(--mix-t3,#5E6673); } b { display: block; font-size: 13px; color: var(--mix-t1,#EAECEF); &.ok { color: #0ECB81; } &.bad { color: #F6465D; } } }
.vgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap: 8px; }
.vg { background: var(--mix-panel,#12151A); border: 1px solid var(--mix-border,#262B33); border-radius: 8px; padding: 8px 11px;
  &.stale { opacity: .55; border-color: #F6465D66; } }
.vgh { display: flex; align-items: center; gap: 8px; b { color: var(--mix-t1,#EAECEF); } }
.vgk { font-size: 10.5px; color: var(--mix-t3,#5E6673); margin-top: 3px; }
.m-NORMAL { color: #35b57c; } .m-WATCH { color: #F0B90B; } .m-NO_NEW_RISK { color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; } .m-FROZEN { color: #8B1E2D; }
</style>
