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
        <el-table-column label="读权限" width="70"><template #default="{row}"><span :class="row.probe_read?'ok':'bad'"><FIcon :name="row.probe_read?'check':'x'" :size="11"/></span></template></el-table-column>
        <el-table-column label="交易权限" width="80"><template #default="{row}"><span :class="row.probe_trade?'ok':'bad'"><FIcon :name="row.probe_trade?'check':'x'" :size="11"/></span></template></el-table-column>
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
        <span class="c-bal">资金</span>
        <span class="c-bal">现货</span>
        <span class="c-bal">合约</span>
        <span class="c-bal">理财</span>
        <span class="c-bal">杠杆可用</span>
        <span class="c-bal">借入</span>
        <span class="c-risk">风险值</span>
        <span class="c-act">操作</span>
      </div>
      <template v-for="m in tree" :key="m.id">
        <!-- 主账号 / 钱包组 行 -->
        <div class="row master" @contextmenu.prevent="openMenu($event, m)" v-longpress="(e)=>openMenu(e, m)">
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
          <span v-for="bk in BAL_KEYS" :key="bk" class="c-bal">{{ balT(m, bk) }}</span>
          <span class="c-risk" :class="riskCls(m)">{{ balT(m, 'risk') }}</span>
          <!-- 行内七动作(带 ICON 扁平按钮);其余全在「编辑」弹框(复用新建账户) -->
          <span class="c-act">
            <button v-if="m.kind==='master'&&m.platformType!=='kms_wallet'" class="ab sec" @click.stop="doAction({key:'create_sub',label:'新建子账户'}, m)"><el-icon><Plus/></el-icon>子账户</button>
            <button class="ab sec" @click.stop="doAction({key:'toggle',label:'启用/禁用'}, m)"><el-icon><SwitchButton/></el-icon>启停</button>
            <button class="ab" @click.stop="doAction({key:'verify',label:'验证'}, m)"><el-icon><CircleCheck/></el-icon>探针</button>
            <button class="ab sec" @click.stop="doAction({key:'refresh',label:'余额刷新'}, m)"><el-icon><Refresh/></el-icon>刷新</button>
            <button class="ab gold" @click.stop="openEdit(m)"><el-icon><EditPen/></el-icon>编辑</button>
            <button class="ab red sec" @click.stop="doAction({key:'purge',label:'清除',danger:true,confirm:true}, m)"><el-icon><Delete/></el-icon>清除</button>
            <button class="ab red" @click.stop="freezeVenueRow(m)"><el-icon><Lock/></el-icon>冻结</button>
            <button class="ab onlysm" @click.stop="openMenu($event, m)"><el-icon><MoreFilled/></el-icon></button>
          </span>
        </div>
        <!-- 子账户 / 钱包地址 行 -->
        <template v-if="open.has(m.id)">
          <div v-for="c in m.children" :key="c.id" class="row sub" @contextmenu.prevent="openMenu($event, c, m)" v-longpress="(e)=>openMenu(e, c, m)">
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
            <span v-for="bk in BAL_KEYS" :key="bk" class="c-bal">{{ balT(c, bk) }}</span>
            <span class="c-risk" :class="riskCls(c)">{{ balT(c, 'risk') }}</span>
            <span class="c-act">
              <button class="ab sec" @click.stop="doAction({key:'toggle',label:'启用/禁用'}, c)"><el-icon><SwitchButton/></el-icon>启停</button>
              <button class="ab" @click.stop="doAction({key:'verify',label:'验证'}, c)"><el-icon><CircleCheck/></el-icon>探针</button>
              <button class="ab sec" @click.stop="doAction({key:'refresh',label:'余额刷新'}, c)"><el-icon><Refresh/></el-icon>刷新</button>
              <button class="ab gold" @click.stop="openEdit(c, m)"><el-icon><EditPen/></el-icon>编辑</button>
              <button class="ab red sec" @click.stop="doAction({key:'purge',label:'清除',danger:true,confirm:true}, c)"><el-icon><Delete/></el-icon>清除</button>
              <button class="ab red" @click.stop="freezeVenueRow(c)"><el-icon><Lock/></el-icon>冻结</button>
              <button class="ab onlysm" @click.stop="openMenu($event, c, m)"><el-icon><MoreFilled/></el-icon></button>
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
    <el-dialog v-model="modeDlg" :title="`账户模式 · ${modeForm.account_key}`" width="720" @open="loadElig">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
        title="账户模式=交易所账户的物理形态(四种,封闭集);哪个策略能跑哪种形态=下方资格矩阵(单一权威,可自定义)。" />
      <el-form label-width="90">
        <el-form-item label="账户模式">
          <el-select v-model="modeForm.account_mode" style="width:320px">
            <el-option value="classic" label="经典（钱包分离·C3 借币点差）" />
            <el-option value="portfolio_margin" label="统一账户（组合保证金·借贷利率套利）" />
            <el-option value="cross_margin" label="全仓杠杆" />
            <el-option value="isolated" label="逐仓" />
          </el-select>
        </el-form-item>
      </el-form>
      <!-- 原设计#5:策略×账户模式资格矩阵(strategy_account_eligibility 单一权威)——点击格子循环切换 首选→允许→禁止 -->
      <div class="eligwrap" v-loading="eligLoading">
        <div class="elighd"><b>策略 × 账户模式 资格矩阵</b>
          <span class="dimtxt">点击格子切换:首选→允许→禁止;当前列高亮=本弹框选中的模式;opener/executor 按此门控(消费端接线中)</span></div>
        <table class="eligtbl" v-if="elig.matrix">
          <thead><tr><th>策略</th>
            <th v-for="m in elig.account_modes" :key="m.key" :class="{cur:m.key===modeForm.account_mode}">{{ m.name }}</th></tr></thead>
          <tbody>
            <tr v-for="s in elig.strategies" :key="s.code">
              <td class="sname">{{ s.code }} · {{ s.name }}</td>
              <td v-for="m in elig.account_modes" :key="m.key" class="cell"
                  :class="[cellOf(s.code,m.key)?.eligibility, {cur:m.key===modeForm.account_mode}]"
                  :title="cellOf(s.code,m.key)?.reason || (cellOf(s.code,m.key)?.configured?'':'未配置=默认允许')"
                  @click="cycleElig(s.code, m.key)">
                {{ ELIG_CN[cellOf(s.code,m.key)?.eligibility] || '允许' }}<i v-if="!cellOf(s.code,m.key)?.configured">*</i>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="dimtxt" style="margin-top:6px">* =未显式配置(默认允许) ｜ 改动即写权威表(strategy_account_eligibility)并留操作审计</div>
      </div>
      <template #footer>
        <el-button @click="modeDlg=false">取消</el-button>
        <el-button type="warning" @click="saveMode">保存账户模式</el-button>
      </template>
    </el-dialog>

    <!-- 新建账户：主 / 子 + 别名/邮箱 + 可选 API Key/密码（一步录入，密钥仍浏览器端加密） -->
    <el-dialog v-model="createDlg" :title="editMode ? `编辑账户 · ${createForm.account_key}` : '新建账户'"
               width="520" @closed="editMode=false">
      <el-form label-width="96">
        <el-form-item label="账户类型">
          <el-radio-group v-model="createForm.account_type" :disabled="editMode">
            <el-radio-button value="master">主账户</el-radio-button>
            <el-radio-button value="sub">子账户</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="账户标识"><el-input v-model="createForm.account_key" :disabled="editMode" placeholder="唯一键，如 joycar003 / binance-master" /></el-form-item>
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
          <el-select v-model="createForm.account_mode" style="width:280px">
            <el-option value="classic" label="经典（钱包分离·可跑 C3 借币点差）" />
            <el-option value="portfolio_margin" label="统一账户（组合保证金·跑借贷利率套利）" />
            <el-option value="cross_margin" label="全仓杠杆" />
            <el-option value="isolated" label="逐仓" />
          </el-select>
          <el-link type="warning" style="margin-left:8px;font-size:11px" @click="showElig=!showElig">
            资格矩阵{{ showElig ? '▲' : '▼' }}</el-link>
        </el-form-item>
        <!-- 策略×账户模式资格矩阵(单一权威,新建/编辑同一份,点击切换 首选→允许→禁止) -->
        <div v-if="showElig" class="eligwrap" v-loading="eligLoading" style="margin:0 0 12px">
          <table class="eligtbl" v-if="elig.matrix">
            <thead><tr><th>策略</th>
              <th v-for="mm in elig.account_modes" :key="mm.key" :class="{cur:mm.key===createForm.account_mode}">{{ mm.name }}</th></tr></thead>
            <tbody>
              <tr v-for="s in elig.strategies" :key="s.code">
                <td class="sname">{{ s.code }} · {{ s.name }}</td>
                <td v-for="mm in elig.account_modes" :key="mm.key" class="cell"
                    :class="[cellOf(s.code,mm.key)?.eligibility, {cur:mm.key===createForm.account_mode}]"
                    @click="cycleElig(s.code, mm.key)">
                  {{ ELIG_CN[cellOf(s.code,mm.key)?.eligibility] || '允许' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <template v-if="editMode">
          <el-form-item v-if="createForm.account_type==='sub'" label="主账户关联">
            <el-select v-model="createForm.parent_key" style="width:280px" filterable allow-create>
              <el-option v-for="mo in masterForm.options" :key="mo.account_key||mo" :label="mo.account_key||mo" :value="mo.account_key||mo" />
            </el-select>
          </el-form-item>
          <el-form-item label="IP 代理">
            <el-input v-model="createForm.proxy_url" placeholder="http://user:pass@host:port（留空=直连）" />
          </el-form-item>
          <el-form-item label="IP 白名单">
            <el-button size="small" @click="doAction({key:'ip_whitelist',label:'IP 白名单'}, {id:createForm.account_key, venue:createForm.venue})">
              <el-icon><View/></el-icon>&nbsp;查看三机出口 IP 指引</el-button>
          </el-form-item>
        </template>
        <el-divider content-position="left" style="font-size:12px">
          API 凭证（{{ editMode ? '留空=不改;填写=浏览器端加密重录' : '选填，浏览器端加密' }}）</el-divider>
        <el-form-item label="API Key"><el-input v-model="createForm.apiKey" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="API Secret"><el-input v-model="createForm.apiSecret" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="Passphrase"><el-input v-model="createForm.passphrase" type="password" show-password placeholder="OKX/Bitget 需要" autocomplete="new-password" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg=false">取消</el-button>
        <el-button type="warning" :loading="apiSaving" @click="createAccount">{{ editMode ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
    </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
// V5 MJvpp 托管与权限
import { ElMessage, ElMessageBox } from 'element-plus'
import { ACCOUNT_MENUS } from '../../components/PositionTable/strategyColumns'
import { mixApi } from '../../api/mix'
import { sealCredential, maskKey } from '../../api/credCrypto'

const tree = ref([])
const open = reactive(new Set())
const menu = reactive({ open: false, x: 0, y: 0, node: null })
const createDlg = ref(false)
const editMode = ref(false)   // 复用同一弹框:新建/编辑双态
const createForm = reactive({ account_type: 'sub', account_key: '', venue: 'binance', parent_key: '', alias: '', email: '', machine: 'B', book: 'TEST', account_mode: 'classic', apiKey: '', apiSecret: '', passphrase: '', proxy_url: '' })
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
// 资格矩阵(原设计#5:策略×账户模式→PREFERRED/ALLOWED/FORBIDDEN 单一权威可配)
const elig = ref({}); const eligLoading = ref(false)
const showElig = ref(false)
watch(showElig, v => { if (v && !elig.value.matrix) loadElig() })
const ELIG_CN = { PREFERRED: '首选', ALLOWED: '允许', FORBIDDEN: '禁止' }
const _CYCLE = { PREFERRED: 'ALLOWED', ALLOWED: 'FORBIDDEN', FORBIDDEN: 'PREFERRED' }
function cellOf(s, m) { return (elig.value.matrix || []).find(x => x.strategy === s && x.account_mode === m) }
async function loadElig() {
  eligLoading.value = true
  try { elig.value = await mixApi.eligibility() } catch (e) { elig.value = {} }
  eligLoading.value = false
}
async function cycleElig(strategy, account_mode) {
  const cur = cellOf(strategy, account_mode)?.eligibility || 'ALLOWED'
  const next = _CYCLE[cur]
  try {
    await mixApi.eligibilityPut({ strategy, account_mode, eligibility: next,
      reason: `账户页矩阵编辑(${cur}→${next})` })
    ElMessage.success(`${strategy} × ${account_mode} → ${ELIG_CN[next]}`)
    loadElig()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
}
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
const credLabel = c => ({ active: `${c.key_mask||'已配'}`, pending: '下发中', error: '异常', revoked: '已吊销' }[c.state] || '')
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
// 余额七维(后端 bal 契约:null=未接入显—,绝不用0冒充;资金/现货/理财待 account-snapshot 扩采)
const BAL_KEYS = ['funding', 'spot', 'futures', 'earn', 'margin_free', 'borrowed']
function balT(node, k) {
  const v = node?.bal?.[k]
  if (v == null) return '—'
  if (k === 'risk') return v >= 100 ? '安全' : Number(v).toFixed(2)   // 币安999=无负债哨兵值
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })
}
function riskCls(node) {
  const v = node?.bal?.risk
  if (v == null) return ''
  return v < 1.5 ? 'riskbad' : (v < 2 ? 'riskwarn' : 'riskok')
}
// 编辑账户(复用新建弹框):设API/IP白名单/别名/关联主/代理/模式 全部收编于此
function openEdit(node, parent) {
  const cur = reg.value[node.id] || {}
  const isSub = node.kind === 'sub' || node.kind === 'wallet' || !!parent
  Object.assign(createForm, {
    account_type: isSub ? 'sub' : 'master', account_key: node.id,
    parent_key: cur.parent_key || parent?.id || '',
    venue: node.venue || 'binance',
    alias: cur.alias || '', email: cur.email || '',
    book: cur.book || 'TEST', account_mode: cur.account_mode || 'classic',
    apiKey: '', apiSecret: '', passphrase: '',
    proxy_url: cur.credential?.proxy_url || '',
  })
  editMode.value = true
  createDlg.value = true
  mixApi.accountMasters(node.venue || '').then(r => { masterForm.options = r.masters || [] }).catch(() => {})
}
// 行内「冻结新增」(MJvpp 规约四动作之一):对该账户所属 venue 追加 NO_NEW_RISK(减险,经风险权威通道)
async function freezeVenueRow(node) {
  const v = node?.venue
  if (!v) { ElMessage.warning('该行无所属平台'); return }
  try {
    await ElMessageBox.confirm(`对 ${v} 追加「暂停开新仓」(减险·立即;已有仓位减仓/还币不受影响)?`, '冻结新增', { type: 'warning' })
    await mixApi.riskOverrideAdd({ scope_type: 'VENUE', scope_key: v, mode: 'NO_NEW_RISK', reason: `账户页冻结(${node.id||''})` })
    ElMessage.success(`已追加 ${v} 暂停开新仓`)
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '失败') }
}
function openMenu(e, node) {
  // 触屏长按等价右键:touch 事件坐标在 touches/changedTouches,鼠标在 e 自身
  const p = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e
  menu.open = true
  menu.x = Math.min(p.clientX || 40, window.innerWidth - 210)
  menu.y = Math.min(p.clientY || 120, window.innerHeight - 300)
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
// 编辑保存:别名/邮箱/账本/模式/主账户关联/代理/API(留空不改) 一次提交,分别写各自权威
async function saveEdit() {
  apiSaving.value = true
  try {
    await mixApi.registryPut({ account_key: createForm.account_key, alias: createForm.alias,
      email: createForm.email, note: reg.value[createForm.account_key]?.note || '' })
    const cur = reg.value[createForm.account_key] || {}
    if (createForm.account_mode !== (cur.account_mode || 'classic'))
      await mixApi.setAccountMode(createForm.account_key, createForm.account_mode)
    if (createForm.account_type === 'sub' && createForm.parent_key &&
        createForm.parent_key !== (cur.parent_key || ''))
      await mixApi.setAccountMaster(createForm.account_key, createForm.parent_key)
    if (createForm.apiKey && createForm.apiSecret) {
      const enc = await encryptCred(createForm.apiKey, createForm.apiSecret, createForm.passphrase)
      await mixApi.credPut({ account_key: createForm.account_key, venue: createForm.venue,
        proxy_url: createForm.proxy_url, ...enc })
      ElMessage.success('API 已浏览器端加密提交,B 机 agent 60s 内生效')
    } else if (createForm.proxy_url !== (cur.credential?.proxy_url || '')) {
      try { await mixApi.credProxy(createForm.account_key, { proxy_url: createForm.proxy_url }) }
      catch (e) { ElMessage.warning('代理未保存(该账户尚未录入 API 凭证)') }
    }
    ElMessage.success('账户设置已保存')
    createDlg.value = false; editMode.value = false; loadRegistry(); load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') } finally { apiSaving.value = false }
}
async function createAccount() {
  if (editMode.value) return saveEdit()
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
.thead { display: flex; align-items: center; gap: 5px; padding: 2px 8px; font-size: 10px;
  color: var(--el-text-color-placeholder); font-weight: 700; }
.row { display: flex; align-items: center; gap: 5px; padding: 0 8px; border-radius: 6px; font-size: 12px; height: 34px;
  &.master { background: var(--el-fill-color); font-weight: 700; }
  &.sub { background: var(--el-fill-color-lighter); height: 30px; } }
/* 固定列(thead 与 row 同宽对齐) */
/* 列宽策略:除操作列外全部等比 flex(flex-basis:0,同比例)——每行宽度公式一致,跨行天然对齐;
   窗口变宽各列按比例伸展(自适应),不再把富余全灌给名称列。操作列定宽=全量按钮最大集合。 */
.c-cb { width: 22px; flex: none; display: flex; align-items: center; input { cursor: pointer; } }
.c-name { flex: 22 1 0; min-width: 150px; display: flex; align-items: center; gap: 5px; cursor: pointer; overflow: hidden;
  .nm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    &.sm { font-weight: 600; } &.off { opacity: .45; text-decoration: line-through; } } }
.c-venue { flex: 8 1 0; min-width: 58px; color: var(--el-text-color-secondary); font-size: 11px; overflow: hidden; }
.c-book { flex: 9 1 0; min-width: 66px; font-size: 10px; font-weight: 800; overflow: hidden;
  &.bk-CORE_POOL { color: #F0B90B; } &.bk-HOUSE_RND { color: #2DD4BF; } &.bk-TEST { color: var(--el-text-color-placeholder); } }
.c-cred { flex: 8 1 0; min-width: 56px; font-size: 10.5px; color: var(--el-text-color-secondary); overflow: hidden; }
.c-mode { flex: 6 1 0; min-width: 42px; font-size: 11px; overflow: hidden; }
/* 余额七维(资金/现货/合约/理财/杠杆可用/借入)+风险值:右对齐等宽数字;—=未接入 */
.c-bal { flex: 8 1 0; min-width: 54px; font-size: 11.5px; font-weight: 700; text-align: right;
  white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--mix-t1, #EAECEF); overflow: hidden; }
.thead .c-bal { font-weight: 700; color: var(--el-text-color-placeholder); font-size: 10px; }
.c-risk { flex: 6 1 0; min-width: 42px; font-size: 11.5px; font-weight: 700; text-align: right;
  white-space: nowrap; font-variant-numeric: tabular-nums; overflow: hidden;
  &.riskok { color: #0ECB81; } &.riskwarn { color: #F0B90B; } &.riskbad { color: #F6465D; } }
.thead .c-risk { color: var(--el-text-color-placeholder); font-size: 10px; }
/* 操作列定宽=紧凑按钮最大集合(主行7钮);总最小宽须<内容区,禁出横向滚动条 */
.c-act { width: 398px; flex: none; display: flex; align-items: center; gap: 3px; justify-content: flex-end; flex-wrap: nowrap; }
/* 扁平功能按钮:ICON+文字,无 emoji;中性=灰底白字/主动作=金/危险=红,悬停描边呼应主色 */
.ab { display: inline-flex; align-items: center; gap: 2px; font-size: 10px; font-weight: 700;
  padding: 3px 6px; border-radius: 4px; cursor: pointer;
  background: var(--mix-card2, #20242C); color: var(--mix-t1, #EAECEF);
  border: 1px solid var(--mix-border, #2B3139); white-space: nowrap; transition: border-color .12s;
  .el-icon { font-size: 11px; }
  &:hover { border-color: #F0B90B; color: #F0B90B; }
  &.gold { background: rgba(240,185,11,.12); border-color: rgba(240,185,11,.4); color: #F0B90B;
    &:hover { border-color: #F0B90B; } }
  &.red { background: rgba(246,70,93,.08); border-color: rgba(246,70,93,.4); color: #F6465D;
    &:hover { border-color: #F6465D; } } }
.ab.onlysm { display: none; }
/* 资格矩阵(账户模式弹框) */
.eligwrap { margin-top: 4px; }
.elighd { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; b { font-size: 12.5px; } }
.eligtbl { width: 100%; border-collapse: collapse; font-size: 11px;
  th, td { border: 1px solid var(--mix-border, #2B3139); padding: 5px 8px; text-align: center; }
  th { color: var(--mix-t3, #5E6673); font-size: 10px; background: var(--mix-panel, #12151A);
    &.cur { color: #F0B90B; } }
  .sname { text-align: left; color: var(--mix-t2, #848E9C); font-weight: 700; white-space: nowrap; }
  .cell { cursor: pointer; font-weight: 700; transition: background .12s;
    i { font-style: normal; opacity: .5; font-weight: 400; }
    &:hover { background: rgba(240,185,11,.08); }
    &.cur { background: rgba(240,185,11,.05); }
    &.PREFERRED { color: #0ECB81; }
    &.ALLOWED { color: var(--mix-t2, #848E9C); font-weight: 400; }
    &.FORBIDDEN { color: #F6465D; } } }
/* 中屏:次要按钮收进「更多」,操作列收窄;余额列只留 合约/杠杆可用/借入/风险(断点提前防溢出) */
@media (max-width: 1700px) {
  .c-act { width: 226px; }
  .ab.sec { display: none; }
  .ab.onlysm { display: inline-flex; }
  .c-bal:nth-of-type(1), .c-bal:nth-of-type(2), .c-bal:nth-of-type(4),
  .thead .c-bal:nth-of-type(1), .thead .c-bal:nth-of-type(2), .thead .c-bal:nth-of-type(4) { display: none; }
}
@media (max-width: 1280px) {
  .c-cred, .thead .c-cred, .c-mode, .thead .c-mode { display: none; }
}
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
/* 移动端:只留「更多」菜单;次要列隐藏 */
@media (max-width: 860px) {
  .c-act { width: 52px; }
  .c-act .ab { display: none; }
  .c-act .ab.onlysm { display: inline-flex; }
  .c-cred, .c-bal, .thead .c-cred, .thead .c-bal { display: none; }
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
