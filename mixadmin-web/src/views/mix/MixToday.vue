<template>
  <!-- V6.2 今日工作(帧 D2GIj):中控台+三墙+工作台的合体——唯一日常入口。
       一份快照/七段流程条/三视图(三栏|页签|墙聚焦)/行点击→右抽屉六段,全程不跳页。 -->
  <div class="today">
    <V6StatusBar :snap="snap" :stale="stale" :can-open="canOpen" :ago="ago"/>
    <!-- V6.2 R2 自动运行状态条(§4.1 紧凑事实带):所有真钱自动回路首屏可见 -->
    <AutomationStrip/>
    <!-- V6.2 R3 每日开班简报(§4.3):当天首次进入自动一次;无待办不庆祝 -->
    <DailyBriefing :snap="snap" :can-open="canOpen" @open-item="openItem"/>
    <div class="body">
      <div class="railrow">
        <ProcessRail class="railfill" :steps="railSteps" @pick="pickQueue"/>
        <!-- 视图切换:轻列表(默认)|深表格(/mix/work?view=table,工作台主表能力并入统一外壳) -->
        <span class="vswitch">
          <a :class="{on:viewMode==='list'}" @click="viewMode='list'">列表</a>
          <a :class="{on:viewMode==='table'}" @click="viewMode='table'">表格</a>
        </span>
        <!-- 手动计划泛产品化:全产品统一走 研判先行→DRY_RUN 链路 -->
        <button class="planbtn" @click="npOpen=true">＋ 手动计划</button>
        <!-- §9.2:训练通过后菜单收敛,入口迁到这里(仍可主动进入演练) -->
        <button v-if="trainOk" class="trainbtn" @click="$router.push('/mix/training')"><FIcon name="cap" :size="12"/> 训练/演练</button>
        <!-- V6.2 R3+ 浮动引导栏内联版(从右下浮动球移到按钮行右侧,避免与AI客服重叠) -->
        <GuidanceRail class="railinline" @open-item="openItemById" @retour="tourOpen=true"/>
      </div>
      <!-- LAB 提醒落点(V6.2:outbox 新 artifact→提醒;此前只在退役中控台,唯一日常入口反而看不见) -->
      <div class="labbar" v-if="labNote"><FIcon name="flask" :size="12"/> {{ labNote }} →
        <a @click="$router.push({path:'/mix/lab',query:{focus:'outbox'}})">实验室·结果与判决</a>
        <span class="labx" @click="dismissLab">✕</span></div>
      <!-- 深表格视图:与轻列表同一快照同一抽屉,队列过滤共用流程条 -->
      <WorkTable v-if="viewMode==='table'" :items="tableItems" :row-state="rowState" :sel-id="selId"
                 :preset="wtPreset" :product="wtProduct" :expanded="expRows"
                 @open="openItem" @run="runAct" @toggle="toggleExp" @open-asset="openAsset360"
                 @update:preset="setWtPreset" @update:product="setWtProduct"/>
      <!-- 窄屏页签(≥1360 自动隐藏,三栏并排) -->
      <div v-if="viewMode==='list'" class="vtabs">
        <span v-for="v in ['机会','持仓','风险']" :key="v" class="vt" :class="{on:vtab===v}" @click="vtab=v">{{ v }}</span>
        <span class="wallbtns">
          <a v-for="w in WALLS" :key="w.k" @click="openWall(w.k)">{{ w.t }}</a>
        </span>
      </div>
      <div v-if="viewMode==='list'" class="cols" :data-vtab="vtab" :data-focus="focusCol">
        <!-- 栏1·机会 -->
        <div class="col c-opp">
          <div class="chd"><b>机会</b><a class="fllim" @click="editFlLimit" :title="'快线额度:单笔≤'+flLimit+'U 直接下单;点击修改(逐操作员)'"><FIcon name="zap" :size="10"/> {{ flLimit }}U</a><i>候选 {{ snap?.counts?.candidates_raw ?? '—' }} → 过闸 {{ opps.length }}</i></div>
          <div class="list" ref="oppList">
            <!-- 批A §6A.5B 机会紧凑行三行式:身份/路线容量/时间新鲜度 -->
            <div v-for="w in opps" :key="w.work_item_id" class="row tall opp3" :class="{sel:selId===w.work_item_id, submitting:rowState[w.work_item_id]==='loading'}"
                 @click="openItem(w)">
              <div class="r1">
                <b class="sym" @click.stop="openAsset360(w.symbol)">{{ w.symbol }}</b>
                <span class="prod" :class="pxCls(w.strategy_code)">· {{ w.strategy_code }}</span>
                <span v-if="w.research_status && w.research_status!=='NOT_REQUIRED'" class="rs" :class="w.research_status">
                  研判{{ {PENDING:'待做',COMPLETED:'完成',EXPIRED:'过期'}[w.research_status]||'' }}</span>
                <span class="fill"></span>
                <button v-if="w.source==='opener' && String(w.route||'').includes('↔')" class="flbtn"
                        :disabled="flBusy===w.work_item_id" @click.stop="fastOpen(w)"
                        :title="`快线直通:额度内(${flLimit}U)免冷却免逐笔认证,四道机器闸毫秒级自动过`">
                  <FIcon name="zap" :size="11"/> {{ flBusy===w.work_item_id ? '执行中…' : '直接开仓' }}</button>
                <PrimaryAction v-if="primaryOf(w)" :a="primaryOf(w)" sz="sm"
                               :still-allowed="w.still_allowed" :blocking-reason="w.blocking_reason"
                               :state="rowState[w.work_item_id]||''" @run="(a)=>runAct(w,a)"/>
              </div>
              <div class="band">
                <span class="bc"><i>路线</i><b><template v-for="(rv,ri) in String(w.route||'—').split('↔')" :key="ri"><i v-if="ri" class="rsep">↔</i><span :class="'vx-'+rv">{{ rv }}</span></template></b></span>
                <span class="bc"><i>目标</i><b class="amtx">{{ w.capital_reserved!=null ? fmtU(w.capital_reserved)+' U' : '—' }}</b></span>
                <span class="bc"><i>净期望</i><b class="ev" :class="(w.expected_net_return||0)>=0?'up':'dn'">{{ w.expected_net_return!=null ? evT(w) : '待计算' }}</b></span>
              </div>
              <div class="band dim">
                <span class="bc"><i>下一结算</i><b>{{ (w.next_deadline||'—').slice(5,16) || '—' }}</b></span>
                <span class="bc"><i>风险</i><b>{{ w.risk_status?.level==='NORMAL' ? '正常' : (w.risk_status?.level||'—') }}</b></span>
              </div>
            </div>
            <EmptyState v-if="!opps.length" kind="none" title="暂无过闸候选" hint="顾问与 LAB 持续扫描中"/>
          </div>
        </div>
        <!-- 栏2·持仓 -->
        <div class="col c-pos">
          <div class="chd"><b>持仓 · 一行=一个经济组合</b><i>{{ queueNote }}</i></div>
          <div class="list">
            <!-- 批A §6A.5B 持仓紧凑行=四数据带(身份/仓位/经济/风险时间)+按需展开账户腿;
                 数据=服务端 legagg 聚合(group_econ 与点差保护同源),缺数显'—'绝不冒充0 -->
            <div v-for="w in posShown" :key="w.work_item_id" class="row tall pos4" :class="{sel:selId===w.work_item_id, bad:w.workflow_stage==='RECONCILING'}"
                 @click="openItem(w)">
              <div class="r1">
                <span v-if="w.account_legs?.length" class="expbtn" :class="{on:!!expRows[w.work_item_id]}"
                      @click.stop="toggleExp(w.work_item_id)">{{ expRows[w.work_item_id] ? '▾' : '▸' }}</span>
                <b class="sym" @click.stop="openAsset360(w.symbol)">{{ w.symbol }}</b>
                <span class="prod" :class="pxCls(w.strategy_code)">· {{ w.strategy_code }}</span>
                <!-- P2 修复:坑位行显示主账户/对冲账户 -->
                <span v-if="accountsOf(w)" class="accts">{{ accountsOf(w) }}</span>
                <span class="st" :class="stCls(w)">{{ w.stage_detail || w.workflow_stage }}</span>
                <!-- §6.3 点差保护=一等状态,不藏详情;shadow 评估,退出决策仍人工 -->
                <span v-if="w.risk_protection_state && w.risk_protection_state!=='NORMAL'"
                      class="prot" :class="w.risk_protection_state"
                      :title="'点差保护(shadow) · 预算余 '+(w.hard_loss_budget_remaining??'—')+'U · 回本 '+(w.recovery_windows??'—')+'窗'">
                  <FIcon name="shield" :size="10"/> {{ PROT_CN[w.risk_protection_state]||w.risk_protection_state }}</span>
                <span class="fill"></span>
                <span class="ddl">{{ w.next_deadline || '' }}</span>
                <button v-if="canFastClose(w)" class="flcbtn" :disabled="flcBusy===w.work_item_id"
                        @click.stop="fastClose(w)" title="快线直接平仓:两腿reduce-only真实平仓(减险,免额度/深度闸)">
                  <FIcon name="zap" :size="11"/> {{ flcBusy===w.work_item_id ? '平仓中…' : '直接平仓' }}</button>
                <PrimaryAction v-if="primaryOf(w)" :a="primaryOf(w)" sz="sm"
                               :still-allowed="w.still_allowed" :blocking-reason="w.blocking_reason"
                               :state="rowState[w.work_item_id]||''" @run="(a)=>runAct(w,a)"/>
              </div>
              <div class="band">
                <span class="bc"><i>规模</i><b class="amtx">{{ w.capital_reserved!=null ? fmtU(w.capital_reserved)+' U' : '—' }}</b></span>
                <span class="bc"><i>净Δ</i><b :class="cls0(ge(w).net_delta)">{{ ge(w).net_delta!=null ? fmtU(ge(w).net_delta)+' U' : '—' }}</b></span>
                <span class="bc"><i>费差/日</i><b :class="(ge(w).gap_now_pct||0)>0?'up':((ge(w).gap_now_pct||0)<0?'dn':'')">{{ ge(w).gap_now_pct!=null ? fmt2(ge(w).gap_now_pct)+'%' : '—' }}</b></span>
                <span class="bc"><i>退出盈亏</i><b :class="cls0(ge(w).closeout_pnl_net)">{{ ge(w).closeout_pnl_net!=null ? fmt2(ge(w).closeout_pnl_net)+' U' : '—' }}</b></span>
                <span class="bc"><i>已确认</i><b :class="cls0(w.confirmed_pnl)">{{ w.confirmed_pnl!=null ? fmt2(w.confirmed_pnl)+' U' : '—' }}</b></span>
              </div>
              <div class="band dim">
                <span class="bc"><i>预算余</i><b class="amtx">{{ ge(w).budget_remaining!=null ? fmt2(ge(w).budget_remaining)+' U' : '—' }}</b></span>
                <span class="bc"><i>最差强平</i><b :class="liqCls(ge(w).margin_min_dist_liq_pct)">{{ ge(w).margin_min_dist_liq_pct!=null ? fmtU(ge(w).margin_min_dist_liq_pct)+'%('+(ge(w).margin_worst_venue||'?')+')' : '—' }}</b></span>
                <span class="bc grow"><i></i><b class="wh">{{ w.what_happened }}</b></span>
              </div>
              <!-- 展开=账户腿明细(§6A.5B:不跳页;venue符号/方向/数量/标记/浮盈/费率/强平/ADL) -->
              <div v-if="expRows[w.work_item_id] && w.account_legs?.length" class="legs" @click.stop>
                <div class="leghd"><span>账户/腿</span><span>方向</span><span class="num">数量</span><span class="num">持仓U</span><span class="num">标记价</span><span class="num">浮盈U</span><span class="num">费率%/d</span><span class="num">强平距%</span><span class="num">ADL</span></div>
                <div v-for="l in w.account_legs" :key="l.leg_id" class="legrow" :class="{ghost:l.data_state!=='PRESENT'}">
                  <span :title="l.note||''"><b :class="'vx-'+(l.venue||l.account)">{{ l.account }}</b> · {{ legCn(l.role) }}</span>
                  <span :class="l.side==='LONG'?'up':'dn'">{{ l.side==='LONG'?'多':'空' }}</span>
                  <span class="num">{{ l.qty!=null ? fmtU(l.qty) : '—' }}</span>
                  <span class="num">{{ l.notional_usdt!=null ? fmtU(l.notional_usdt) : '—' }}</span>
                  <span class="num">{{ l.mark!=null ? l.mark : '—' }}</span>
                  <span class="num" :class="cls0(l.upnl)">{{ l.upnl!=null ? fmt2(l.upnl) : '—' }}</span>
                  <span class="num">{{ l.funding_daily_pct!=null ? fmt2(l.funding_daily_pct) : (l.interest_daily_pct!=null ? '息'+fmt2(l.interest_daily_pct) : '—') }}</span>
                  <span class="num" :class="liqCls(l.dist_liq_pct ?? l.liq_pct)">{{ (l.dist_liq_pct ?? l.liq_pct)!=null ? fmtU(l.dist_liq_pct ?? l.liq_pct) : '—' }}</span>
                  <span class="num">{{ l.adl!=null ? l.adl : '—' }}</span>
                </div>
                <div class="legft">腿事实=交易所直拉快照;组合聚合=服务端 {{ ge(w).agg_version||'legagg' }}(最差腿口径);子行无独立开平仓入口</div>
              </div>
            </div>
            <EmptyState v-if="!posShown.length" kind="none" :title="`「${queueLabel}」队列为空`" hint="点流程条其它分段查看"/>
            <!-- C4 期现交割持仓卡(独立数据链:/research/c4/positions,不占 V6 work_items 投影) -->
            <C4Board @open-asset="openAsset360"/>
          </div>
        </div>
        <!-- 栏3·风险 -->
        <div class="col c-risk">
          <div class="chd"><b>风险 · 必须处理优先</b></div>
          <div class="list pad">
            <div v-if="p0item" class="must" @click="openItem(p0item)">
              <b>{{ p0item.symbol }} · {{ p0item.stage_detail }}</b>
              <div class="qa"><i>发生了什么</i><span>{{ p0item.what_happened }}</span></div>
              <div class="qa"><i>系统已做</i><span>{{ p0item.system_did }}</span></div>
              <div class="qa"><i>你需要做什么</i><span>{{ p0item.next_action }}</span></div>
            </div>
            <div v-else-if="p0inc" class="must">
              <b>P0 · {{ p0inc.venue }} {{ p0inc.title }}</b>
              <div class="qa"><i>详情</i><span>{{ (p0inc.detail||'').slice(0,90) }}</span></div>
              <div class="qa"><i>处置</i><span><a @click="deepRisk">进风险与账务·风险事件 →</a></span></div>
            </div>
            <div v-else class="okline"><FIcon name="check" :size="12"/> 当前无必须处理事件</div>
            <!-- 批A §6A.5B:无 P0/P1 也不留空白——账户风险概览(与持仓行 group_econ 同源) -->
            <div v-if="acctOverview" class="aro">
              <div class="rrow"><b>最差强平距离</b>
                <span :class="liqCls(acctOverview.worst?.d)">{{ acctOverview.worst ? fmtU(acctOverview.worst.d)+'%('+(acctOverview.worst.v||'?')+'·'+acctOverview.worst.sym+')' : '—' }}</span></div>
              <div class="rrow"><b>硬亏预算余最小</b>
                <span class="amtx">{{ acctOverview.minBud ? fmt2(acctOverview.minBud.b)+' U('+acctOverview.minBud.sym+')' : '—' }}</span></div>
              <div class="rrow"><b>真实退出盈亏合计</b>
                <span :class="cls0(acctOverview.closeoutSum)">{{ acctOverview.closeoutSum!=null ? fmt2(acctOverview.closeoutSum)+' U' : '—' }}</span></div>
            </div>
            <div class="rrow"><b>平台/账户限制 · {{ restrictedN }}</b><span>{{ restrictedN? '已停新增·详情见风险事件' : '全部平台正常' }}</span></div>
            <div class="rrow" :class="{warn:protHotN>0}"><b>点差保护 · {{ protHotN? protHotN+' 项越线' : '全部正常' }}</b>
              <span>{{ protNote }}</span></div>
            <div class="rrow"><b>维护排空 · {{ maintT }}</b></div>
            <div class="rrow" :class="{warn:abnN>0}"><b>账目核对 · {{ abnN }} 项待清</b>
              <span>{{ abnN? '见异常队列' : '账本投影无待清差异' }}</span></div>
            <div class="fillv"></div>
            <div v-for="f in freezes" :key="f.scope" class="rrow warn frzrow">
              <b>人工冻结中 · {{ f.scope.replace('GLOBAL:GLOBAL','全局') }}·{{ f.mode }} · 已{{ f.age_hours }}h</b>
              <span>{{ f.expires_at ? '到期自动解除 '+f.expires_at.slice(5,16) : '无过期时间(超24h会跑马灯提醒)' }}
                <a class="frzlift" @click="liftFreeze(f)">恢复 NORMAL</a></span>
            </div>
            <button class="freeze" :disabled="pausing" @click="pauseNew"><FIcon name="pause" :size="12"/> 暂停开新仓（减险·立即）</button>
          </div>
        </div>
      </div>
    </div>
    <!-- 六段抽屉(帧 eTSxn 规格):不跳页,技术详情单独折叠 -->
    <el-drawer v-model="drawerOpen" :title="(sel?.symbol||'')+' · '+(sel?.strategy_code||'')" size="440px"
               @closed="selst.wi.value=''">
      <div v-if="sel" class="dw">
        <div class="dsec"><i>当前结论</i>
          <p>{{ sel.workflow_stage==='DISCOVERED' ? evT(sel)+' · '+(sel.next_action||'') : (sel.stage_detail||'') }}</p></div>
        <div class="dsec"><i>研判依据 / AiCoin</i>
          <p><span v-if="sel.research_status && sel.research_status!=='NOT_REQUIRED'" class="rs" :class="sel.research_status">
              研判{{ {PENDING:'待完成',COMPLETED:'已完成',EXPIRED:'已过期(需复核)'}[sel.research_status]||sel.research_status }}
              <template v-if="sel.next_review_at"> · 复核至 {{ (sel.next_review_at||'').slice(5,16) }}</template></span>
            {{ sel.what_happened }} <a class="dl" @click="$router.push({path:'/mix/aicoin',query:{symbol:sel.symbol}})">打开研判 →</a></p></div>
        <div class="dsec"><i>成本与预计收益</i>
          <p>投入 <ValueCell :value="sel.capital_reserved" :state="sel.data_state?.capital_reserved" suffix=" U"/> ·
             预期 <ValueCell :value="sel.expected_net_return" :state="sel.data_state?.expected_net_return" suffix=" bps/日" :dp="1"/> ·
             已确认 <ValueCell :value="sel.confirmed_pnl" :state="sel.data_state?.confirmed_pnl" suffix=" U" :dp="1"/></p></div>
        <div class="dsec"><i>平台与账户风险</i>
          <p :class="sel.risk_status?.level==='NORMAL'?'':'warn'">{{ sel.risk_status?.level==='NORMAL' ? '低 · 全所正常' : (sel.risk_status?.reason || sel.risk_status?.level) }}</p>
          <p v-if="sel.risk_protection_state && sel.risk_protection_state!=='NORMAL'" class="warn">
            <FIcon name="shield" :size="11"/> 点差保护[{{ PROT_CN[sel.risk_protection_state]||sel.risk_protection_state }}](shadow):
            真实退出盈亏 <ValueCell :value="sel.closeout_pnl_net" suffix=" U" :dp="2"
              :state="sel.closeout_pnl_net==null?'NOT_CONNECTED':undefined"/> ·
            预算余量 <ValueCell :value="sel.hard_loss_budget_remaining" suffix=" U" :dp="2"
              :state="sel.hard_loss_budget_remaining==null?'NOT_YET_AVAILABLE':undefined"/> ·
            回本 <ValueCell :value="sel.recovery_windows" suffix=" 窗" :dp="1"
              :state="sel.recovery_windows==null?'NOT_YET_AVAILABLE':undefined"/></p></div>
        <div class="dsec"><i>系统已经做了什么</i><p>{{ sel.system_did }}</p></div>
        <div class="dsec"><i>完成条件与下一步</i><p>{{ sel.completion_condition }}<br/>触发:{{ sel.next_trigger }}</p></div>
        <!-- V6.2 R3 套利原理三层(§6):机制白话;当前实例数字由上方各段承担 -->
        <PlaybookBlock :code="sel.strategy_code"/>
        <div class="dsec"><i>深链</i><p>
          <a class="dl" @click="$router.push({path:'/mix/history',query:{symbol:sel.symbol}})">交易与核对 →</a>
          <a class="dl" @click="deepRisk">风险事件 →</a>
          <a class="dl" @click="$router.push('/mix/report')">资产收益 →</a></p></div>
        <div class="dacts">
          <PrimaryAction v-for="a in (sel.allowed_actions||[])" :key="a.code" :a="a"
                         :still-allowed="sel.still_allowed" :blocking-reason="sel.blocking_reason"
                         :state="rowState[sel.work_item_id]||''" @run="(x)=>runAct(sel,x)"/>
        </div>
        <div class="tech" @click="techOpen=!techOpen"><FIcon name="wrench" :size="11"/> 技术详情（只读折叠）{{ techOpen?'▲':'▼' }}</div>
        <div v-if="techOpen" class="techb">
          <p>owner: {{ sel.owner_key||'N/A' }} ｜ saga: {{ sel.saga_id||'N/A' }} ｜ epoch: {{ sel.control_epoch??'N/A' }}</p>
          <p>runtime: {{ sel.runtime_stage }} ｜ 能力: {{ sel.product_capability }} ｜ rv: {{ sel.row_version }}</p>
        </div>
      </div>
    </el-drawer>
    <PartialRepayModal v-model="repay.open" :symbol="repay.symbol"/>
    <ClosePreviewDialog v-model="closeP.open" :symbol="closeP.symbol"/>
    <!-- Asset 360 单币全景抽屉（批A入口：币种点击；批B-C补充提/韩国/研判表单） -->
    <el-drawer v-model="asset360Open" :size="asset360Fullscreen?'100%':'60%'" direction="rtl"
               :show-close="false" :close-on-press-escape="true" :append-to-body="true"
               :destroy-on-close="false" class="a360drawer">
      <Asset360 v-if="asset360Open && asset360Id" :asset-id="asset360Id" :fullscreen="asset360Fullscreen"
                @close="closeAsset360" @toggle-fullscreen="toggleAsset360Fullscreen"/>
    </el-drawer>
    <!-- 手动计划(泛产品):研判先行——本弹窗只指路,不直接建计划 -->
    <el-dialog v-model="npOpen" title="新建手动计划（研判先行 · 全产品同一链路）" width="440px">
      <el-form label-width="80px" size="small">
        <el-form-item label="标的"><el-input v-model="np.symbol" placeholder="如 TONUSDT" @input="np.symbol=np.symbol.toUpperCase()"/></el-form-item>
        <el-form-item label="产品">
          <el-select v-model="np.product" style="width:100%">
            <el-option v-for="p in ['C1','C2.H','C2.C','C2.P','C3.S','C3.R','C4','C5','C6','O1']" :key="p" :value="p"/>
          </el-select>
        </el-form-item>
      </el-form>
      <p class="npnote">流程:研判(阶段/依据/风险/结论=准备计划)→ 生成计划 → DRY_RUN 冷却 → 二次认证 → shadow 终态。
        证据先行,任何产品的手动计划都必须挂研判案件。</p>
      <template #footer>
        <el-button @click="npOpen=false">取消</el-button>
        <el-button type="primary" :disabled="!np.symbol" @click="gotoResearch">去研判并生成计划 →</el-button>
      </template>
    </el-dialog>
    <!-- V6.2 R3+ 首次聚光教程(§5.1L3,课程进度服务端记账) -->
    <CoachMark v-model="tourOpen" :steps="TOUR_STEPS" @done="tourDone"/>
  </div>
</template>
<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { mixApi } from '../../api/mix'
import Asset360 from '../../components/v62/Asset360.vue'
import { useV6Snapshot } from '../../composables/useV6'
import { useSelection } from '../../composables/useSelection'
import V6StatusBar from '../../components/V6StatusBar.vue'
import C4Board from '../../components/v62/C4Board.vue'
import AutomationStrip from '../../components/v62/AutomationStrip.vue'
import DailyBriefing from '../../components/v62/DailyBriefing.vue'
import PlaybookBlock from '../../components/v62/PlaybookBlock.vue'
import GuidanceRail from '../../components/v62/GuidanceRail.vue'
import CoachMark from '../../components/v62/CoachMark.vue'
import ProcessRail from '../../components/v62/ProcessRail.vue'
import PrimaryAction from '../../components/v62/PrimaryAction.vue'
import ValueCell from '../../components/v62/ValueCell.vue'
import EmptyState from '../../components/v62/EmptyState.vue'
import WorkTable from '../../components/v62/WorkTable.vue'
import PartialRepayModal from '../../components/rules/PartialRepayModal.vue'
import ClosePreviewDialog from '../../components/ClosePreviewDialog.vue'

const route = useRoute()
const router = useRouter()
const { snap, stale, canOpen, isStrong, ago, refetch } = useV6Snapshot()
const selst = useSelection('today')
const vtab = ref('持仓')
const queue = ref('全部')
const sel = ref(null)
const selId = computed(() => sel.value?.work_item_id || '')
const drawerOpen = computed({ get: () => !!sel.value, set: v => { if (!v) sel.value = null } })
const techOpen = ref(false)
const rowState = ref({})
const pausing = ref(false)
const repay = ref({ open: false, symbol: '' })
const closeP = ref({ open: false, symbol: '' })
const WALLS = [{ k: 'market', t: '屏1' }, { k: 'exec', t: '屏2' }, { k: 'risk', t: '屏3' }]
// §9.2 训练通过→今日工作出现「训练/演练」按钮(菜单侧同步收敛,Layout 负责)
const trainOk = ref(false)
mixApi.v6Training().then(r => { trainOk.value = !!r?.certified }).catch(() => {})
// 视图模式:list 轻列表 | table 深表格(工作台主表并入统一外壳);focusCol=聚焦视图(§3.1)
const viewMode = ref('list')
const focusCol = ref('')
// 手动计划入口(泛产品,研判先行)
const npOpen = ref(false)
const np = ref({ symbol: '', product: 'C2.P' })
function gotoResearch() {
  npOpen.value = false
  router.push({ path: '/mix/aicoin', query: { symbol: np.value.symbol, product: np.value.product } })
}
const tableItems = computed(() => {
  let list = items.value
  if (queue.value !== '全部' && QUEUES[queue.value]) list = list.filter(w => QUEUES[queue.value].includes(w.workflow_stage))
  return list
})
// §8 点差保护摘要(shadow):WATCH 不计入越线,NO_ADD 起算
const PROT_CN = { WATCH: '观察', NO_ADD: '禁加仓', REDUCE_REQUIRED: '需减仓', EXIT_REQUIRED: '需退出' }
const protHotN = computed(() => {
  const c = snap.value?.risk_exit_summary?.counts || {}
  return (c.NO_ADD || 0) + (c.REDUCE_REQUIRED || 0) + (c.EXIT_REQUIRED || 0)
})
const protNote = computed(() => {
  const c = snap.value?.risk_exit_summary?.counts || {}
  const parts = Object.entries(c).filter(([k]) => k !== 'NORMAL').map(([k, v]) => `${PROT_CN[k] || k}${v}`)
  return parts.length ? parts.join(' · ') + '(shadow评估·退出仍人工)' : '在管组合退出估值全部在预算内'
})

// ── V6.2 R3+ 首次聚光教程(课程版本由服务端 guidance_template 管;完成才记进度,跳过不算) ──
const tourOpen = ref(false)
const tourVer = ref(1)
const TOUR_STEPS = [
  { selector: '.autostrip', title: '自动运行状态条', text: '所有真钱自动回路在这里首屏可见:武装状态、最近轮次、发布一致性。点"回路详情"能看每个回路的执行链和时间线。' },
  { selector: '.railrow', title: '工作流程条', text: '机会→研判→执行→持有→核对的七段队列。点任一段过滤下方列表;异常永远置顶。' },
  { selector: '.c-opp', title: '机会列表', text: '每行三段:身份、路线容量、净期望。点行打开右侧抽屉看六段事实与套利原理,唯一主动作在行尾。' },
  { selector: '.planbtn', title: '手动计划', text: '所有产品的人工开仓从这里走:研判先行→DRY_RUN→审批,不存在绕闸的快捷下单。' },
]
async function initTour () {
  try {
    const p = await mixApi.guidanceProgress()
    const cur = p?.curricula?.TODAY_TOUR || 1
    tourVer.value = cur
    const done = (p?.completed || []).some(r => r.scope === 'TODAY_TOUR' && r.curriculum_version >= cur)
    if (!done) tourOpen.value = true
  } catch (e) { /* 未登录/失败=不弹 */ }
}
onMounted(initTour)
async function tourDone (completed) {
  if (!completed) return   // §10:完成条件=走完,不是点过
  try { await mixApi.guidanceComplete('TODAY_TOUR', tourVer.value) } catch (e) {}
}
function openItemById (id) {
  const w = items.value.find(x => x.work_item_id === id || x.symbol === id)
  if (w) openItem(w)
}

const items = computed(() => snap.value?.work_items || [])
const opps = computed(() => items.value.filter(w => w.workflow_stage === 'DISCOVERED'))
const abn = computed(() => items.value.filter(w => w.workflow_stage === 'RECONCILING'))
const abnN = computed(() => abn.value.length)
const p0item = computed(() => abn.value[0] || null)
const p0inc = computed(() => (snap.value?.incidents || []).find(i => i.severity === 'fatal') || null)
const restrictedN = computed(() => [...new Set((snap.value?.incidents || []).filter(i => i.severity === 'fatal').map(i => i.venue))].length)
const maintT = computed(() => { const s = snap.value?.site_maintenance_state; return (!s || s === 'NORMAL' || s === 'CLOSED') ? '无进行中' : s })

const QUEUES = { 机会: ['DISCOVERED'], 人工研判: ['RESEARCH'], 审批: ['REVIEW', 'RESERVED'], 执行: ['EXECUTING'],
                 持有: ['HOLDING'], 退出与还币: ['EXITING'], 异常: ['RECONCILING'], 核对: ['RECONCILING'] }
const railSteps = computed(() => {
  const c = (sts) => items.value.filter(w => sts.includes(w.workflow_stage)).length
  const cur = queue.value
  const mk = (label, sts, extra = {}) => ({ key: label, label, count: c(sts),
    state: cur === label ? 'current' : (extra.state || (c(sts) > 0 ? 'done' : 'todo')) })
  const steps = []
  if (abnN.value > 0) steps.push({ key: '异常', label: '异常', count: abnN.value, state: cur === '异常' ? 'current' : 'error' })
  // V6.2 PATCH-01 §3.1:机会→人工研判→审批→…;C2.P 必经研判,C2.H 可主动送研判
  steps.push(mk('机会', ['DISCOVERED']), mk('人工研判', ['RESEARCH']), mk('审批', ['REVIEW', 'RESERVED']),
             mk('执行', ['EXECUTING']), mk('持有', ['HOLDING']), mk('退出与还币', ['EXITING']),
             { key: '核对', label: '核对', count: 0, state: cur === '核对' ? 'current' : 'todo' })
  return steps
})
function pickQueue(k) { queue.value = queue.value === k ? '全部' : k; if (k === '机会') vtab.value = '机会'; else vtab.value = '持仓' }
const queueLabel = computed(() => queue.value)
const queueNote = computed(() => queue.value === '全部' ? '进行中全量' : `已按「${queue.value}」过滤 · 点流程条取消`)
const justClosed = ref(new Set())   // 乐观:刚平仓的wid立即隐藏,不等投影(20s)刷新
const posShown = computed(() => {
  let list = items.value.filter(w => w.workflow_stage !== 'DISCOVERED' && !justClosed.value.has(w.work_item_id))
  if (queue.value !== '全部' && QUEUES[queue.value]) list = list.filter(w => QUEUES[queue.value].includes(w.workflow_stage))
  return list.sort((a, b) => (b.workflow_stage === 'RECONCILING') - (a.workflow_stage === 'RECONCILING'))
})

function evT(w) { const v = w.expected_net_return; return v == null ? '—' : `${v>=0?'+':''}${Number(v).toFixed(1)} bps/日` }
function stCls(w) { return w.workflow_stage === 'RECONCILING' ? 'dn' : (w.workflow_stage === 'EXITING' ? 'amber' : 'up') }
function primaryOf(w) {
  // 去掉平仓预演(用户2026-07-19:小额持仓无需预演,C2走⚡直接平仓,C1/C3走各自流程)
  const a = (w.allowed_actions || []).filter(x => x.code !== 'close_preview')
  return a.find(x => x.kind === 'primary') || a[0] || null
}
function openItem(w) { sel.value = w; selst.wi.value = w.work_item_id }
function openWall(k) { window.open(`/wall/${k}?token=${localStorage.getItem('mix_token')||''}`, `wall-${k}`) }
function deepRisk() { router.push({ path: '/mix/venuerisk' }) }

async function runAct(w, a) {
  const id = w.work_item_id
  switch (a.code) {
    case 'close_preview': closeP.value = { open: true, symbol: w.symbol }; return
    case 'c3_partial_repay': repay.value = { open: true, symbol: w.symbol }; return
    case 'goto_risk_center': deepRisk(); return
    case 'view': case 'view_basis': openItem(w); return
    case 'proposal_approve': approveProposal(w); return
    case 'proposal_reject': rejectProposal(w); return
    // C2.P 人工研判(V6.2 PATCH-01):研判与生成计划都在 AiCoin 研判工作台完成
    case 'open_research': router.push({ path: '/mix/aicoin', query: { symbol: w.symbol } }); return
    case 'create_manual_plan':
      router.push({ path: '/mix/aicoin', query: { symbol: w.symbol, plan: w.research_case_id || '' } }); return
  }
  // 提交三态:loading→服务端确认;失败=failed 可重试,绝不假成功迁移
  rowState.value = { ...rowState.value, [id]: 'loading' }
  try {
    const r = await mixApi.v6Command({ command_type: a.code,
      params: { symbol: w.symbol, strategy_code: w.strategy_code, work_item_id: id } })
    ElMessage.success(r?.result?.note || '已确认')
    rowState.value = { ...rowState.value, [id]: '' }
    refetch()   // 服务端确认后立即拉快照→行随真实状态原地迁移(非乐观更新)
  } catch (e) {
    ElMessage.error(e?.detail || e?.error || '被拒绝')
    rowState.value = { ...rowState.value, [id]: 'failed' }
  }
}
async function pauseNew() {
  let ttl = null
  try {
    const { value } = await ElMessageBox.prompt(
      '暂停开新仓(全局 NO_NEW_RISK,减险立即生效)。自动恢复时长(小时,留空=永久;永久超24h会提醒):',
      '暂停开新仓', { confirmButtonText: '暂停', inputValue: '24',
        inputPattern: /^\d*\.?\d*$/, inputErrorMessage: '小时数或留空' })
    ttl = value && Number(value) > 0 ? Number(value) : null
  } catch (e) { return }
  pausing.value = true
  try {
    await mixApi.v6Command({ command_type: 'pause_new_risk',
      params: { reason: '今日工作:暂停新增', ttl_hours: ttl } })
    ElMessage.success(`已提交暂停新增${ttl ? `(${ttl}h后自动恢复)` : '(永久,超24h将提醒)'}`)
    loadFreezes()
  } catch (e) { ElMessage.error(e?.detail || '失败') } finally { pausing.value = false }
}
// 提案审批原地闭环(此前 proposal_approve 只 router.push 跳中控台=断头路,目标页无审批弹窗)
function _pidOf(w) {
  const m = String(w?.position_intent_id || '').match(/^dryrun:(\d+)$/)
  return m ? Number(m[1]) : null
}
async function approveProposal(w) {
  const pid = _pidOf(w)
  if (!pid) { ElMessage.error('工作项无提案ID(position_intent_id),请在交易与核对·提案页处理'); return }
  try {
    if (isStrong.value) {
      await ElMessageBox.confirm(`批准提案 #${pid}(${w.symbol})?APPROVED 仍是 shadow 终态,不会直接下单。`, '批准提案', { confirmButtonText: '批准' })
      await mixApi.proposalApprove(pid, '')
      ElMessage.success(`提案 #${pid} 已批准(shadow 登记,武装另门控)`)
      refetch(); return
    }
    const { value } = await ElMessageBox.prompt(
      `批准提案 #${pid}(${w.symbol})。APPROVED 仍是 shadow 终态,不会直接下单。\n输入 Authenticator 6位动态码:`,
      '二次认证批准', { confirmButtonText: '批准', inputPattern: /^\d{6}$/, inputErrorMessage: '6位数字' })
    await mixApi.proposalApprove(pid, value)
    ElMessage.success(`提案 #${pid} 已批准(shadow 登记,武装另门控)`)
    refetch()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '批准失败(动态码错误或状态已变)') }
}
async function rejectProposal(w) {
  const pid = _pidOf(w)
  if (!pid) { ElMessage.error('工作项无提案ID'); return }
  try {
    await ElMessageBox.confirm(`驳回提案 #${pid}(${w.symbol})?`, '驳回', { type: 'warning' })
    await mixApi.proposalReject(pid)
    ElMessage.success('已驳回')
    refetch()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '驳回失败') }
}
// 快线直通(2026-07-19用户授权):额度内点击即真实下单;额度逐操作员自定义
const flLimit = ref(50); const flBusy = ref('')
async function loadFlLimit() {
  try { flLimit.value = (await mixApi.fastlaneLimitGet())?.max_notional_usdt ?? 50 } catch (e) { /* 默认50 */ }
}
async function editFlLimit() {
  try {
    const { value } = await ElMessageBox.prompt(
      `你的快线额度(单笔≤此值直接下单,免冷却/免逐笔认证;超额走DRY_RUN预演)。
当前 ${flLimit.value}U,输入新额度(0-5000):`,
      '快线额度设置', { inputValue: String(flLimit.value), inputPattern: /^\d+(\.\d+)?$/, inputErrorMessage: '数字' })
    await mixApi.fastlaneLimitPut({ max_notional_usdt: Number(value) })
    flLimit.value = Number(value)
    ElMessage.success(`快线额度已设为 ${value}U`)
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '保存失败') }
}
// 快线直接平仓(与开仓对称):HOLDING/EXITING 的C2类(有两腿venue)可一键真平
const flcBusy = ref('')
function fcLegs(w) {
  // 从 account_legs 取多空腿平台(side_a/side_b 已废弃改用 account_legs)
  const legs = w.account_legs || []
  const lng = legs.find(l => String(l.side).toUpperCase() === 'LONG')
  const sht = legs.find(l => String(l.side).toUpperCase() === 'SHORT')
  return { vl: lng?.venue, vs: sht?.venue }
}
function canFastClose(w) {
  if (!['HOLDING', 'EXITING'].includes(w.workflow_stage)) return false
  const { vl, vs } = fcLegs(w)
  if (vl && vs && vl !== vs) return true           // C2跨所双腿
  if (String(w.strategy_code || '').startsWith('C1') && (w.account_legs || []).length >= 1) return true  // C1永续+理财腿
  return false
}
async function fastClose(w) {
  const isC1 = String(w.strategy_code || '').startsWith('C1')
  const { vl, vs } = fcLegs(w)
  const base = (w.symbol || '').replace(/USDT$/, '')
  const desc = isC1 ? `${w.symbol}(C1:永续买回+理财赎回+现货卖)` : `${w.symbol}(${vl} × ${vs} 两腿reduce-only)`
  try {
    await ElMessageBox.confirm(
      `⚡直接平仓 ${desc}
真实平仓(减险方向,免额度/深度闸);${isC1?'理财腿FAST赎回可能数秒;':''}平后自动入账。确认?`,
      '直接平仓', { confirmButtonText: '平仓', type: 'warning' })
  } catch (e) { return }
  flcBusy.value = w.work_item_id
  try {
    const payload = isC1
      ? { symbol: w.symbol, work_item_id: w.work_item_id, product: 'C1', base_asset: base }
      : { symbol: w.symbol, work_item_id: w.work_item_id, venue_long: vl, venue_short: vs }
    const r = await mixApi.fastlaneClose(payload)
    ElMessage.success(`已平仓:${w.symbol}${r.already_flat ? '(已是flat)' : ''}`)
    // 乐观:立即隐藏该持仓行,不等投影(manager 20s)刷新;后端已真实平仓
    justClosed.value = new Set([...justClosed.value, w.work_item_id])
    refetch()
    setTimeout(() => { const s2 = new Set(justClosed.value); s2.delete(w.work_item_id); justClosed.value = s2 }, 8000)
  } catch (e) {
    ElMessage.error(e?.detail || e?.error || '平仓被拒/失败')
  } finally { flcBusy.value = '' }
}
async function fastOpen(w) {
  const [vl, vs] = String(w.route || '').split('↔')
  const cap = Math.min(Number(w.capital_reserved) || flLimit.value, flLimit.value)
  let notional
  try {
    const { value } = await ElMessageBox.prompt(
      `⚡快线直通 ${w.symbol}(${vl} 多 ↔ ${vs} 空)
点击"开仓"即真实下单——免冷却、免逐笔认证;
风险权威/额度/一档深度/黑名单四道机器闸自动过,任一不过即拒。
每腿名义U(≤${flLimit.value}):`,
      '直接开仓', { confirmButtonText: '开仓', inputValue: String(cap),
        inputPattern: /^\d+(\.\d+)?$/, inputErrorMessage: '数字' })
    notional = Number(value)
  } catch (e) { return }
  flBusy.value = w.work_item_id
  try {
    const r = await mixApi.fastlaneOpen({ symbol: w.symbol, venue_long: vl, venue_short: vs, notional_usdt: notional })
    ElMessage.success(`已开仓:${w.symbol} ${r.qty}(~${r.notional_per_leg}U/腿) saga=${r.saga_id};manager已接管监护`)
    refetch()
  } catch (e) {
    ElMessage.error(e?.detail || e?.error || '开仓被拒/失败')
  } finally { flBusy.value = '' }
}
// 人工冻结可见性:防"按了忘了"(2026-07-18 #19 事故防呆)
const freezes = ref([])
async function loadFreezes() {
  try { freezes.value = (await mixApi.riskSummary())?.manual_freezes || [] } catch (e) { freezes.value = [] }
}
async function liftFreeze(f) {
  try {
    await ElMessageBox.confirm(`解除 ${f.scope} 的 ${f.mode}(追加 NORMAL 覆盖,恢复新增能力)?`, '恢复 NORMAL', { type: 'warning' })
    await mixApi.v6Command({ command_type: 'resume_normal', params: { reason: `今日工作:解除人工冻结(已${f.age_hours}h)` } })
    ElMessage.success('已提交恢复(≤30s合并生效)')
    setTimeout(loadFreezes, 3000)
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
// selection 恢复:URL wi/tab/queue
watch(items, list => {
  if (selst.wi.value && !sel.value) {
    const w = list.find(x => x.work_item_id === selst.wi.value)
    if (w) sel.value = w
  }
})
watch([vtab, queue, viewMode], () => { selst.filters.value = { vt: vtab.value, q: queue.value, v: viewMode.value } })
onMounted(() => {
  const f = selst.filters.value
  if (f.vt) vtab.value = f.vt
  if (f.q) queue.value = f.q
  if (f.v === 'table') viewMode.value = 'table'
  // PATCH-02 §3.1 命名视图:overview 三栏 / workflow 表格 / opportunity|position|risk 聚焦
  const vw = String(route.query.view || '')
  if (vw === 'table' || vw === 'workflow') viewMode.value = 'table'
  else if (vw === 'opportunity') { focusCol.value = '机会'; vtab.value = '机会' }
  else if (vw === 'position') { focusCol.value = '持仓'; vtab.value = '持仓' }
  else if (vw === 'risk') { focusCol.value = '风险'; vtab.value = '风险' }
  mixApi.uxPageview('today')   // M5 收敛门槛数据:今日工作 vs 工作台使用量
  loadFreezes(); setInterval(loadFreezes, 30000)  // 人工冻结章30s刷新
  loadFlLimit()
  loadLabNote()
})
// ── 批A §6A:持仓紧凑行数据带 + 账户腿展开(展开态进 selection 会话层) ──
function ge(w) { return w.group_econ || {} }
function fmtU(v) { const n = Number(v); return Math.abs(n) >= 1000 ? n.toLocaleString('en-US', { maximumFractionDigits: 0 }) : String(Math.round(n * 100) / 100) }
function fmt2(v) { return Number(v).toFixed(2) }
function cls0(v) { return v == null ? '' : (Number(v) >= 0 ? 'up' : 'dn') }
function pxCls(code) { return 'px-' + String(code||'').split('.')[0].toLowerCase() }
function liqCls(d) { if (d == null) return ''; return d < 50 ? 'dn' : (d < 80 ? 'warn' : 'up') }
function legCn(r) { return ({ PERP_SHORT: '永续空', PERP_LONG: '永续多', SPOT_LONG: '现货多', BORROW_SPOT_SHORT: '借币空', PERP_LONG_HEDGE: '对冲多(主)' })[r] || r }
// P2 修复:提取账户信息显示(主账户/对冲账户)
function accountsOf(w) {
  const legs = w.account_legs || []
  if (!legs.length) return ''
  const accounts = [...new Set(legs.map(l => l.account).filter(Boolean))]
  return accounts.length ? accounts.slice(0, 2).join('·') : ''
}
const expRows = ref({ ...(selst.sess.value.expanded || {}) })
function toggleExp(id) {
  expRows.value = { ...expRows.value, [id]: !expRows.value[id] }
  selst.remember({ expanded: expRows.value })
}
// 批B §6A.2:父子表双预设(任务精简/策略完整)+单一产品专业列——进 URL 可深链
// /mix/work?view=workflow&preset=strategy&product=C3.S
const wtPreset = ref(String(route.query.preset || 'today'))
const wtProduct = ref(String(route.query.product || ''))
function setWtPreset(p) { wtPreset.value = p; router.replace({ query: { ...route.query, preset: p } }) }
function setWtProduct(p) {
  wtProduct.value = p
  const q = { ...route.query }; p ? (q.product = p) : delete q.product
  router.replace({ query: q })
}
// 无 P0/P1 时的账户风险概览(§6A.5B:右栏不留空白;与持仓行 group_econ 同源不造第二口径)
const acctOverview = computed(() => {
  const rows = posShown.value.map(w => ({ sym: w.symbol, e: ge(w) })).filter(x => x.e.agg_version)
  if (!rows.length) return null
  let worst = null, minBud = null, closeoutSum = null
  for (const x of rows) {
    const d = x.e.margin_min_dist_liq_pct
    if (d != null && (!worst || d < worst.d)) worst = { d, v: x.e.margin_worst_venue, sym: x.sym }
    const b = x.e.budget_remaining
    if (b != null && (!minBud || b < minBud.b)) minBud = { b, sym: x.sym }
    if (x.e.closeout_pnl_net != null) closeoutSum = (closeoutSum || 0) + Number(x.e.closeout_pnl_net)
  }
  return { worst, minBud, closeoutSum }
})
// Asset 360 单币全景抽屉（批A §6A入口复用：所有币种行一次点击打开同一抽屉）
const asset360Open = ref(false); const asset360Id = ref(''); const asset360Fullscreen = ref(false)
function openAsset360(symbol) {
  asset360Id.value = symbol?.toUpperCase() || ''
  if (asset360Id.value) { asset360Open.value = true; asset360Fullscreen.value = false }
}
function closeAsset360() { asset360Open.value = false }
function toggleAsset360Fullscreen() { asset360Fullscreen.value = !asset360Fullscreen.value }
// LAB 提醒(与旧中控台同一已读键 mix_lab_read_id:同一 artifact 两处不重复打扰)
const labNote = ref(''); const labLatestId = ref(0)
async function loadLabNote() {
  try {
    const ob = await mixApi.v6LabOutbox()
    const rows = ob?.data || []
    if (rows.length && Number(localStorage.getItem('mix_lab_read_id') || 0) < rows[0].id) {
      labLatestId.value = rows[0].id
      labNote.value = `LAB 有新结果（${rows[0].project_id} · ${rows[0].title}）`
    }
  } catch { /* LAB 不可达不影响生产 */ }
}
function dismissLab() {
  localStorage.setItem('mix_lab_read_id', String(labLatestId.value || 0))
  labNote.value = ''
}
</script>
<style scoped>
.today{height:100%;display:flex;flex-direction:column;background:var(--mix-bg);min-height:0}
.body{flex:1;display:flex;flex-direction:column;gap:8px;padding:8px 12px;min-height:0}
.labbar{font-size:10.5px;color:var(--mix-blue);background:#4A9CFF14;border:1px solid #4A9CFF44;border-radius:6px;padding:5px 12px;display:flex;align-items:center;gap:6px}
.labbar a{color:var(--mix-blue);cursor:pointer;text-decoration:underline}
.labx{margin-left:auto;cursor:pointer;color:var(--mix-t3);padding:0 4px}
.labx:hover{color:var(--mix-t1)}
.vtabs{display:none;gap:2px;background:var(--mix-panel);border-radius:6px;padding:2px;align-items:center}
.vt{font-size:11.5px;color:var(--mix-t2);padding:5px 16px;border-radius:5px;cursor:pointer}
.vt.on{background:var(--mix-card2);color:var(--mix-t1);font-weight:700}
.wallbtns{margin-left:auto;display:flex;gap:8px;padding-right:8px}
.wallbtns a{font-size:10px;color:var(--mix-t3);cursor:pointer}
.cols{flex:1;display:flex;gap:8px;min-height:0}
.col{background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.c-opp{width:400px;flex:none}.c-pos{flex:1;min-width:0}.c-risk{width:300px;flex:none}
.chd{display:flex;justify-content:space-between;align-items:baseline;padding:8px 12px 6px}
.chd b{font-size:12px;color:var(--mix-t1)}
.chd i{font-size:9.5px;color:var(--mix-t3);font-style:normal}
.list{flex:1;overflow:auto;min-height:0}
.list.pad{padding:2px 10px 8px;display:flex;flex-direction:column;gap:6px}
.row{display:flex;align-items:center;gap:8px;padding:0 12px;height:44px;border-bottom:1px solid var(--mix-border);cursor:pointer}
.row.tall{flex-direction:column;align-items:stretch;justify-content:center;gap:2px;height:52px}
/* 批A:四数据带持仓行/三行机会行——固定行高保稳定布局(§6.1),数字变化不跳版 */
.row.pos4{height:auto;min-height:78px;padding:6px 12px}
.row.opp3{height:auto;min-height:64px;padding:5px 12px}
.band{display:flex;gap:12px;align-items:baseline;min-width:0}
.band.dim .bc b{color:var(--mix-t2)}
.bc{display:inline-flex;gap:4px;align-items:baseline;min-width:0;white-space:nowrap}
.bc.grow{flex:1;min-width:0;overflow:hidden}
.bc i{font-style:normal;font-size:8.5px;color:var(--mix-t3);flex:none}
.bc b{font-size:10.5px;color:var(--mix-t1);font-weight:600;font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis}
.bc b.wh{font-weight:400;color:var(--mix-t3);font-size:9.5px}
/* 符号色优先级修复:.bc b(0-1-1)/.band.dim .bc b(0-3-1)会压过单类.up/.dn(0-1-0)——
   类名打上但颜色被覆盖="配色没变化"的根因;用!important一次压平 */
.bc b.up,.band.dim .bc b.up{color:var(--mix-green)!important}
.bc b.dn,.band.dim .bc b.dn{color:var(--mix-red)!important}
.bc b.warn,.band.dim .bc b.warn{color:#FF8A3D!important}
.bc b.bad,.band.dim .bc b.bad{color:var(--mix-red)!important}
.legs span.up{color:var(--mix-green)!important}
.legs span.dn{color:var(--mix-red)!important}
.legs span.warn{color:#FF8A3D!important}
.expbtn{flex:none;width:16px;text-align:center;color:var(--mix-t3);cursor:pointer;font-size:10px;border-radius:3px}
.expbtn:hover,.expbtn.on{color:var(--mix-accent);background:var(--mix-card2)}
.legs{margin-top:4px;border:1px solid var(--mix-border);border-radius:6px;background:var(--mix-panel);overflow:hidden;cursor:default}
.leghd,.legrow{display:grid;grid-template-columns:minmax(110px,1.4fr) 34px repeat(7,minmax(52px,1fr));gap:4px;padding:3px 8px;align-items:center}
.leghd{font-size:8.5px;color:var(--mix-t3);border-bottom:1px solid var(--mix-border);background:var(--mix-card2)}
.legrow{font-size:9.5px;color:var(--mix-t1);border-bottom:1px solid var(--mix-border)}
.legrow:last-of-type{border-bottom:none}
.legrow.ghost{opacity:.55}
.legrow span,.leghd span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.leghd .num,.legrow .num{text-align:right;font-variant-numeric:tabular-nums}
.legft{font-size:8px;color:var(--mix-t3);padding:3px 8px;border-top:1px dashed var(--mix-border)}
.aro{display:flex;flex-direction:column;gap:0;border:1px solid var(--mix-border);border-radius:6px;background:var(--mix-panel);padding:2px 0;margin-top:2px}
.rs{font-size:8.5px;padding:1px 5px;border-radius:3px;border:1px solid var(--mix-border);color:var(--mix-t2)}
.rs.COMPLETED{color:var(--mix-green);border-color:#0ECB8155}
.rs.PENDING{color:var(--mix-accent);border-color:#F0B90B55}
.up{color:var(--mix-green)}.dn{color:var(--mix-red)}.warn{color:#FF8A3D}
:deep(.a360drawer .el-drawer__body){padding:0;overflow:hidden}
.row .r1{display:flex;align-items:center;gap:10px}
.row .r2{font-size:9.5px;color:var(--mix-t3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row.sel{background:var(--mix-card2);border-left:2px solid var(--mix-blue)}
.row.bad{background:#F6465D0A}
.row.submitting{opacity:.75}
.sym{font-size:11px;color:var(--mix-gold,#F0B90B);font-weight:800;cursor:pointer;border-bottom:1px dashed transparent}
.rsep{color:var(--mix-t3);font-style:normal;margin:0 1px}
.sym:hover{color:var(--mix-accent);border-bottom-color:var(--mix-accent)}
.prod{font-size:11px;color:var(--mix-t2)}
.accts{font-size:9px;color:var(--mix-t3);padding:1px 5px;border-radius:3px;background:var(--mix-card2);border:1px solid var(--mix-border)}
.ev{font-size:11px;font-weight:700}
.st{font-size:10.5px}
.ddl{font-size:9.5px;color:var(--mix-t3)}
.up{color:var(--mix-green)}.dn{color:var(--mix-red)}.amber{color:var(--mix-accent)}
.fill{flex:1;min-width:0}.fillv{flex:1}
.must{background:#F6465D0D;border:1px solid #F6465D66;border-radius:6px;padding:8px 10px;display:flex;flex-direction:column;gap:3px;cursor:pointer}
.must b{font-size:11px;color:var(--mix-red)}
.qa{display:flex;gap:6px;font-size:9.5px}
.qa i{color:var(--mix-t3);font-style:normal;flex:none;width:64px;font-size:9px}
.qa span{color:var(--mix-t2);line-height:1.35}
.qa a{color:var(--mix-blue);cursor:pointer}
.okline{color:var(--mix-green);font-size:11px;font-weight:700;padding:8px 2px}
.rrow{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px;display:flex;flex-direction:column;gap:1px}
.rrow b{font-size:10px;color:var(--mix-t2)}
.rrow span{font-size:8.5px;color:var(--mix-t3)}
.rrow.warn b{color:#FF8A3D}
.freeze{height:34px;border-radius:6px;background:#F6465D14;border:1px solid #F6465D66;color:var(--mix-red);font-size:11px;font-weight:700;cursor:pointer}
.frzrow b{color:#FF8A3D}
.frzlift{color:var(--mix-gold,#F0B90B);cursor:pointer;margin-left:6px;text-decoration:underline}
.railrow{display:flex;align-items:center;gap:8px}
.railfill{flex:1;min-width:0}
.vswitch{flex:none;display:flex;background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:2px}
.vswitch a{font-size:10.5px;color:var(--mix-t3);padding:3px 10px;border-radius:4px;cursor:pointer}
.vswitch a.on{background:var(--mix-card2);color:#F0B90B;font-weight:700}
.planbtn{flex:none;font-size:10.5px;padding:5px 10px;border-radius:6px;cursor:pointer;font-weight:700;
  background:#F0B90B14;border:1px solid #F0B90B4D;color:#F0B90B}
.planbtn:hover{border-color:#F0B90B}
.npnote{font-size:10.5px;color:var(--mix-t3);line-height:1.6;margin:4px 0 0}
.trainbtn{flex:none;font-size:10.5px;padding:5px 10px;border-radius:6px;cursor:pointer;
  background:#4A9CFF14;border:1px solid #4A9CFF66;color:var(--mix-blue,#4A9CFF);font-weight:700}
.trainbtn:hover{border-color:#F0B90B;color:#F0B90B}
.railinline{flex:none;margin-left:8px}
/* 覆盖GuidanceRail的fixed定位为relative内联 */
:deep(.railinline .grail){position:relative;right:auto;bottom:auto;display:inline-block}
:deep(.railinline .panel){bottom:auto;top:48px;right:0}
.dw{display:flex;flex-direction:column;gap:10px}
.dsec i{font-size:9.5px;color:var(--mix-t3);font-style:normal;font-weight:700}
.dsec p{font-size:11.5px;color:var(--mix-t1);margin:3px 0 0;line-height:1.55}
.dsec p.warn{color:#FF8A3D}
.prot{font-size:9px;border-radius:3px;padding:1px 5px;font-weight:700;flex:none}
.prot.WATCH{color:#F0B90B;border:1px solid #F0B90B66}
.prot.NO_ADD{color:#FF8A3D;border:1px solid #FF8A3D88}
.prot.REDUCE_REQUIRED,.prot.EXIT_REQUIRED{color:#F6465D;border:1px solid #F6465D88;background:#F6465D14}
/* §3.1 聚焦视图:query view=opportunity|position|risk 只显示对应栏 */
.cols[data-focus="机会"] .c-pos,.cols[data-focus="机会"] .c-risk{display:none}
.cols[data-focus="持仓"] .c-opp,.cols[data-focus="持仓"] .c-risk{display:none}
.cols[data-focus="风险"] .c-opp,.cols[data-focus="风险"] .c-pos{display:none}
.cols[data-focus="风险"] .c-risk{flex:1}
.cols[data-focus="机会"] .c-opp{flex:1}
.rs{font-size:9px;border:1px solid var(--mix-border);border-radius:3px;padding:1px 5px;margin-right:6px;color:var(--mix-t2)}
.rs.COMPLETED{color:#35b57c;border-color:#35b57c66}
.rs.PENDING{color:#F0B90B;border-color:#F0B90B66}
.rs.EXPIRED{color:#F6465D;border-color:#F6465D66}
.dl{color:var(--mix-blue);cursor:pointer;font-size:10.5px}
.dacts{display:flex;flex-wrap:wrap;gap:6px;padding-top:2px}
.tech{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px;font-size:10px;color:var(--mix-t2);cursor:pointer}
.techb{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px}
.techb p{font-size:9px;color:var(--mix-t3);margin:2px 0;word-break:break-all}
@media (max-width:1360px){
  .vtabs{display:flex}
  .cols[data-vtab='机会'] .c-pos,.cols[data-vtab='机会'] .c-risk{display:none}
  .cols[data-vtab='持仓'] .c-opp,.cols[data-vtab='持仓'] .c-risk{display:none}
  .cols[data-vtab='风险'] .c-opp,.cols[data-vtab='风险'] .c-pos{display:none}
  .c-opp,.c-risk{width:100%}
}
.flbtn{height:24px;padding:0 10px;border-radius:5px;border:1px solid #F0B90B;background:#F0B90B;color:#111;font-size:10.5px;font-weight:800;cursor:pointer;white-space:nowrap}
.flbtn:disabled{opacity:.6;cursor:wait}
.fllim{margin-left:8px;font-size:10px;color:var(--mix-gold,#F0B90B);cursor:pointer;border:1px dashed #F0B90B66;border-radius:4px;padding:1px 6px}
.flcbtn{height:24px;padding:0 10px;border-radius:5px;border:1px solid var(--mix-red,#F6465D);background:transparent;color:var(--mix-red,#F6465D);font-size:10.5px;font-weight:800;cursor:pointer;white-space:nowrap;margin-right:6px}
.flcbtn:disabled{opacity:.6;cursor:wait}
</style>
