<template>
  <div class="mixacct" @click="menu.open=false">
    <div class="bar">
      <b>账户列表</b>
      <span class="hint">主账号行默认 · 点击展开子账户 · 右键 / ⋮ 账户操作（KMS 行 → 钱包管理菜单）</span>
      <el-button type="warning" size="small" @click="createDlg=true">新建账户</el-button>
    </div>

    <div class="tbl">
      <template v-for="m in tree" :key="m.id">
        <!-- 主账号 / 钱包组 行 -->
        <div class="row master" @click="toggle(m.id)" @contextmenu.prevent="openMenu($event, m)">
          <span class="caret">{{ open.has(m.id) ? '▾' : '▸' }}</span>
          <span class="kind" :class="typeOf(m.id)==='sub' ? 'sub' : m.platformType">
            {{ m.platformType === 'kms_wallet' ? '链上' : (typeOf(m.id)==='sub' ? '子' : '主') }}</span>
          <span class="name" :class="{off: reg[m.id]?.enabled===false}">{{ m.id }}</span>
          <span class="acctname">{{ reg[m.id]?.alias || '—' }}
            <i v-if="reg[m.id]?.machine" class="mch">{{ reg[m.id].machine }}机</i>
            <i v-if="reg[m.id]?.credential" class="cred" :class="reg[m.id].credential.state">{{ credLabel(reg[m.id].credential) }}</i>
          </span>
          <span class="venue">{{ m.venue }} · 域 {{ m.domain }}</span>
          <span class="dot" :class="m.apiStatus" />
          <span v-for="(v,k) in m.metrics" :key="k" class="pair"><em>{{ k }}</em><b :class="{neg:String(v).startsWith('-')}">{{ v }}</b></span>
          <button class="more" @click.stop="openMenu($event, m)">⋮</button>
        </div>
        <!-- 子账户 / 钱包地址 行 -->
        <template v-if="open.has(m.id)">
          <div v-for="c in m.children" :key="c.id" class="row sub" @contextmenu.prevent="openMenu($event, c, m)">
            <span class="caret"></span>
            <span class="kind" :class="c.kind === 'wallet' ? 'kms_wallet' : 'sub'">{{ c.kind === 'wallet' ? '址' : '子' }}</span>
            <span class="name sm" :class="{off: reg[c.id]?.enabled===false}">↳ {{ c.id }}</span>
            <span class="acctname">{{ reg[c.id]?.alias || '—' }}
              <i v-if="reg[c.id]?.machine" class="mch">{{ reg[c.id].machine }}机</i>
              <i v-if="reg[c.id]?.credential" class="cred" :class="reg[c.id].credential.state">{{ credLabel(reg[c.id].credential) }}</i>
            </span>
            <span class="venue">{{ c.venue }}</span>
            <span class="dot" :class="c.apiStatus" />
            <span v-if="c.apiStatus==='restricted'" class="restricted">受限 · -2015 IP 白名单</span>
            <span v-for="(v,k) in c.metrics" :key="k" class="pair"><em>{{ k }}</em><b :class="{neg:String(v).startsWith('-')}">{{ v }}</b></span>
            <el-tag v-if="c.approvalState==='pending_approval'" size="small" type="warning" effect="dark" @click.stop="approve(c)">转账待审批 · 点此审批</el-tag>
            <button class="more" @click.stop="openMenu($event, c, m)">⋮</button>
          </div>
        </template>
      </template>
    </div>

    <!-- 账户右键菜单（cex / kms_wallet 按 platformType 注入） -->
    <Teleport to="body">
      <div v-if="menu.open" class="acct-ctx-backdrop" @click="menu.open=false" @contextmenu.prevent="menu.open=false"></div>
      <div v-if="menu.open" class="acct-ctx" :style="{left:menu.x+'px',top:menu.y+'px'}" @click.stop>
        <div class="h">{{ menu.node?.id }} · {{ menu.node?.venue }}</div>
        <template v-for="it in menuItems" :key="it.key">
          <div v-if="it.dividerBefore" class="dv" />
          <div class="it" :class="it.kind" @click="doAction(it)">{{ it.label }}</div>
        </template>
      </div>
    </Teleport>

    <!-- 设置 API（浏览器端 sealed box 加密，明文永不离开本机） -->
    <el-dialog v-model="apiDlg" :title="`设置 API · ${apiForm.account_key}`" width="480">
      <el-alert type="success" :closable="false" show-icon style="margin-bottom:12px"
        title="明文在你的浏览器内加密后才提交，服务端与数据库全程只见密文；私钥只在 B 机。" />
      <el-form label-width="90">
        <el-form-item label="交易所">
          <el-select v-model="apiForm.venue" style="width:180px">
            <el-option v-for="v in ['binance','okx','bybit','gate','bitget','hyperliquid']" :key="v" :value="v" :label="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签"><el-input v-model="apiForm.label" placeholder="如 合约+借币权限" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="apiForm.apiKey" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="API Secret"><el-input v-model="apiForm.apiSecret" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="Passphrase"><el-input v-model="apiForm.passphrase" type="password" show-password placeholder="OKX/Bitget 需要，其余留空" autocomplete="new-password" /></el-form-item>
        <el-form-item label="IP 代理">
          <el-input v-model="apiForm.proxy_url" placeholder="socks5://user:pass@host:port（留空=直连）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="apiDlg=false">取消</el-button>
        <el-button type="warning" :loading="apiSaving" @click="saveApi">加密并提交</el-button>
      </template>
    </el-dialog>

    <!-- 分配作用域（勾选，不填空框） -->
    <el-dialog v-model="scopeDlg" :title="`分配作用域 · ${scopeForm.account_key}`" width="480">
      <el-radio-group v-model="scopeForm.machine" class="scoperadio">
        <el-radio value="A" border>A 机 · 数据面<span class="sd">52.193.224.137（行情/采样）</span></el-radio>
        <el-radio value="B" border>B 机 · 执行面<span class="sd">54.65.42.207（五所 key / 引擎 / 监控）</span></el-radio>
        <el-radio value="C" border>C 机 · 控制面<span class="sd">57.181.130.126（gateway / 决策 / mix）</span></el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="scopeDlg=false">取消</el-button>
        <el-button type="warning" @click="saveScope">保存</el-button>
      </template>
    </el-dialog>

    <!-- IP 代理（单改，不动密钥） -->
    <el-dialog v-model="proxyDlg" :title="`IP 代理 · ${proxyForm.account_key}`" width="440">
      <el-form label-width="80">
        <el-form-item label="代理出口"><el-input v-model="proxyForm.proxy_url" placeholder="socks5://user:pass@host:port（留空=直连）" /></el-form-item>
      </el-form>
      <div style="font-size:11px;color:var(--el-text-color-placeholder);padding:0 10px">保存后 B 机 cred-agent 下发到该账户交易客户端。当前架构默认直连+交易所 IP 白名单。</div>
      <template #footer>
        <el-button @click="proxyDlg=false">取消</el-button>
        <el-button type="warning" @click="saveProxy">保存</el-button>
      </template>
    </el-dialog>

    <!-- 别名簿（accounts_registry：别名/邮箱/备注,mix 自有域直写） -->
    <el-dialog v-model="regDlg" :title="`别名/备注 · ${regForm.account_key}`" width="420">
      <el-form label-width="70">
        <el-form-item label="别名"><el-input v-model="regForm.alias" placeholder="如：套利1号·币安主" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="regForm.email" placeholder="账户绑定邮箱（备查）" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="regForm.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="regDlg=false">取消</el-button>
        <el-button type="warning" @click="saveRegistry">保存</el-button>
      </template>
    </el-dialog>

    <!-- #3 设置主账户关联（hedge_via_master 对冲腿路由靠此） -->
    <el-dialog v-model="masterDlg" :title="`设置主账户关联 · ${masterForm.account_key}`" width="460">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
        title="子账户关联到哪个主账户，决定 hedge_via_master 的合约对冲腿下到哪个主账户。" />
      <el-form label-width="90">
        <el-form-item label="主账户">
          <el-select v-model="masterForm.master_key" style="width:280px" clearable placeholder="选主账户（清空=解除关联）">
            <el-option v-for="m in masterForm.options" :key="m.account_key" :value="m.account_key"
              :label="`${m.name}（${m.venue||'?'}·${m.book||'TEST'}）`" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="masterDlg=false">取消</el-button>
        <el-button type="warning" @click="saveMaster">保存</el-button>
      </template>
    </el-dialog>

    <!-- #5 账户模式（决定能跑什么策略，经资格矩阵） -->
    <el-dialog v-model="modeDlg" :title="`账户模式 · ${modeForm.account_key}`" width="460">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
        title="经典=钱包分离可跑 C3 借币点差；统一账户=组合保证金跑借贷利率套利。模式经资格矩阵门控策略。" />
      <el-form label-width="90">
        <el-form-item label="账户模式">
          <el-select v-model="modeForm.account_mode" style="width:280px">
            <el-option value="classic" label="经典（钱包分离·C3 借币点差）" />
            <el-option value="portfolio_margin" label="统一账户（组合保证金·借贷利率套利）" />
            <el-option value="cross_margin" label="全仓杠杆" />
            <el-option value="isolated" label="逐仓" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modeDlg=false">取消</el-button>
        <el-button type="warning" @click="saveMode">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建账户：主 / 子 + 别名/邮箱 + 可选 API Key/密码（一步录入，密钥仍浏览器端加密） -->
    <el-dialog v-model="createDlg" title="新建账户" width="480">
      <el-form label-width="96">
        <el-form-item label="账户类型">
          <el-radio-group v-model="createForm.account_type">
            <el-radio-button value="master">主账户</el-radio-button>
            <el-radio-button value="sub">子账户</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="账户标识"><el-input v-model="createForm.account_key" placeholder="唯一键，如 joycar003 / binance-master" /></el-form-item>
        <el-form-item label="交易所">
          <el-select v-model="createForm.venue" style="width:180px">
            <el-option v-for="v in ['binance','okx','bybit','gate','bitget','hyperliquid']" :key="v" :value="v" :label="v" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createForm.account_type==='sub'" label="挂载主账户">
          <el-select v-model="createForm.parent_key" style="width:220px" filterable allow-create default-first-option>
            <el-option v-for="m in masterKeys" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="别名"><el-input v-model="createForm.alias" placeholder="如 套利1号" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="createForm.email" /></el-form-item>
        <el-form-item label="资金账本(Book)">
          <el-select v-model="createForm.book" style="width:220px">
            <el-option value="TEST" label="测试账户（TEST）" />
            <el-option value="HOUSE_RND" label="自营研发金（HOUSE_RND）" />
            <el-option value="CORE_POOL" label="核心投资池（CORE_POOL·投资人资金）" />
          </el-select>
          <div v-if="createForm.book==='CORE_POOL'" class="hint" style="color:#F0B90B">投资人资金，创建需二次确认</div>
        </el-form-item>
        <el-form-item label="账户模式">
          <el-select v-model="createForm.account_mode" style="width:220px">
            <el-option value="classic" label="经典（钱包分离·可跑 C3 借币点差）" />
            <el-option value="portfolio_margin" label="统一账户（组合保证金·跑借贷利率套利）" />
            <el-option value="cross_margin" label="全仓杠杆" />
            <el-option value="isolated" label="逐仓" />
          </el-select>
        </el-form-item>
        <el-divider content-position="left" style="font-size:12px">API 凭证（选填，浏览器端加密）</el-divider>
        <el-form-item label="API Key"><el-input v-model="createForm.apiKey" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="API Secret"><el-input v-model="createForm.apiSecret" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="Passphrase"><el-input v-model="createForm.passphrase" type="password" show-password placeholder="OKX/Bitget 需要" autocomplete="new-password" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg=false">取消</el-button>
        <el-button type="warning" :loading="apiSaving" @click="createAccount">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ACCOUNT_MENUS } from '../../components/PositionTable/strategyColumns'
import { mixApi } from '../../api/mix'
import { sealCredential, maskKey } from '../../api/credCrypto'

const tree = ref([])
const open = reactive(new Set())
const menu = reactive({ open: false, x: 0, y: 0, node: null })
const createDlg = ref(false)
const createForm = reactive({ account_type: 'sub', account_key: '', venue: 'binance', parent_key: '', alias: '', email: '', machine: 'B', book: 'TEST', account_mode: 'classic', apiKey: '', apiSecret: '', passphrase: '' })
const reg = ref({})
const regDlg = ref(false)
const regForm = reactive({ account_key: '', alias: '', email: '', note: '' })
const apiDlg = ref(false), apiSaving = ref(false)
const apiForm = reactive({ account_key: '', venue: 'binance', label: '', apiKey: '', apiSecret: '', passphrase: '', proxy_url: '' })
const proxyDlg = ref(false)
const proxyForm = reactive({ account_key: '', proxy_url: '' })
const scopeDlg = ref(false)
const scopeForm = reactive({ account_key: '', machine: 'B' })
const masterDlg = ref(false)
const masterForm = reactive({ account_key: '', master_key: '', options: [] })
const modeDlg = ref(false)
const modeForm = reactive({ account_key: '', account_mode: 'classic' })
async function saveMaster() {
  try { await mixApi.setAccountMaster(masterForm.account_key, masterForm.master_key)
    ElMessage.success(masterForm.master_key ? '主账户关联已设' : '已解除关联'); masterDlg.value = false; loadRegistry(); load() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
}
async function saveMode() {
  try { await mixApi.setAccountMode(modeForm.account_key, modeForm.account_mode)
    ElMessage.success('账户模式已设'); modeDlg.value = false; loadRegistry(); load() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
}
async function saveScope() {
  try {
    const r = await mixApi.accountAction(scopeForm.account_key, 'assign_scope', { machine: scopeForm.machine })
    ElMessage.success(`已分配 ${r.machine} 机：${r.desc}`)
    scopeDlg.value = false; loadRegistry()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '失败') }
}
const masterKeys = computed(() => Object.values(reg.value).filter(r => r.account_type === 'master').map(r => r.account_key))

async function encryptCred(apiKey, apiSecret, passphrase) {
  const { pubkey } = await mixApi.credPubkey()
  return { ciphertext: sealCredential(pubkey, apiKey, apiSecret, passphrase || ''), key_mask: maskKey(apiKey) }
}
const typeOf = id => reg.value[id]?.account_type || 'master'
const credLabel = c => ({ active: `🔑${c.key_mask||'已配'}`, pending: '🔑下发中', error: '🔑异常', revoked: '🔑已吊销' }[c.state] || '')

const menuItems = computed(() => menu.node
  ? [...(ACCOUNT_MENUS[menu.node.platformType] || []),
     ...(typeOf(menu.node.id) === 'sub'
       ? [{ key: 'set_master', label: '设置主账户关联…', kind: 'registry', dividerBefore: true }] : []),
     { key: 'set_mode', label: '账户模式…', kind: 'registry',
       dividerBefore: typeOf(menu.node.id) !== 'sub' },
     { key: 'edit_registry', label: '别名 / 邮箱…', kind: 'registry' }]
  : [])

function toggle(id) { open.has(id) ? open.delete(id) : open.add(id) }
function openMenu(e, node) {
  menu.open = true
  menu.x = Math.min(e.clientX, window.innerWidth - 210)
  menu.y = Math.min(e.clientY, window.innerHeight - 300)
  menu.node = node
}
async function doAction(it) {
  menu.open = false
  const node = menu.node
  try {
    if (it.key === 'edit_registry') {
      const cur = reg.value[node.id] || {}
      Object.assign(regForm, { account_key: node.id, alias: cur.alias || '', email: cur.email || '', note: cur.note || '' })
      regDlg.value = true; return
    }
    if (it.key === 'assign_scope') {
      scopeForm.account_key = node.id
      scopeForm.machine = reg.value[node.id]?.machine || 'B'
      scopeDlg.value = true; return
    }
    if (it.key === 'set_master') {   // #3 设主子关联
      masterForm.account_key = node.id
      masterForm.master_key = reg.value[node.id]?.parent_key || ''
      try { const r = await mixApi.accountMasters(node.venue || ''); masterForm.options = r.masters || [] }
      catch { masterForm.options = [] }
      masterDlg.value = true; return
    }
    if (it.key === 'set_mode') {   // #5 设账户模式
      modeForm.account_key = node.id
      modeForm.account_mode = reg.value[node.id]?.account_mode || 'classic'
      modeDlg.value = true; return
    }
    if (it.key === 'create_sub' || it.key === 'create_wallet') { createDlg.value = true; return }
    if (it.key === 'set_api') {
      const cur = reg.value[node.id]?.credential || {}
      Object.assign(apiForm, { account_key: node.id, venue: node.venue || 'binance', label: '',
        apiKey: '', apiSecret: '', passphrase: '', proxy_url: cur.proxy_url || '' })
      apiDlg.value = true; return
    }
    if (it.key === 'ip_proxy') {
      const cur = reg.value[node.id]?.credential || {}
      Object.assign(proxyForm, { account_key: node.id, proxy_url: cur.proxy_url || '' })
      proxyDlg.value = true; return
    }
    if (it.confirm) await ElMessageBox.confirm(`确认对 ${node.id} 执行「${it.label}」？`, '危险操作', { type: 'warning' })
    if (it.key === 'transfer') {
      const r = await mixApi.kmsTransfer({ from: node.id, amount: 1000 })
      ElMessage.warning(`转账已发起 → ${r.state}（发起人 ≠ 审批人，等待审批）`)
      return load()
    }
    // 真实动作:verify/refresh 回活体状态;toggle 回标记;ip_whitelist 回白名单指引;purge 清别名簿
    const r = await mixApi.accountAction(node.id, it.key)
    if (it.key === 'verify' || it.key === 'refresh') {
      ElMessageBox.alert(
        `鉴权: ${r.auth}\n权益: ${r.equity_usdt ?? '—'} U\n快照龄: ${r.age_sec}s\n${r.note}`,
        `${node.id} · ${it.label}`, { customStyle: { whiteSpace: 'pre-line' } })
    } else if (it.key === 'toggle') {
      ElMessage.success(`${node.id} 已${r.enabled ? '启用' : '停用'}（${r.note}）`)
      loadRegistry()
    } else if (it.key === 'ip_whitelist') {
      ElMessageBox.alert(
        Object.entries(r.machines).map(([k, v]) => `${k} 机 = ${v}`).join('\n')
        + `\n\n当前鉴权: ${r.current_auth}\n${r.note}`,
        'IP 白名单指引', { customStyle: { whiteSpace: 'pre-line' } })
    } else if (it.key === 'purge') {
      ElMessage.success(r.note); loadRegistry()
    } else {
      ElMessage.success(`完成：${it.label}`)
    }
    if (it.key === 'refresh') load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '失败') }
}
async function approve(c) {
  await ElMessageBox.confirm(`审批 ${c.id} 的待审批转账？（审批人身份校验由后端强制）`, 'KMS 审批', { type: 'warning' })
  const r = await mixApi.kmsApprove(c.id)
  ElMessage.success(`已执行：${r.state} · 审计 ${r.auditId}`)
}
async function saveApi() {
  if (!apiForm.apiKey || !apiForm.apiSecret) return ElMessage.warning('API Key/Secret 必填')
  apiSaving.value = true
  try {
    const enc = await encryptCred(apiForm.apiKey, apiForm.apiSecret, apiForm.passphrase)
    await mixApi.credPut({ account_key: apiForm.account_key, venue: apiForm.venue, label: apiForm.label,
      proxy_url: apiForm.proxy_url, ...enc })
    ElMessage.success('已加密提交，B 机 agent 60s 内下发生效')
    apiDlg.value = false; loadRegistry()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '提交失败') } finally { apiSaving.value = false }
}
async function saveProxy() {
  try { await mixApi.credProxy(proxyForm.account_key, { proxy_url: proxyForm.proxy_url }); ElMessage.success('代理已保存'); proxyDlg.value = false; loadRegistry() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败（先设置 API）') }
}
async function createAccount() {
  if (!createForm.account_key) return ElMessage.warning('账户标识必填')
  // #1 护栏:CORE_POOL/SMA(投资人资金)二次确认
  let confirm = false
  if (createForm.book === 'CORE_POOL' || createForm.book.startsWith('SMA')) {
    try { await ElMessageBox.confirm(`「${createForm.book}」是投资人/客户资金账户，确认创建？`, '二次确认', { type: 'warning' }); confirm = true }
    catch { return }
  }
  apiSaving.value = true
  try {
    await mixApi.registryFull({ account_key: createForm.account_key, account_type: createForm.account_type,
      parent_key: createForm.parent_key, alias: createForm.alias, email: createForm.email, machine: createForm.machine,
      book: createForm.book, account_mode: createForm.account_mode, confirm })
    if (createForm.apiKey && createForm.apiSecret) {
      const enc = await encryptCred(createForm.apiKey, createForm.apiSecret, createForm.passphrase)
      await mixApi.credPut({ account_key: createForm.account_key, venue: createForm.venue, ...enc })
    }
    ElMessage.success(`已创建${createForm.account_type === 'master' ? '主账户' : '子账户'}`)
    createDlg.value = false; loadRegistry()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '创建失败') } finally { apiSaving.value = false }
}
async function saveRegistry() {
  try {
    await mixApi.registryPut({ ...regForm })
    ElMessage.success('别名簿已保存')
    regDlg.value = false; loadRegistry()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
}
async function loadRegistry() {
  try {
    const rows = await mixApi.registryList()
    reg.value = Object.fromEntries((rows || []).map(r => [r.account_key, r]))
    const tree2 = await mixApi.registryTree()
    for (const m of (tree2.masters || [])) reg.value[m.account_key] = { ...reg.value[m.account_key], ...m }
    for (const m of (tree2.masters || [])) for (const s of (m.children || [])) reg.value[s.account_key] = { ...reg.value[s.account_key], ...s }
    for (const o of (tree2.orphans || [])) reg.value[o.account_key] = { ...reg.value[o.account_key], ...o }
  } catch (e) { /* 降级：无别名不阻塞账户树 */ }
}
async function load() {
  tree.value = await mixApi.accounts()
  tree.value.forEach(m => open.add(m.id))   // 默认全展
}
onMounted(() => { load(); loadRegistry() })
</script>

<style scoped lang="scss">
.mixacct { display: flex; flex-direction: column; gap: 10px; }
.bar { display: flex; align-items: center; gap: 12px;
  b { font-size: 14px; } .hint { flex: 1; font-size: 11px; color: var(--el-text-color-secondary); } }
.tbl { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 6px; display: flex; flex-direction: column; gap: 2px; }
.row { display: flex; align-items: center; gap: 10px; padding: 0 10px; border-radius: 6px; cursor: pointer; font-size: 12px; height: 34px;
  &.master { background: var(--el-fill-color); font-weight: 700; }
  &.sub { background: var(--el-fill-color-lighter); padding-left: 26px; height: 30px; } }
.caret { width: 12px; color: var(--el-text-color-placeholder); }
.kind { padding: 0 5px; border-radius: 4px; font-size: 10px; font-weight: 800;
  &.cex { background: rgba(240,185,11,.15); color: #B8860B; }
  &.kms_wallet { background: rgba(45,212,191,.15); color: #0d9488; }
  &.sub { background: var(--el-fill-color-dark); color: var(--el-text-color-secondary); } }
.name { min-width: 130px; &.sm { font-weight: 600; }
  &.off { opacity: .45; text-decoration: line-through; } }
.acctname { min-width: 120px; font-size: 11px; color: #F0B90B; font-weight: 700;
  .mch { font-style: normal; margin-left: 6px; padding: 0 5px; border-radius: 4px; font-size: 9px;
    background: rgba(45,212,191,.14); color: #2DD4BF; font-weight: 800; }
  .cred { font-style: normal; margin-left: 4px; padding: 0 5px; border-radius: 4px; font-size: 9px; font-weight: 700;
    &.active { background: rgba(14,203,129,.14); color: #0ECB81; }
    &.pending { background: rgba(240,185,11,.14); color: #F0B90B; }
    &.error { background: rgba(246,70,93,.14); color: #F6465D; }
    &.revoked { background: rgba(94,102,115,.14); color: #5E6673; } } }
.venue { color: var(--el-text-color-secondary); font-size: 11px; min-width: 110px; }
.dot { width: 7px; height: 7px; border-radius: 50%;
  &.ok { background: #0ECB81; } &.restricted { background: #F6465D; } &.healing { background: #F0B90B; } }
.restricted { color: #F6465D; font-size: 10px; font-weight: 700; }
.pair { flex: 1; display: inline-flex; justify-content: flex-end; gap: 4px; align-items: baseline; min-width: 0; overflow: hidden;
  em { font-style: normal; color: var(--el-text-color-placeholder); font-size: 10px; white-space: nowrap; }
  b { font-size: 11.5px; white-space: nowrap; &.neg { color: #F6465D; } } }
.more { background: var(--el-fill-color-dark); border: 1px solid var(--el-border-color); border-radius: 4px; color: var(--el-text-color-secondary); cursor: pointer; padding: 0 6px; font-weight: 800; }
</style>

<style lang="scss">
.acct-ctx { position: fixed; z-index: 9999; width: 196px; background: #1E232B; border: 1px solid #262B33; border-radius: 10px; padding: 5px;
  box-shadow: 0 8px 24px rgba(0,0,0,.6); font-size: 11px; color: #EAECEF;
  .h { padding: 5px 10px 4px; color: #5E6673; font-size: 9px; font-weight: 600; }
  .dv { height: 1px; background: #262B33; margin: 2px 0; }
  .it { padding: 6px 10px; border-radius: 6px; font-weight: 600; cursor: pointer;
    &:hover { background: #20242C; }
    &.danger { color: #F6465D; } &.strategy { color: #A78BFA; } &.link { color: #4A9CFF; } } }
</style>
