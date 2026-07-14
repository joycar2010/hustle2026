<template>
  <div class="mixsys">
    <div class="grid">
      <div class="card">
        <div class="chd"><b>版本管理</b></div>
        <div class="kv"><span>源码权威</span><b>{{ st.version?.source_branch || '—' }}</b></div>
        <div class="kv"><span>服务器部署时间</span><b>{{ st.version?.deployed_at || '—' }}</b></div>
        <el-button size="small" type="warning" :loading="busy==='snap'" @click="run('snap')">部署态快照备份</el-button>
        <div class="fnote">源码推送在开发机（GitHub mix 分支,FF-only）；此按钮=服务器部署产物快照落 backups/</div>
      </div>

      <div class="card">
        <div class="chd"><b>数据库管理</b></div>
        <div class="kv" v-for="(v, k) in st.db || {}" :key="k"><span>{{ k }}</span><b>{{ v }}</b></div>
        <el-button size="small" type="warning" :loading="busy==='db'" @click="run('db')">立即备份（pg_dump×2）</el-button>
      </div>

      <div class="card">
        <div class="chd"><b>SSL 证书</b></div>
        <div class="kv"><span>到期</span><b>{{ st.ssl?.cert_expiry || '—' }}</b></div>
        <div class="kv"><span>自动续期</span><b>{{ st.ssl?.auto_renew || '—' }}</b></div>
        <div v-for="(info, dom) in (st.ssl?.domains || {})" :key="dom" class="kv">
          <span>{{ dom }}</span>
          <b :style="{color: info.san_covers ? '#0ECB81' : '#F6465D'}">
            {{ info.san_covers ? 'SAN✓' : 'SAN✗' }} · {{ info.expiry }}</b>
        </div>
        <el-button size="small" type="warning" :loading="busy==='ssl'" @click="run('ssl')">手动触发续期检查</el-button>
        <div class="fnote">certbot renew：未到期=no-op，安全</div>
      </div>

      <div class="card wide">
        <div class="chd"><b>备份文件</b><el-button size="small" @click="load">刷新</el-button></div>
        <div class="tr th"><span>文件</span><span class="r">大小MB</span><span class="r">时间</span></div>
        <div v-for="b in st.backups || []" :key="b.file" class="tr">
          <span class="fn">{{ b.file }}</span><span class="r">{{ b.size_mb }}</span><span class="r">{{ b.mtime }}</span>
        </div>
        <div v-if="!(st.backups||[]).length" class="fnote">暂无备份文件</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'

const st = ref({}); const busy = ref('')
async function load() { try { st.value = await mixApi.system.status() } catch (e) { ElMessage.error(e?.detail || '加载失败') } }
async function run(which) {
  busy.value = which
  try {
    const r = which === 'db' ? await mixApi.system.backupDb()
      : which === 'snap' ? await mixApi.system.backupSnapshot()
      : await mixApi.system.sslRenew()
    ElMessage.success(JSON.stringify(r.results || r).slice(0, 160))
    load()
  } catch (e) { ElMessage.error(e?.detail || '执行失败（需 SUPER_ADMIN 令牌）') }
  finally { busy.value = '' }
}
onMounted(load)
</script>

<style scoped lang="scss">
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; align-items: start; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px; &.wide { grid-column: 1 / -1; } }
.chd { display: flex; justify-content: space-between; align-items: center; b { font-size: 13px; } }
.kv { display: flex; justify-content: space-between; font-size: 12px; color: var(--mix-t2, #848E9C); b { color: var(--mix-t1, #EAECEF); } }
.fnote { font-size: 10.5px; color: var(--mix-t3, #5E6673); }
.tr { display: grid; grid-template-columns: 1fr 90px 110px; gap: 8px; font-size: 11.5px; padding: 3px 0;
  &.th { color: var(--mix-t3, #5E6673); font-weight: 700; } }
.fn { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.r { text-align: right; }
</style>
