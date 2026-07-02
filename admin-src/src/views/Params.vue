<template>
  <el-card><template #header><span class="ch"><el-icon><Setting/></el-icon> 参数下发 · 模板管理</span>
    <span style="float:right"><UserSelect v-model="user" width="180px" placeholder="选择用户下发" style="margin-right:8px"/><el-button size="small" type="primary" :disabled="!user" @click="load">{{t('refresh')}}</el-button></span></template>
    <el-table :data="list" size="small" border>
      <el-table-column prop="symbol" label="品种" width="90"/>
      <el-table-column prop="hedge_symbol" label="对冲品种" width="100"/>
      <el-table-column prop="entry_spread" label="入场点差" width="90"/>
      <el-table-column prop="tp_points" label="止盈点" width="80"/>
      <el-table-column prop="sl_points" label="止损点" width="80"/>
      <el-table-column prop="ladders" label="进单量" width="80"/>
      <el-table-column prop="base_lot" label="每U手数" width="90"/>
      <el-table-column prop="hold_secs" label="持仓秒" width="80"/>
      <el-table-column label="周末保护" width="90"><template #default="s"><el-tag size="small" :type="s.row.weekend_guard?'success':'info'">{{s.row.weekend_guard?'开':'关'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="110" fixed="right"><template #default="s"><el-button size="small" type="primary" @click="edit(s.row)">编辑下发</el-button></template></el-table-column>
    </el-table>
    <div style="color:#909399;font-size:12px;margin-top:8px">此处为全局参数下发(对齐用户端「对冲参数配置」),下发后引擎下轮热重载生效。逐坑覆盖在用户端控制台设置。</div>

    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="'参数编辑 — '+(cur.symbol||'')+'（下发后引擎热重载）'" width="720" top="6vh">
      <el-tabs v-model="etab">
        <!-- 基础 / 手数 / 数据 -->
        <el-tab-pane label="基础 · 手数 · 数据" name="base">
          <el-row :gutter="16">
            <el-col :span="8"><el-form-item label="对冲品种" label-width="96"><el-input v-model="cur.hedge_symbol" placeholder="如 XAUUSD.m" autocomplete="off"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="进单量(阶梯)" label-width="96"><el-input-number v-model="cur.ladders" :min="1" :max="20" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="每U手数" label-width="96"><el-input-number v-model="cur.base_lot" :step="0.01" :min="0" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主手数倍数" label-width="96"><el-input-number v-model="cur.main_lot_mult" :step="0.01" :min="0" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲手数倍数" label-width="96"><el-input-number v-model="cur.hedge_lot_mult" :step="0.01" :min="0" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="数据偏移" label-width="96"><el-input-number v-model="cur.basis_offset" :step="0.01" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主数据倍数" label-width="96"><el-input-number v-model="cur.data_mult_main" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲数据倍数" label-width="96"><el-input-number v-model="cur.data_mult_hedge" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主进位" label-width="96"><el-input-number v-model="cur.digits_main" :min="0" :max="8" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲进位" label-width="96"><el-input-number v-model="cur.digits_hedge" :min="0" :max="8" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="数据同步(秒)" label-width="96"><el-input-number v-model="cur.sync_interval_sec" :step="0.5" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="每秒数据条数" label-width="96"><el-input-number v-model="cur.records_per_sec" :min="1" style="width:100%"/></el-form-item></el-col>
          </el-row>
        </el-tab-pane>
        <!-- 护栏 / 点差 -->
        <el-tab-pane label="护栏 · 点差" name="guard">
          <el-row :gutter="16">
            <el-col :span="8"><el-form-item label="入场点差阈值" label-width="100"><el-input-number v-model="cur.entry_spread" :step="0.01" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="止盈点" label-width="100"><el-input-number v-model="cur.tp_points" :step="0.5" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="止损点" label-width="100"><el-input-number v-model="cur.sl_points" :step="1" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主点差上限" label-width="100"><el-input-number v-model="cur.main_spread_cap" :step="0.01" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲点差上限" label-width="100"><el-input-number v-model="cur.hedge_spread_cap" :step="0.01" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="滑点容差" label-width="100"><el-input-number v-model="cur.slippage_tol" :step="0.01" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="滑点停顿(分)" label-width="100"><el-input-number v-model="cur.slippage_pause_min" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="入场排队上限" label-width="100"><el-input-number v-model="cur.max_inflight" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="匹配数据数量" label-width="100"><el-input-number v-model="cur.match_count" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="上下波动带" label-width="100"><el-input-number v-model="cur.fluctuation_band" :step="0.01" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主预留保证金" label-width="100"><el-input-number v-model="cur.margin_reserve_main" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲预留保证金" label-width="100"><el-input-number v-model="cur.margin_reserve_hedge" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="每手费用" label-width="100"><el-input-number v-model="cur.fee_per_lot" :step="0.01" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="智能预判预算" label-width="100"><el-input-number v-model="cur.predict_budget" :step="0.01" :min="0" style="width:100%"/></el-form-item></el-col>
          </el-row>
        </el-tab-pane>
        <!-- 时序 / 模式 -->
        <el-tab-pane label="时序 · 模式" name="mode">
          <el-row :gutter="16">
            <el-col :span="8"><el-form-item label="持仓时间(秒)" label-width="100"><el-input-number v-model="cur.hold_secs" :step="30" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="进单间隔(秒)" label-width="100"><el-input-number v-model="cur.entry_interval_sec" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="进单模式" label-width="100"><el-select v-model="cur.entry_mode" style="width:100%"><el-option value="concurrent" label="同进同出"/><el-option value="main_first" label="1先2后"/><el-option value="hedge_first" label="2先1后"/></el-select></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="出单模式" label-width="100"><el-select v-model="cur.exit_mode" style="width:100%"><el-option value="concurrent" label="同进同出"/><el-option value="main_first" label="1先2后"/><el-option value="hedge_first" label="2先1后"/></el-select></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="速度模式" label-width="100"><el-select v-model="cur.speed_mode" style="width:100%"><el-option value="normal" label="正常"/><el-option value="fast" label="高速"/><el-option value="turbo" label="极速"/></el-select></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="自动清仓" label-width="100"><el-switch v-model="cur.auto_close"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="单腿告警" label-width="100"><el-switch v-model="cur.single_leg_alert"/></el-form-item></el-col>
          </el-row>
        </el-tab-pane>
        <!-- 周末停市 -->
        <el-tab-pane label="周末停市" name="weekend">
          <el-form-item label="周末保护(总)" label-width="120"><el-switch v-model="cur.weekend_guard"/></el-form-item>
          <el-form-item label="周六可交易" label-width="120"><el-switch v-model="cur.weekend_sat"/></el-form-item>
          <el-form-item label="周日可交易" label-width="120"><el-switch v-model="cur.weekend_sun"/></el-form-item>
          <div style="color:#909399;font-size:12px">周末保护开启后, 未勾选"可交易"的周六/周日将停市。</div>
        </el-tab-pane>
      </el-tabs>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存并热重载</el-button></template>
    </el-dialog>
  </el-card>
</template>
<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import UserSelect from '../components/UserSelect.vue'
const { t }=useI18n()
const user=ref(''),list=ref([]),dlg=ref(false),cur=ref({}),saving=ref(false),etab=ref('base')
async function load(){ if(!user.value){ list.value=[]; return } try{ list.value=(await api.params(user.value)).params||[] }catch(e){} }
function edit(r){ cur.value={...r}; etab.value='base'; dlg.value=true }   // 复制整行(全列)→保存回传全部, 防洗字段
async function save(){
  saving.value=true
  try{
    const payload={ ...cur.value, username:user.value }   // 传完整行, 后端全列 UPDATE 才不丢配置
    const r=await api.paramsSave(payload)
    ElMessage.success(r.msg||'参数已下发')
    dlg.value=false
    const want=Number(cur.value.entry_spread)
    setTimeout(async()=>{
      await load()
      const row=list.value.find(x=>x.symbol===cur.value.symbol)
      if(row && Number(row.entry_spread)===want) ElMessage.success('已回读确认: 参数落库, 引擎下轮热重载生效')
      else ElMessage.warning('已保存, 但回读未命中(引擎可能尚未刷新, 请稍后手动核对)')
    },3500)
  }catch(e){ ElMessage.error('下发失败: '+(e?.response?.data?.detail||e?.message||'错误')) }
  finally{ saving.value=false }
}
</script>
<style scoped>
.ch{display:inline-flex;align-items:center;gap:6px;font-weight:600}
.ch .el-icon{color:var(--el-color-primary)}
</style>
