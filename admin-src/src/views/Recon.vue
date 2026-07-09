<template>
  <el-card><template #header>跨用户对账 · 三源核对 + 成交账本</template>
    <el-tabs v-model="tab">
      <!-- ============ 持仓对账(原有) ============ -->
      <el-tab-pane label="持仓对账" name="recon">
        <el-alert type="info" :closable="false" title="对账口径：引擎评估(eval) ↔ 双腿持仓(positions) ↔ 账户(account) 三源一致性" style="margin-bottom:12px"/>
        <el-table :data="rows" size="small" border>
          <el-table-column prop="user" label="用户"/>
          <el-table-column prop="symbol" label="品种"/>
          <el-table-column prop="mainLots" label="主腿手数"/>
          <el-table-column prop="hedgeLots" label="对冲手数"/>
          <el-table-column label="单腿"><template #default="s"><el-tag size="small" :type="s.row.singleLeg?'danger':'success'">{{s.row.singleLeg?('单腿!'+(s.row.missing||'')):'齐'}}</el-tag></template></el-table-column>
          <el-table-column label="对账结论"><template #default="s"><el-tag size="small" :type="s.row.ok?'success':'warning'">{{s.row.ok?'一致':'偏差'}}</el-tag></template></el-table-column>
        </el-table>
        <el-divider/>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="市场">{{market}}</el-descriptions-item>
          <el-descriptions-item label="循环对数">{{pairs}}</el-descriptions-item>
          <el-descriptions-item label="单腿计数">{{singleCnt}}</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>

      <!-- ============ 成交记录·统计(持久账本, 原 /deals 并入) ============ -->
      <el-tab-pane label="成交记录 · 统计" name="deals">
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
          <el-input v-model="user" size="small" placeholder="用户名(空=全部)" clearable style="width:150px" @keyup.enter="loadDeals" @clear="loadDeals"/>
          <el-select v-model="leg" size="small" style="width:110px" @change="loadDeals">
            <el-option label="全部腿" value=""/><el-option label="主腿" value="main"/><el-option label="对冲腿" value="hedge"/>
          </el-select>
          <el-select v-model="days" size="small" style="width:96px" @change="loadDeals">
            <el-option label="近1天" :value="1"/><el-option label="近7天" :value="7"/><el-option label="近30天" :value="30"/><el-option label="近90天" :value="90"/>
          </el-select>
          <el-button size="small" @click="loadDeals">{{t('refresh')}}</el-button>
          <el-button size="small" type="primary" :loading="sweeping" @click="doSweep" title="手动触发一次 云端→本地账本 增量对账(平时每120秒自动)">立即对账</el-button>
          <span style="font-size:11px;color:#909399">平仓即落库 + 120s 云端对账 · 不受云端会话清零影响</span>
        </div>
        <!-- 统计卡(SQL 全量聚合, 与筛选联动, 不受明细 limit 截断) -->
        <div class="stat-row" v-if="stats">
          <div class="stat-card"><span class="l" title="筛选期内已平成交笔数">成交笔数</span><b>{{stats.n}}</b></div>
          <div class="stat-card"><span class="l" title="成交手数合计">手数合计</span><b>{{stats.lots}}</b></div>
          <div class="stat-card"><span class="l" title="盈亏+过夜费+手续费 合计">净盈亏</span><b :class="stats.net>=0?'up':'down'">{{stats.net>=0?'+':''}}{{stats.net}}</b></div>
          <div class="stat-card"><span class="l" title="主腿已实现盈亏合计">主腿盈亏</span><b :class="stats.profit_main>=0?'up':'down'">{{stats.profit_main>=0?'+':''}}{{stats.profit_main}}</b></div>
          <div class="stat-card"><span class="l" title="对冲腿已实现盈亏合计">对冲腿盈亏</span><b :class="stats.profit_hedge>=0?'up':'down'">{{stats.profit_hedge>=0?'+':''}}{{stats.profit_hedge}}</b></div>
          <div class="stat-card"><span class="l" title="过夜费合计">过夜费</span><b>{{stats.swap}}</b></div>
          <div class="stat-card"><span class="l" title="手续费合计">手续费</span><b>{{stats.commission}}</b></div>
          <div class="stat-card"><span class="l" title="盈利笔数 / 总笔数">胜率</span><b>{{stats.win_rate!=null?stats.win_rate+'%':'—'}}</b></div>
        </div>
        <!-- 按用户小计(多用户时显示) -->
        <el-table v-if="stats && stats.by_user && stats.by_user.length>1" :data="stats.by_user" size="small" border style="margin-bottom:10px;max-width:640px">
          <el-table-column prop="username" label="用户名" width="130"/>
          <el-table-column prop="n" label="笔数" width="80"/>
          <el-table-column label="盈亏" width="110"><template #default="s"><span :class="s.row.profit>=0?'up':'down'">{{s.row.profit>=0?'+':''}}{{s.row.profit}}</span></template></el-table-column>
          <el-table-column prop="swap" label="过夜费" width="90"/>
          <el-table-column prop="commission" label="手续费" width="90"/>
        </el-table>
        <!-- 明细 -->
        <el-table :data="deals" size="small" height="calc(100vh - 430px)" stripe v-loading="loading">
          <el-table-column prop="time_bj" label="时间(北京)" width="160"/>
          <el-table-column prop="username" label="用户名" width="110"/>
          <el-table-column label="腿" width="80"><template #default="s"><el-tag size="small" :type="s.row.leg==='main'?'danger':'warning'">{{s.row.leg==='main'?'主':'对冲'}}</el-tag></template></el-table-column>
          <el-table-column prop="ticket" label="票号" width="115"/>
          <el-table-column prop="symbol" label="品种" width="90"/>
          <el-table-column label="方向" width="70"><template #default="s"><el-tag size="small" :type="s.row.side==='buy'?'danger':s.row.side==='sell'?'primary':'info'">{{ {buy:'买',sell:'卖'}[s.row.side]||s.row.side }}</el-tag></template></el-table-column>
          <el-table-column prop="lots" label="手数" width="72"/>
          <el-table-column label="开仓价" width="96"><template #default="s">{{s.row.price_open!=null?Number(s.row.price_open).toFixed(2):'-'}}</template></el-table-column>
          <el-table-column label="平仓价" width="96"><template #default="s">{{s.row.price!=null?Number(s.row.price).toFixed(2):'-'}}</template></el-table-column>
          <el-table-column label="盈亏" width="90"><template #default="s"><span :class="s.row.profit>=0?'up':'down'">{{s.row.profit>=0?'+':''}}{{Number(s.row.profit||0).toFixed(2)}}</span></template></el-table-column>
          <el-table-column label="过夜费" width="80"><template #default="s">{{Number(s.row.swap||0).toFixed(2)}}</template></el-table-column>
          <el-table-column label="手续费" width="80"><template #default="s">{{Number(s.row.commission||0).toFixed(2)}}</template></el-table-column>
          <el-table-column prop="comment" label="注释" min-width="130" show-overflow-tooltip/>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useLiveRefresh } from '../composables/useLiveRefresh'
const { t }=useI18n()
const tab=ref('recon')
// ---- 持仓对账(原有) ----
const rows=ref([]),market=ref('--'),pairs=ref(0),singleCnt=ref(0)
async function load(){
  try{ const st=await api.engineState()
    market.value=st.market?.closed?('休市('+st.market.why+')'):'开市'; pairs.value=st.cycle?.pairs||0; singleCnt.value=st.cycle?.single_leg||0
    const ev=st.eval||{}; rows.value=Object.entries(ev).map(([user,e])=>({user,symbol:e.symbol,mainLots:e.main_lots,hedgeLots:e.hedge_lots,singleLeg:e.single_leg,missing:e.missing,ok:!e.single_leg}))
  }catch(e){}
}
const live=useLiveRefresh(load,{interval:3000})
// ---- 成交记录·统计(持久账本) ----
const user=ref(''), leg=ref(''), days=ref(7), deals=ref([]), stats=ref(null), loading=ref(false), sweeping=ref(false)
async function loadDeals(){
  loading.value=true
  try{ const r=await api.adminLegDeals({user:user.value.trim(),leg:leg.value,days:days.value,limit:500})
    deals.value=r.deals||[]; stats.value=r.stats||null }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'加载失败') }
  finally{ loading.value=false }
}
async function doSweep(){
  sweeping.value=true
  try{ const r=await api.adminLegDealsSweep(); ElMessage.success('对账完成, 新增 '+(r.added||0)+' 笔'); loadDeals() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'对账失败') }
  finally{ sweeping.value=false }
}
onMounted(()=>{ load(); live.start(); loadDeals() }); onUnmounted(()=>live.stop())
</script>
<style scoped>
.up{color:#1aa86a;font-weight:600}
.down{color:#e05555;font-weight:600}
.stat-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.stat-card{min-width:96px;padding:8px 14px;border:1px solid var(--el-border-color-lighter);border-radius:8px;background:var(--el-fill-color-lighter);display:flex;flex-direction:column;gap:2px}
.stat-card .l{font-size:11px;color:var(--el-text-color-secondary)}
.stat-card b{font-size:16px}
</style>
