<template>
  <div class="mixacct" @click="menu.open=false">
    <el-tabs v-model="atab">
    <el-tab-pane label="托管与权限" name="custody">
      <div class="cbar"><b>Venue 账户与托管</b>
        <span class="hint">密钥永不显示 · 换钥/开提现/地址管理=cred-agent 永久 deny(纵深防御,不由 policy 放开)</span>
        <el-button size="small" @click="loadCustody" style="margin-left:auto">刷新</el-button></div>
      <el-table :data="custody" size="small" stripe>
        <el-table-column label="Venue" width="90"><template #default="{row}"><b>{{ row.venue }}</b></template></el-table-column>
        <el-table-column label="托管模式" width="170"><template #default="{row}">{{ custodyLabel(row.custody_mode) }}</template></el-table-column>
        <el-table-column label="权益U" width="90" align="right"><template #default="{row}">{{ row.equity ?? 'N/A' }}</template></el-table-column>
        <el-table-column label="读权限" width="70"><template #default="{row}"><span :class="row.probe_read?'ok':'bad'">{{ row.probe_read?'✓':'✗' }}</span></template></el-table-column>
        <el-table-column label="交易权限" width="80"><template #default="{row}"><span :class="row.probe_trade?'ok':'bad'">{{ row.probe_trade?'✓':'✗' }}</span></template></el-table-column>
        <el-table-column label="提现权限" width="140"><template #default="{row}"><span class="deny">{{ row.probe_withdraw }}</span></template></el-table-column>
        <el-table-column label="划转权限" width="140"><template #default="{row}"><span class="deny">{{ row.probe_transfer }}</span></template></el-table-column>
        <el-table-column label="Credential Epoch" width="130" align="center"><template #default="{row}">{{ row.credential_epoch ?? 'N/A' }}</template></el-table-column>
        <el-table-column label="提现 p95/样本" width="120"><template #default="{row}">{{ row.wd_p95_sec != null ? Math.round(row.wd_p95_sec/60)+'m' : 'N/A' }} / {{ row.wd_sample_n ?? 0 }}</template></el-table-column>
        <el-table-column label="模式" width="120"><template #default="{row}"><span :class="'m-'+row.mode">{{ row.mode || 'N/A' }}</span>
          <span v-if="row.err" class="bad" style="font-size:10px"> · {{ row.err.slice(0,20) }}</span></template></el-table-column>
      </el-table>
      <div class="fnote">权限探针=只读推断(账户快照 ok 反证读/交易权限),绝不主动调提现/划转 endpoint 试探(会触发平台风控);
        换钥、开启提现、地址管理、删号=独立高危确认页(此表不放危险快捷图标,V2 §15)。</div>
    </el-tab-pane>
    <el-tab-pane label="账户明细(操作)" name="list">
    <div class="bar">
      <b>账户列表</b>
      <span class="hint">勾选账户→批量设模式/账本 · PC 行内图标或右键操作</span>
      <span class="spacer" />
      <span v-if="sel.size" class="selinfo">已选 {{ sel.size }}</span>
      <el-button size="small" :disabled="!sel.size" @click="openBatch">批量设置…</el-button>
      <el-button type="warning" size="small" @click="createDlg=true">新建账户</el-button>
    </div>

    <div class="tbl">
      <div class="thead">
        <span class="c-cb"><input type="checkbox" :checked="allSel" @change="toggleAll" /></span>
        <span class="c-name">账户</span>
        <span class="c-venue">平台</span>
        <span class="c-book">账本</span>
        <span class="c-cred">凭证</span>
        <span class="c-mode">模式</span>
        <span class="c-eq">余额</span>
        <span class="c-sub">子账户</span>
        <span class="c-act">操作</span>
      </div>
      <template v-for="m in tree" :key="m.id">
        <!-- 主账号 / 钱包组 行 -->
        <div class="row master" @contextmenu.prevent="openMenu($event, m)">
          <span class="c-cb"><input type="checkbox" :checked="sel.has(m.id)" @click.stop="toggleSel(m.id)" /></span>
          <span class="c-name" @click="toggle(m.id)">
            <span class="caret">{{ open.has(m.id) ? '▾' : '▸' }}</span>
            <span class="kind" :class="m.platformType==='kms_wallet' ? 'kms_wallet' : 'master'">{{ m.platformType==='kms_wallet' ? '链上' : '主' }}</span>
            <b class="nm" :class="{off: reg[m.id]?.enabled===false}">{{ mv(m,'账户') || m.id }}</b>
            <i class="dot" :class="m.apiStatus" />
          </span>
          <span class="c-venue">{{ m.venue }}</span>
          <span class="c-book" :class="'bk-'+(mv(m,'Book')||'TEST')">{{ mv(m,'Book')||'—' }}</span>
          <span class="c-cred">{{ mv(m,'凭证') || (m.platformType==='kms_wallet'?'钱包':'—') }}</span>
          <span class="c-mode">{{ mv(m,'模式') || '—' }}</span>
          <span class="c-eq">{{ mv(m,'合计净值') || mv(m,'净值') || '—' }}</span>
          <span class="c-sub">{{ mv(m,'子账户') || mv(m,'钱包') || '—' }}</span>
          <span class="c-act">
            <el-icon v-for="a in actionsOf(m)" :key="a.key" class="act" :class="{danger:a.danger}" :title="a.label" @click.stop="doAction(a, m)"><component :is="a.icon" /></el-icon>
            <button class="more" @click.stop="openMenu($event, m)"><el-icon><MoreFilled /></el-icon></button>
          </span>
        </div>
        <!-- 子账户 / 钱包地址 行 -->
        <template v-if="open.has(m.id)">
          <div v-for="c in m.children" :key="c.id" class="row sub" @contextmenu.prevent="openMenu($event, c, m)">
            <span class="c-cb"><input type="checkbox" :checked="sel.has(c.id)" @click.stop="toggleSel(c.id)" /></span>
            <span class="c-name">
              <span class="caret sub" />
              <span class="kind" :class="c.kind==='wallet' ? 'kms_wallet' : 'sub'">{{ c.kind==='wallet' ? '址' : '子' }}</span>
              <b class="nm sm" :class="{off: reg[c.id]?.enabled===false}">{{ mv(c,'账户') || c.id }}</b>
              <i class="dot" :class="c.apiStatus" />
            </span>
            <span class="c-venue">{{ c.venue }}</span>
            <span class="c-book" :class="'bk-'+(mv(c,'Book')||'TEST')">{{ mv(c,'Book')||'—' }}</span>
            <span class="c-cred">{{ mv(c,'凭证') || (c.kind==='wallet'?'钱包':'—') }}</span>
            <span class="c-mode">{{ mv(c,'模式') || '—' }}</span>
            <span class="c-eq">{{ mv(c,'净值') || mv(c,'杠杆净资产') || '—' }}</span>
            <span class="c-sub"><el-tag v-if="c.approvalState==='pending_approval'" size="small" type="warning" effect="dark" @click.stop="approve(c)">待审批</el-tag></span>
            <span class="c-act">
              <el-icon v-for="a in actionsOf(c)" :key="a.key" class="act" :class="{danger:a.danger}" :title="a.label" @click.stop="doAction(a, c)"><component :is="a.icon" /></el-icon>
              <button class="more" @click.stop="openMenu($event, c, m)"><el-icon><MoreFilled /></el-icon></button>
            </span>
          </div>
        </template>
      </template>
    </div>

    <!-- 批量设置(勾选后) -->
    <el-dialog v-model="batchDlg" :title="`批量设置 · 已选 ${sel.size} 个账户`" width="440">
      <el-form label-width="90">
        <el-form-item label="设置项">
          <el-radio-group v-model="batchForm.field" size="small">
            <el-radio-button value="account_mode">账户模式</el-radio-button>
            <el-radio-button value="book">资金账本</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="batchForm.field==='account_mode'" label="账户模式">
          <el-select v-model="batchForm.account_mode" style="width:240px">
            <el-option value="classic" label="经典（钱包分离·C3 借币点差）" />
            <el-option value="portfolio_margin" label="统一账户（组合保证金·借贷套利）" />
            <el-option value="cross_margin" label="全仓杠杆" />
            <el-option value="isolated" label="逐仓" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="资金账本">
          <el-select v-model="batchForm.book" style="width:240px">
            <el-option value="TEST" label="测试账户（TEST）" />
            <el-option value="HOUSE_RND" label="自营研发金（HOUSE_RND）" />
            <el-option value="CORE_POOL" label="核心投资池（CORE_POOL）" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDlg=false">取消</el-button>
        <el-button type="warning" @click="saveBatch">应用到 {{ sel.size }} 个账户</el-button>
      </template>
    </el-dialog>

    <!-- 账户右键菜单（cex / kms_wallet 按 platformType 注入） -->
    <Teleport to="body">
      <div v-if="menu.open" class="acct-ctx-backdrop" @click="menu.open=false" @contextmenu.prevent="menu.open=false"></div>
      <div v-if="menu.open" class="acct-ctx" :style="{left:menu.x+'px',top:menu.y+'px'}" @click.stop>
        <div class="h">{{ mv(menu.node,'账户') || menu.node?.id }} · {{ menu.node?.venue }}</div>
        <template v-for="a in (menu.node ? actionsOf(menu.node) : [])" :key="a.key">
          <div v-if="a.dividerBefore" class="dv" />
          <div class="it" :class="{danger:a.danger}" @click="doAction(a, menu.node)"><el-icon class="mi"><component :is="a.icon" /></el-icon>{{ a.label }}</div>
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
    </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
// V5 MJvpp 托管与权限
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
// 从节点 metrics 按键取值(固定列渲染);容错多种键名
const mv = (node, key) => (node && node.metrics && node.metrics[key]) || ''

// 行内/菜单统一动作集:PC 内联扁平图标显示,移动端收进 ⋮ 菜单。编辑组+清除组用 dividerBefore 分隔。
function actionsOf(node) {
  if (!node) return []
  const isWallet = node.kind === 'wallet' || node.platformType === 'kms_wallet'
  const isSub = node.kind === 'sub' || typeOf(node.id) === 'sub'
  if (isWallet) return [   // HL 链上钱包:agent 私钥,无 API key/secret 流程
    { key: 'verify', icon: 'CircleCheck', label: '验证' },
    { key: 'refresh', icon: 'Refresh', label: '余额刷新' },
    { key: 'edit_registry', icon: 'EditPen', label: '编辑别名/邮箱', dividerBefore: true },
    { key: 'ip_proxy', icon: 'Position', label: 'IP 代理' },
    { key: 'purge', icon: 'Delete', label: '清除(改名/删除)', danger: true, confirm: true, dividerBefore: true }]
  const A = []
  if (!isSub) A.push({ key: 'create_sub', icon: 'Plus', label: '新建子账户' })
  A.push({ key: 'set_api', icon: 'Key', label: '设置 API…' })
  A.push({ key: 'toggle', icon: 'SwitchButton', label: '启用/禁用' })
  A.push({ key: 'verify', icon: 'CircleCheck', label: '验证' })
  A.push({ key: 'ip_whitelist', icon: 'Lock', label: 'IP 白名单' })
  A.push({ key: 'refresh', icon: 'Refresh', label: '余额刷新' })
  A.push({ key: 'edit_registry', icon: 'EditPen', label: '编辑别名/邮箱', dividerBefore: true })
  if (isSub) A.push({ key: 'set_master', icon: 'Connection', label: '主账户关联' })
  A.push({ key: 'set_mode', icon: 'Setting', label: '账户模式' })
  A.push({ key: 'ip_proxy', icon: 'Position', label: 'IP 代理' })
  A.push({ key: 'purge', icon: 'Delete', label: '清除(改名/删除)', danger: true, confirm: true, dividerBefore: true })
  return A
}

// 勾选 + 批量设置
const sel = reactive(new Set())
const allIds = computed(() => tree.value.flatMap(m => [m.id, ...(m.children || []).map(c => c.id)]))
const allSel = computed(() => allIds.value.length > 0 && allIds.value.every(id => sel.has(id)))
function toggleSel(id) { sel.has(id) ? sel.delete(id) : sel.add(id) }
function toggleAll() { allSel.value ? sel.clear() : allIds.value.forEach(id => sel.add(id)) }
const batchDlg = ref(false)
const batchForm = reactive({ field: 'account_mode', account_mode: 'classic', book: 'TEST' })
function openBatch() { if (sel.size) batchDlg.value = true }
async function saveBatch() {
  const keys = [...sel]
  const body = { account_keys: keys }
  if (batchForm.field === 'account_mode') body.account_mode = batchForm.account_mode
  else body.book = batchForm.book
  try { const r = await mixApi.accountsBatch(body)
    ElMessage.success(`已批量设置 ${r.affected} 个账户`); batchDlg.value = false; sel.clear(); loadRegistry(); load() }
  catch (e) { ElMessage.error(e?.detail || e?.error || '批量设置失败') }
}

function toggle(id) { open.has(id) ? open.delete(id) : open.add(id) }
function openMenu(e, node) {
  menu.open = true
  menu.x = Math.min(e.clientX, window.innerWidth - 210)
  menu.y = Math.min(e.clientY, window.innerHeight - 300)
  menu.node = node
}
async function doAction(it, node) {
  menu.open = false
  node = node || menu.node
  if (!node) return
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
const atab = ref('custody')
const custody = ref([])
const CUSTODY_LABEL = { SELF_CUSTODY_B_KMS: 'B机KMS托管(交易key,过渡)', CLIENT_OWNED_GUARD: '客户自有+Guard', THIRD_PARTY_MPC: '第三方MPC' }
const custodyLabel = m => CUSTODY_LABEL[m] || m || 'N/A'
async function loadCustody(){ try{ custody.value=(await mixApi.accountsCustody())?.rows||[] }catch(e){} }
onMounted(() => { load(); loadRegistry(); loadCustody() })
</script>

<style scoped lang="scss">
.mixacct { display: flex; flex-direction: column; gap: 10px; }
.bar { display: flex; align-items: center; gap: 10px;
  b { font-size: 14px; } .hint { font-size: 11px; color: var(--el-text-color-secondary); }
  .spacer { flex: 1; } .selinfo { font-size: 11px; color: #F0B90B; font-weight: 700; } }
.tbl { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 6px; display: flex; flex-direction: column; gap: 2px; }
.thead { display: flex; align-items: center; gap: 8px; padding: 2px 10px; font-size: 10px;
  color: var(--el-text-color-placeholder); font-weight: 700; }
.row { display: flex; align-items: center; gap: 8px; padding: 0 10px; border-radius: 6px; font-size: 12px; height: 34px;
  &.master { background: var(--el-fill-color); font-weight: 700; }
  &.sub { background: var(--el-fill-color-lighter); height: 30px; } }
/* 固定列(thead 与 row 同宽对齐) */
.c-cb { width: 22px; flex: none; display: flex; align-items: center; input { cursor: pointer; } }
.c-name { flex: 1; min-width: 170px; display: flex; align-items: center; gap: 6px; cursor: pointer; overflow: hidden;
  .nm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    &.sm { font-weight: 600; } &.off { opacity: .45; text-decoration: line-through; } } }
.c-venue { width: 82px; flex: none; color: var(--el-text-color-secondary); font-size: 11px; }
.c-book { width: 90px; flex: none; font-size: 10px; font-weight: 800;
  &.bk-CORE_POOL { color: #F0B90B; } &.bk-HOUSE_RND { color: #2DD4BF; } &.bk-TEST { color: var(--el-text-color-placeholder); } }
.c-cred { width: 92px; flex: none; font-size: 10.5px; color: var(--el-text-color-secondary); }
.c-mode { width: 66px; flex: none; font-size: 11px; }
.c-eq { width: 104px; flex: none; font-size: 12px; font-weight: 700; text-align: right; }
.c-sub { width: 70px; flex: none; font-size: 11px; color: var(--el-text-color-secondary); }
.c-act { flex: none; display: flex; align-items: center; gap: 1px; margin-left: auto; }
.caret { width: 12px; color: var(--el-text-color-placeholder); &.sub { visibility: hidden; } }
.kind { padding: 0 5px; border-radius: 4px; font-size: 10px; font-weight: 800; flex: none;
  &.master { background: rgba(240,185,11,.15); color: #F0B90B; }
  &.kms_wallet { background: rgba(45,212,191,.15); color: #2DD4BF; }
  &.sub { background: var(--el-fill-color-dark); color: var(--el-text-color-secondary); } }
.dot { width: 7px; height: 7px; border-radius: 50%; flex: none;
  &.ok { background: #0ECB81; } &.restricted { background: #F6465D; } &.healing { background: #F0B90B; } }
/* 白色扁平功能图标(hover 金;danger 红) */
.act { font-size: 15px; color: #C8CDD6; cursor: pointer; padding: 3px; border-radius: 4px; transition: color .12s, background .12s;
  &:hover { color: #F0B90B; background: rgba(240,185,11,.12); }
  &.danger:hover { color: #F6465D; background: rgba(246,70,93,.12); } }
.more { display: none; background: transparent; border: none; color: var(--el-text-color-secondary); cursor: pointer; padding: 3px; align-items: center; }
/* 移动端:内联图标收进 ⋮ 菜单;次要列隐藏 */
@media (max-width: 860px) {
  .c-act .act { display: none; }
  .more { display: inline-flex; }
  .c-cred, .c-sub, .thead .c-cred, .thead .c-sub { display: none; }
}
.cbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
  b { font-size: 13px; } .hint { font-size: 10.5px; color: var(--el-text-color-secondary); } }
.ok { color: #0ECB81; font-weight: 700; } .bad { color: #F6465D; } .deny { color: #FF8A3D; font-size: 10.5px; }
.fnote { font-size: 10px; color: var(--el-text-color-secondary); margin-top: 8px; line-height: 1.6; }
.m-NORMAL { color: #35b57c; } .m-WATCH { color: #F0B90B; } .m-NO_NEW_RISK { color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; } .m-FROZEN { color: #8B1E2D; }
</style>

<style lang="scss">
.acct-ctx { position: fixed; z-index: 9999; width: 196px; background: #1E232B; border: 1px solid #262B33; border-radius: 10px; padding: 5px;
  box-shadow: 0 8px 24px rgba(0,0,0,.6); font-size: 11px; color: #EAECEF;
  .h { padding: 5px 10px 4px; color: #5E6673; font-size: 9px; font-weight: 600; }
  .dv { height: 1px; background: #262B33; margin: 2px 0; }
  .it { padding: 6px 10px; border-radius: 6px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 8px;
    .mi { font-size: 14px; color: #9AA0AB; }
    &:hover { background: #20242C; } &:hover .mi { color: #F0B90B; }
    &.danger { color: #F6465D; } &.danger .mi { color: #F6465D; } } }
.cbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
  b { font-size: 13px; } .hint { font-size: 10.5px; color: var(--el-text-color-secondary); } }
.ok { color: #0ECB81; font-weight: 700; } .bad { color: #F6465D; } .deny { color: #FF8A3D; font-size: 10.5px; }
.fnote { font-size: 10px; color: var(--el-text-color-secondary); margin-top: 8px; line-height: 1.6; }
.m-NORMAL { color: #35b57c; } .m-WATCH { color: #F0B90B; } .m-NO_NEW_RISK { color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; } .m-FROZEN { color: #8B1E2D; }
</style>
