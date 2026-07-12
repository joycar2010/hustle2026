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
          <span class="kind" :class="m.platformType">{{ m.platformType === 'kms_wallet' ? '链上' : '主' }}</span>
          <span class="name">{{ m.id }}</span>
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
            <span class="name sm">↳ {{ c.id }}</span>
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
      <div v-if="menu.open" class="acct-ctx" :style="{left:menu.x+'px',top:menu.y+'px'}" @click.stop>
        <div class="h">{{ menu.node?.id }} · {{ menu.node?.venue }}</div>
        <template v-for="it in menuItems" :key="it.key">
          <div v-if="it.dividerBefore" class="dv" />
          <div class="it" :class="it.kind" @click="doAction(it)">{{ it.label }}</div>
        </template>
      </div>
    </Teleport>

    <!-- 新建账户：主 / 子 二选一（对齐设计确认项） -->
    <el-dialog v-model="createDlg" title="新建账户" width="420">
      <el-form label-width="90">
        <el-form-item label="账户类型">
          <el-radio-group v-model="createForm.kind">
            <el-radio-button value="master">主账户</el-radio-button>
            <el-radio-button value="sub">子账户</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="交易所">
          <el-select v-model="createForm.venue" style="width:200px">
            <el-option v-for="v in ['币安','OKX','Bybit','Gate','MEXC']" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createForm.kind==='sub'" label="挂载主账户">
          <el-select v-model="createForm.parentId" style="width:200px">
            <el-option v-for="m in tree.filter(t=>t.platformType==='cex')" :key="m.id" :label="m.id" :value="m.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg=false">取消</el-button>
        <el-button type="warning" @click="createAccount">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ACCOUNT_MENUS } from '../../components/PositionTable/strategyColumns'
import { mixApi } from '../../api/mix'

const tree = ref([])
const open = reactive(new Set())
const menu = reactive({ open: false, x: 0, y: 0, node: null })
const createDlg = ref(false)
const createForm = reactive({ kind: 'sub', venue: '币安', parentId: '' })

const menuItems = computed(() => menu.node ? ACCOUNT_MENUS[menu.node.platformType] || [] : [])

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
    if (it.key === 'create_sub' || it.key === 'create_wallet') { createDlg.value = true; return }
    if (it.kind === 'link') { ElMessageBox.alert(`打开「${it.label}」配置弹窗（M4 接线）`, node.id); return }
    if (it.confirm) await ElMessageBox.confirm(`确认对 ${node.id} 执行「${it.label}」？`, '危险操作', { type: 'warning' })
    if (it.key === 'transfer') {
      const r = await mixApi.kmsTransfer({ from: node.id, amount: 1000 })
      ElMessage.warning(`转账已发起 → ${r.state}（发起人 ≠ 审批人，等待审批）`)
      return load()
    }
    const r = await mixApi.accountAction(node.id, it.key)
    ElMessage.success(`已受理（202）：${it.label}`)
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.error || '失败') }
}
async function approve(c) {
  await ElMessageBox.confirm(`审批 ${c.id} 的待审批转账？（审批人身份校验由后端强制）`, 'KMS 审批', { type: 'warning' })
  const r = await mixApi.kmsApprove(c.id)
  ElMessage.success(`已执行：${r.state} · 审计 ${r.auditId}`)
}
async function createAccount() {
  try {
    await mixApi.accountCreate({ ...createForm })
    ElMessage.success(`已创建${createForm.kind === 'master' ? '主账户' : '子账户'}（201）`)
    createDlg.value = false; load()
  } catch (e) { ElMessage.error(e?.error || '创建失败') }
}
async function load() {
  tree.value = await mixApi.accounts()
  tree.value.forEach(m => open.add(m.id))   // 默认全展
}
onMounted(load)
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
.name { min-width: 150px; &.sm { font-weight: 600; } }
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
