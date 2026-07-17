<template>
  <div class="mixsys">
    <el-tabs v-model="tab">
    <el-tab-pane label="系统配置" name="sys">
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
            {{ info.san_covers ? 'SAN 覆盖' : 'SAN 缺失' }} · {{ info.expiry }}</b>
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
    </el-tab-pane>
    <el-tab-pane label="网站设置" name="site" lazy><MixSite /></el-tab-pane>
    <el-tab-pane label="LLM设置" name="llm" lazy><MixLLM /></el-tab-pane>
    <el-tab-pane label="二次认证(TOTP)" name="totp" lazy>
      <div class="card" style="max-width:460px">
        <div class="chd"><b>操作员 TOTP 绑定</b></div>
        <div class="fnote" style="margin-bottom:10px">提案审批(DRY_RUN→ACTIVE)第二因子。规约允许 WebAuthn/TOTP,本实现为 TOTP。当前:<b>{{ totpBound ? '已绑定' : '未绑定' }}</b></div>
        <div v-if="!totpUri">
          <el-button size="small" type="warning" @click="totpProvision">{{ totpBound ? '重新绑定' : '开始绑定' }}</el-button>
        </div>
        <div v-else>
          <div class="fnote">otpauth URI(填入 Authenticator / Google Authenticator):</div>
          <el-input :model-value="totpUri" readonly type="textarea" :rows="2" style="margin:6px 0" />
          <div class="fnote">secret: <code>{{ totpSecret }}</code></div>
          <el-input v-model="totpCode" placeholder="输入一次动态码确认" maxlength="6" size="small" style="width:160px;margin-top:8px" />
          <el-button size="small" type="warning" style="margin-left:8px" @click="totpConfirm">确认启用</el-button>
        </div>
      </div>
    </el-tab-pane>
    <el-tab-pane label="AiCoin配置" name="aicoin" lazy>
      <div class="card" style="max-width:560px">
        <div class="chd"><b>AiCoin 行情接口配置</b></div>
        <div class="fnote" style="margin-bottom:10px">为 K线/币种搜索(行情研判·AiCoin 页)提供数据。凭据从 open.aicoin.com 获取,保存后 60s 内生效。secret 只存服务端,前端仅见掩码。</div>
        <el-form label-width="110px" size="small">
          <el-form-item label="AccessKeyId"><el-input v-model="ac.api_key" placeholder="如 abc123def456..." /></el-form-item>
          <el-form-item label="Secret Key">
            <el-input v-model="ac.api_secret" type="password" show-password
              :placeholder="ac.configured ? `当前 ${ac.api_secret_masked||'已设置'}(保存须重输)` : '请输入 Secret Key'" />
          </el-form-item>
          <el-form-item label="API Base"><el-input v-model="ac.api_base" placeholder="https://open.aicoin.com" /></el-form-item>
          <el-form-item label="启用"><el-switch v-model="ac.enabled" /></el-form-item>
          <el-form-item label="到期时间"><el-input v-model="ac.expires_at" placeholder="从 AiCoin 控制台 API Key 详情获取" /></el-form-item>
        </el-form>
        <div style="display:flex;gap:8px;align-items:center">
          <el-button size="small" type="warning" :loading="acBusy==='save'" @click="acSave">保存配置</el-button>
          <el-button size="small" :loading="acBusy==='test'" @click="acTest">测试连接</el-button>
          <span class="fnote">{{ acMsg }}</span>
        </div>
        <div class="fnote" v-if="ac.updated_at" style="margin-top:8px">最后更新: {{ ac.updated_at }} ({{ ac.updated_by || '-' }})</div>
      </div>
    </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import MixSite from './MixSite.vue'
import MixLLM from './MixLLM.vue'
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
const tab = ref('sys')
const ac = ref({ api_base: 'https://open.aicoin.com', enabled: true })
const acBusy = ref(''); const acMsg = ref('')
async function acLoad() { try { ac.value = { ...ac.value, ...(await mixApi.aicoinConfigGet()), api_secret: '' } } catch (e) { /* 未配置 */ } }
async function acSave() {
  acBusy.value = 'save'
  try { const r = await mixApi.aicoinConfigSave(ac.value); ElMessage.success(r?.note || '已保存'); acLoad() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') } finally { acBusy.value = '' }
}
async function acTest() {
  acBusy.value = 'test'; acMsg.value = ''
  try { const r = await mixApi.aicoinConfigTest(ac.value); acMsg.value = r.ok ? '连接成功(quota 可读)' : '失败: ' + (r.error || '失败') }
  catch (e) { acMsg.value = '失败: ' + (e?.detail || e?.error || '失败') } finally { acBusy.value = '' }
}
const totpBound = ref(false); const totpUri = ref(''); const totpSecret = ref(''); const totpCode = ref('')
async function totpLoad() { try { totpBound.value = (await mixApi.totpStatus())?.bound } catch (e) { /* */ } }
async function totpProvision() {
  try { const r = await mixApi.totpProvision(); totpUri.value = r.otpauth_uri; totpSecret.value = r.secret }
  catch (e) { ElMessage.error(e?.detail || '需 operator 权限') }
}
async function totpConfirm() {
  try { await mixApi.totpConfirm(totpCode.value); ElMessage.success('TOTP 已启用'); totpUri.value = ''; totpLoad() }
  catch (e) { ElMessage.error(e?.detail || '验证码错误') }
}
onMounted(() => { load(); acLoad(); totpLoad() })
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
