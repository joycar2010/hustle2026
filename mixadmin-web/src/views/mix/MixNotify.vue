<template>
  <div class="mixnotify">
    <el-tabs v-model="tab" class="ntabs">

      <!-- ① 渠道与节流（全局统一,dcm:notify:config 热下发） -->
      <el-tab-pane label="渠道与节流" name="throttle">
        <div class="cards2">
          <div class="card">
            <div class="hd"><b>全局节流</b><span class="sub">策略只声明事件与级别；间隔/次数/令牌桶在此统一配置（保存即热下发 dcm 全家）</span></div>
            <el-form label-width="130" style="max-width:520px">
              <el-form-item label="通知渠道">
                <el-checkbox-group v-model="cfg.channels">
                  <el-checkbox value="feishu">飞书</el-checkbox>
                  <el-checkbox value="marquee">跑马灯</el-checkbox>
                  <el-checkbox value="modal">大红弹框（强平级）</el-checkbox>
                  <el-checkbox value="email">邮件</el-checkbox>
                </el-checkbox-group>
              </el-form-item>
              <el-form-item label="提醒间隔 (秒)"><el-input-number v-model="cfg.intervalSec" :min="30" :step="30" /></el-form-item>
              <el-form-item label="每小时上限 (次)"><el-input-number v-model="cfg.maxPerHour" :min="1" :max="60" /></el-form-item>
              <el-form-item label="冷却时间 (秒)"><el-input-number v-model="cfg.cooldownSec" :min="0" :step="60" /></el-form-item>
              <el-form-item label="令牌桶节流">
                <div class="tb">
                  <span>速率</span><el-input-number v-model="cfg.tokenBucket.rate" :min="0.1" :step="0.5" :precision="1" size="small" />
                  <span>突发</span><el-input-number v-model="cfg.tokenBucket.burst" :min="1" :max="10" size="small" />
                  <em>（rate 条/秒 · burst 突发容量；FATAL 级 300s/1 硬地板不受影响）</em>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="warning" :loading="saving" @click="saveThrottle">保存并热下发</el-button>
                <el-button @click="loadThrottle">还原</el-button>
              </el-form-item>
            </el-form>
          </div>
          <div class="card">
            <div class="hd"><b>渠道接入</b><span class="sub">飞书=群机器人 webhook；邮件=SMTP 配置留位（未接线前不假发送）</span></div>
            <el-form label-width="130" style="max-width:520px">
              <el-form-item label="飞书 Webhook">
                <el-input v-model="ch.feishuWebhook" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/…" />
              </el-form-item>
              <el-form-item label="SMTP 主机"><el-input v-model="ch.email.host" placeholder="留位,暂不发送" /></el-form-item>
              <el-form-item label="SMTP 端口"><el-input v-model="ch.email.port" style="max-width:140px" /></el-form-item>
              <el-form-item label="发件账号"><el-input v-model="ch.email.user" /></el-form-item>
              <el-form-item label="发件人显示"><el-input v-model="ch.email.sender" /></el-form-item>
              <el-form-item>
                <el-button type="warning" @click="saveChannels">保存渠道</el-button>
                <el-tag v-if="ch.feishuConfigured" type="success" effect="plain" size="small" style="margin-left:8px">飞书已配置</el-tag>
              </el-form-item>
            </el-form>
            <div class="note">
              <b>分级策略</b>
              <p>FATAL（强平/裸空/借币服务异常）：绕过常规节流（300s/1 硬地板），飞书 + 大红弹框即时；WARN：受令牌桶节流，飞书 + 跑马灯；INFO：仅跑马灯 + 告警时间线落库。告警条目统一带策略徽章（S1–S6）。</p>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ② 网站维护与公告（原网站通知并入,kind 区分） -->
      <el-tab-pane label="网站维护与公告" name="notices">
        <div class="card">
          <div class="hd"><b>维护 / 公告列表</b>
            <el-button size="small" type="warning" @click="editNotice()">新建</el-button>
          </div>
          <el-table :data="notices" size="small">
            <el-table-column label="类型" width="90">
              <template #default="{row}"><el-tag :type="row.kind==='maintenance'?'danger':'warning'" size="small" effect="plain">{{ row.kind==='maintenance'?'维护':'公告' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="160" />
            <el-table-column prop="content" label="内容" min-width="240" show-overflow-tooltip />
            <el-table-column label="生效" width="70">
              <template #default="{row}"><span :class="row.enabled?'up':'dim'">{{ row.enabled?'启用':'停用' }}</span></template>
            </el-table-column>
            <el-table-column label="时间窗" width="200">
              <template #default="{row}">{{ (row.starts_at||'').slice(5,16) || '—' }} ~ {{ (row.ends_at||'').slice(5,16) || '—' }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="更新" width="100" />
            <el-table-column label="操作" width="130">
              <template #default="{row}">
                <el-button size="small" link type="warning" @click="editNotice(row)">编辑</el-button>
                <el-button size="small" link type="danger" @click="delNotice(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="note"><p>启用的「维护」在用户端渲染全屏蒙层，「公告」渲染顶部横幅（用户端读开放端点 /site/notices/active）。</p></div>
        </div>
      </el-tab-pane>

      <!-- ③ 通知模板 -->
      <el-tab-pane label="通知模板" name="templates">
        <div class="card">
          <div class="hd"><b>模板列表</b><span class="sub">正文支持 {var} 占位；模板供手动广播与将来自动事件套用</span>
            <el-button size="small" type="warning" @click="editTpl()">新建</el-button>
          </div>
          <el-table :data="templates" size="small">
            <el-table-column prop="tkey" label="模板键" width="160" />
            <el-table-column prop="title" label="标题" min-width="140" />
            <el-table-column prop="body" label="正文" min-width="220" show-overflow-tooltip />
            <el-table-column label="级别" width="80">
              <template #default="{row}"><el-tag :type="{info:'info',warn:'warning',fatal:'danger'}[row.level]" size="small" effect="plain">{{ row.level }}</el-tag></template>
            </el-table-column>
            <el-table-column label="渠道" width="140">
              <template #default="{row}">{{ (row.channels||[]).join(' / ') }}</template>
            </el-table-column>
            <el-table-column label="操作" width="170">
              <template #default="{row}">
                <el-button size="small" link type="warning" @click="editTpl(row)">编辑</el-button>
                <el-button size="small" link @click="useTpl(row)">去广播</el-button>
                <el-button size="small" link type="danger" @click="delTpl(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ④ 手动广播 -->
      <el-tab-pane label="手动广播" name="broadcast">
        <div class="card" style="max-width:640px">
          <div class="hd"><b>发送通知</b><span class="sub">跑马灯即时到端（Rust hub 中继）；飞书走 webhook；全量落发送日志+审计</span></div>
          <el-form label-width="90">
            <el-form-item label="标题"><el-input v-model="bc.title" maxlength="120" /></el-form-item>
            <el-form-item label="正文"><el-input v-model="bc.text" type="textarea" :rows="3" maxlength="2000" /></el-form-item>
            <el-form-item label="级别">
              <el-radio-group v-model="bc.level" size="small">
                <el-radio-button value="info">info</el-radio-button>
                <el-radio-button value="warn">warn</el-radio-button>
                <el-radio-button value="fatal">fatal</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="渠道">
              <el-checkbox-group v-model="bc.channels">
                <el-checkbox value="marquee">跑马灯</el-checkbox>
                <el-checkbox value="feishu">飞书</el-checkbox>
                <el-checkbox value="email" disabled>邮件（未接线）</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item>
              <el-button type="warning" :loading="sending" @click="send">发送</el-button>
              <span v-if="lastResult" class="lastres">{{ lastResult }}</span>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- ⑤ 发送日志 -->
      <el-tab-pane label="发送日志" name="logs">
        <div class="card">
          <div class="hd"><b>mix 主动发送记录</b><span class="sub">dcm 服务侧告警见「运维面板/告警时间线」（alerts_log 独立账）</span>
            <el-button size="small" @click="loadLogs">刷新</el-button>
          </div>
          <el-table :data="logs" size="small">
            <el-table-column prop="ts" label="时间" width="130" />
            <el-table-column prop="channel" label="渠道" width="80" />
            <el-table-column prop="title" label="标题" min-width="140" />
            <el-table-column prop="body" label="内容" min-width="200" show-overflow-tooltip />
            <el-table-column label="结果" width="80">
              <template #default="{row}"><span :class="row.ok?'up':'down'">{{ row.ok?'成功':'失败' }}</span></template>
            </el-table-column>
            <el-table-column prop="detail" label="详情" min-width="140" show-overflow-tooltip />
            <el-table-column prop="operator" label="操作者" width="100" />
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 公告编辑弹窗 -->
    <el-dialog v-model="noticeDlg" :title="nf.id?'编辑公告/维护':'新建公告/维护'" width="520">
      <el-form label-width="80">
        <el-form-item label="类型">
          <el-radio-group v-model="nf.kind">
            <el-radio-button value="notice">公告</el-radio-button>
            <el-radio-button value="maintenance">维护</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="nf.title" maxlength="200" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="nf.content" type="textarea" :rows="4" maxlength="4000" /></el-form-item>
        <el-form-item label="时间窗">
          <el-date-picker v-model="nf.window" type="datetimerange" range-separator="~" start-placeholder="开始(可空)" end-placeholder="结束(可空)" size="small" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="nf.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="noticeDlg=false">取消</el-button>
        <el-button type="warning" @click="saveNotice">保存</el-button>
      </template>
    </el-dialog>

    <!-- 模板编辑弹窗 -->
    <el-dialog v-model="tplDlg" :title="tf.id?'编辑模板':'新建模板'" width="520">
      <el-form label-width="80">
        <el-form-item label="模板键"><el-input v-model="tf.tkey" :disabled="!!tf.id" placeholder="如 maintenance_notice" /></el-form-item>
        <el-form-item label="标题"><el-input v-model="tf.title" maxlength="200" /></el-form-item>
        <el-form-item label="正文"><el-input v-model="tf.body" type="textarea" :rows="4" maxlength="4000" /></el-form-item>
        <el-form-item label="级别">
          <el-radio-group v-model="tf.level" size="small">
            <el-radio-button value="info">info</el-radio-button>
            <el-radio-button value="warn">warn</el-radio-button>
            <el-radio-button value="fatal">fatal</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="渠道">
          <el-checkbox-group v-model="tf.channels">
            <el-checkbox value="marquee">跑马灯</el-checkbox>
            <el-checkbox value="feishu">飞书</el-checkbox>
            <el-checkbox value="email">邮件</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tplDlg=false">取消</el-button>
        <el-button type="warning" @click="saveTpl">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const tab = ref('throttle')
const cfg = ref({ channels: [], intervalSec: 300, maxPerHour: 6, cooldownSec: 600, tokenBucket: { rate: 1, burst: 3 } })
const ch = ref({ feishuWebhook: '', feishuConfigured: false, email: { host: '', port: '', user: '', sender: '' } })
const saving = ref(false)
const notices = ref([])
const templates = ref([])
const logs = ref([])
const sending = ref(false)
const lastResult = ref('')
const bc = reactive({ title: '', text: '', level: 'info', channels: ['marquee'] })
const noticeDlg = ref(false)
const nf = reactive({ id: null, kind: 'notice', title: '', content: '', enabled: false, window: null })
const tplDlg = ref(false)
const tf = reactive({ id: null, tkey: '', title: '', body: '', level: 'info', channels: ['marquee'] })

async function loadThrottle() {
  try {
    const r = await mixApi.notifyGet()
    cfg.value = { ...cfg.value, ...r, tokenBucket: { ...cfg.value.tokenBucket, ...(r.tokenBucket || {}) } }
  } catch (e) { ElMessage.error(e?.error || '读取失败') }
}
async function saveThrottle() {
  saving.value = true
  try {
    const r = await mixApi.notifySave(cfg.value)
    ElMessage.success(`已保存（${r?.note || '全局生效'}）`)
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
async function loadChannels() { try { ch.value = { ...ch.value, ...(await mixApi.channelsGet()) } } catch (e) { /* 降级 */ } }
async function saveChannels() {
  try { await mixApi.channelsPut({ feishuWebhook: ch.value.feishuWebhook, email: ch.value.email }); ElMessage.success('渠道已保存'); loadChannels() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
}
async function loadNotices() { try { notices.value = await mixApi.notices() } catch (e) { notices.value = [] } }
function editNotice(row) {
  Object.assign(nf, row
    ? { id: row.id, kind: row.kind, title: row.title, content: row.content, enabled: row.enabled,
        window: (row.starts_at || row.ends_at) ? [row.starts_at, row.ends_at] : null }
    : { id: null, kind: 'notice', title: '', content: '', enabled: false, window: null })
  noticeDlg.value = true
}
async function saveNotice() {
  try {
    await mixApi.noticePut({ id: nf.id, kind: nf.kind, title: nf.title, content: nf.content, enabled: nf.enabled,
      starts_at: nf.window?.[0] ? new Date(nf.window[0]).toISOString() : null,
      ends_at: nf.window?.[1] ? new Date(nf.window[1]).toISOString() : null })
    ElMessage.success('已保存'); noticeDlg.value = false; loadNotices()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
}
async function delNotice(row) {
  await ElMessageBox.confirm(`删除「${row.title}」？`, '删除', { type: 'warning' })
  await mixApi.noticeDel(row.id); ElMessage.success('已删除'); loadNotices()
}
async function loadTpls() { try { templates.value = await mixApi.templates() } catch (e) { templates.value = [] } }
function editTpl(row) {
  Object.assign(tf, row
    ? { id: row.id, tkey: row.tkey, title: row.title, body: row.body, level: row.level, channels: [...(row.channels || [])] }
    : { id: null, tkey: '', title: '', body: '', level: 'info', channels: ['marquee'] })
  tplDlg.value = true
}
async function saveTpl() {
  if (!tf.tkey) return ElMessage.warning('模板键必填')
  try { await mixApi.templatePut({ ...tf }); ElMessage.success('已保存'); tplDlg.value = false; loadTpls() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
}
async function delTpl(row) {
  await ElMessageBox.confirm(`删除模板 ${row.tkey}？`, '删除', { type: 'warning' })
  await mixApi.templateDel(row.id); ElMessage.success('已删除'); loadTpls()
}
function useTpl(row) {
  Object.assign(bc, { title: row.title, text: row.body, level: row.level, channels: (row.channels || ['marquee']).filter(c => c !== 'email') })
  tab.value = 'broadcast'
}
async function loadLogs() { try { logs.value = await mixApi.notifyLogs() } catch (e) { logs.value = [] } }
async function send() {
  if (!bc.text) return ElMessage.warning('正文必填')
  sending.value = true
  try {
    const r = await mixApi.notifyBroadcast({ ...bc })
    lastResult.value = Object.entries(r.results || {}).map(([k, v]) => `${k}:${v}`).join('  ')
    ElMessage.success('已发送'); loadLogs()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '发送失败') }
  finally { sending.value = false }
}
onMounted(() => { loadThrottle(); loadChannels(); loadNotices(); loadTpls(); loadLogs() })
</script>

<style scoped lang="scss">
.mixnotify { display: flex; flex-direction: column; gap: 12px; }
.cards2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 12px; align-items: start; }
.card { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 14px 16px; background: var(--mix-card, #181B21);
  .hd { display: flex; gap: 10px; align-items: baseline; margin-bottom: 12px;
    b { font-size: 13px; } .sub { flex: 1; color: var(--el-text-color-secondary); font-size: 11px; } } }
.note { font-size: 12px; color: var(--el-text-color-regular); margin-top: 10px;
  p { margin: 6px 0 0; color: var(--el-text-color-secondary); } }
.tb { display: flex; gap: 8px; align-items: center; font-size: 12px;
  em { font-style: normal; color: var(--el-text-color-placeholder); font-size: 11px; } }
.up { color: #0ECB81; font-weight: 700; }
.down { color: #F6465D; font-weight: 700; }
.dim { color: var(--el-text-color-placeholder); }
.lastres { margin-left: 10px; font-size: 11px; color: var(--el-text-color-secondary); }
.ntabs :deep(.el-tabs__item) { color: var(--el-text-color-secondary); font-weight: 600; }
.ntabs :deep(.el-tabs__item.is-active) { color: #F0B90B; }
.ntabs :deep(.el-tabs__active-bar) { background: #F0B90B; }
</style>
