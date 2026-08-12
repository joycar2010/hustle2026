<template>
  <el-card><template #header><span class="ch"><el-icon><Setting/></el-icon> 参数下发 · 模板管理</span>
    <span style="float:right"><UserSelect v-model="user" width="180px" placeholder="选择用户下发" style="margin-right:8px"/><el-button size="small" type="primary" :disabled="!user" @click="load">{{t('refresh')}}</el-button></span></template>

    <!-- 工具条: 预设库 + 批量下发 + 从用户复制 -->
    <div class="toolbar">
      <span class="tb-lbl">参数预设:</span>
      <el-select v-model="presetId" size="small" placeholder="选择预设" clearable style="width:180px" @change="onPresetPick">
        <el-option v-for="p in presets" :key="p.id" :value="p.id" :label="p.name"/>
      </el-select>
      <el-button size="small" :disabled="!presetId||!user" @click="applyPresetToUser" title="把所选预设套用到当前用户(可再编辑)">套用到当前用户</el-button>
      <el-button size="small" type="danger" plain :disabled="!presetId" @click="delPreset">删除预设</el-button>
      <el-divider direction="vertical"/>
      <span class="tb-lbl">批量下发:</span>
      <el-select v-model="batchUsers" size="small" multiple filterable remote :remote-method="searchUsers" collapse-tags collapse-tags-tooltip
        placeholder="多选用户" style="width:240px">
        <el-option v-for="u in userOpts" :key="u.username" :value="u.username" :label="u.username+(u.nickname?(' ('+u.nickname+')'):'')"/>
      </el-select>
      <el-button size="small" type="warning" :disabled="!batchUsers.length" @click="openBatch" title="把一套参数一次下发给全部所选用户">批量下发…</el-button>
      <el-divider direction="vertical"/>
      <el-button size="small" @click="openCopy" title="把另一个用户的参数复制到当前编辑(不立即下发)">从用户复制</el-button>
    </div>

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

    <!-- 编辑弹窗 -->
    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="'参数编辑 — '+(cur.symbol||'')+'（下发后引擎热重载）'" width="720" top="6vh">
      <el-alert v-if="changedList.length" type="warning" :closable="false" show-icon style="margin-bottom:10px"
        :title="'本次改动 '+changedList.length+' 项: '+changedList.map(c=>c.label+' '+c.from+'→'+c.to).join('  |  ')"/>
      <el-tabs v-model="etab">
        <el-tab-pane label="基础 · 手数 · 数据" name="base">
          <el-row :gutter="16">
            <el-col :span="8"><el-form-item label="对冲品种" label-width="96"><el-input v-model="cur.hedge_symbol" :class="cc('hedge_symbol')" placeholder="如 XAUUSD.m" autocomplete="off"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="进单量(阶梯)" label-width="96"><el-input-number v-model="cur.ladders" :class="cc('ladders')" :min="1" :max="20" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="每U手数" label-width="96"><el-input-number v-model="cur.base_lot" :class="cc('base_lot')" :step="0.01" :min="0" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主手数倍数" label-width="96"><el-input-number v-model="cur.main_lot_mult" :step="0.01" :min="0" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲手数倍数" label-width="96"><el-input-number v-model="cur.hedge_lot_mult" :step="0.01" :min="0" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="数据偏移" label-width="96"><el-input-number v-model="cur.basis_offset" :step="0.01" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主数据倍数" label-width="96"><el-input-number v-model="cur.data_mult_main" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲数据倍数" label-width="96"><el-input-number v-model="cur.data_mult_hedge" :step="1" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="主进位" label-width="96"><el-input-number v-model="cur.digits_main" :class="cc('digits_main')" :min="0" :max="8" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="对冲进位" label-width="96"><el-input-number v-model="cur.digits_hedge" :class="cc('digits_hedge')" :min="0" :max="8" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="数据同步(秒)" label-width="96"><el-input-number v-model="cur.sync_interval_sec" :step="0.5" :min="0" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="每秒数据条数" label-width="96"><el-input-number v-model="cur.records_per_sec" :min="1" style="width:100%"/></el-form-item></el-col>
          </el-row>
        </el-tab-pane>
        <el-tab-pane label="护栏 · 点差" name="guard">
          <el-row :gutter="16">
            <el-col :span="8"><el-form-item label="入场点差阈值" label-width="100"><el-input-number v-model="cur.entry_spread" :class="cc('entry_spread')" :step="0.01" :precision="2" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="止盈点" label-width="100"><el-input-number v-model="cur.tp_points" :class="cc('tp_points')" :step="0.5" style="width:100%"/></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="止损点" label-width="100"><el-input-number v-model="cur.sl_points" :class="cc('sl_points')" :step="1" style="width:100%"/></el-form-item></el-col>
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
        <el-tab-pane label="周末停市" name="weekend">
          <el-form-item label="周末保护(总)" label-width="120"><el-switch v-model="cur.weekend_guard"/></el-form-item>
          <el-form-item label="周六可交易" label-width="120"><el-switch v-model="cur.weekend_sat"/></el-form-item>
          <el-form-item label="周日可交易" label-width="120"><el-switch v-model="cur.weekend_sun"/></el-form-item>
          <div style="color:#909399;font-size:12px">周末保护开启后, 未勾选"可交易"的周六/周日将停市。</div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="saveAsPreset" style="float:left" title="把当前参数存为命名预设, 供一键套用">存为预设</el-button>
        <el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存并热重载</el-button>
      </template>
    </el-dialog>

    <!-- 批量下发确认 -->
    <el-dialog v-model="batchDlg" title="批量下发确认" width="480">
      <div>将把以下参数下发给 <b>{{batchUsers.length}}</b> 个用户:</div>
      <div style="margin:8px 0;color:#606266;font-size:13px">{{batchUsers.join('、')}}</div>
      <el-alert type="info" :closable="false" show-icon style="margin:8px 0"
        :title="batchSrc==='preset'?('参数来源: 预设「'+(presets.find(p=>p.id===presetId)?.name||'')+'」'):'参数来源: 当前编辑中的参数'"/>
      <template #footer><el-button @click="batchDlg=false">取消</el-button><el-button type="warning" :loading="saving" @click="doBatch">确认批量下发</el-button></template>
    </el-dialog>

    <!-- 从用户复制 -->
    <el-dialog v-model="copyDlg" title="从用户复制参数" width="420">
      <UserSelect v-model="copyFrom" width="100%" placeholder="选择源用户"/>
      <div style="color:#909399;font-size:12px;margin-top:8px">复制其参数填入当前编辑(不立即下发, 可再改后保存)。</div>
      <template #footer><el-button @click="copyDlg=false">取消</el-button><el-button type="primary" :disabled="!copyFrom" @click="doCopy">复制填入</el-button></template>
    </el-dialog>
  </el-card>
</template>
<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import UserSelect from '../components/UserSelect.vue'
const { t }=useI18n()
const user=ref(''),list=ref([]),dlg=ref(false),cur=ref({}),orig=ref({}),saving=ref(false),etab=ref('base')
const presets=ref([]),presetId=ref(null)
const batchUsers=ref([]),userOpts=ref([]),batchDlg=ref(false),batchSrc=ref('cur')
const copyDlg=ref(false),copyFrom=ref('')

const CHG_LABELS={hedge_symbol:'对冲品种',ladders:'进单量',base_lot:'每U手数',entry_spread:'入场点差',tp_points:'止盈',sl_points:'止损',digits_main:'主进位',digits_hedge:'对冲进位'}
const changedList=computed(()=>{
  const out=[]; if(!dlg.value)return out
  for(const k in CHG_LABELS){ if(String(cur.value[k])!==String(orig.value[k])) out.push({label:CHG_LABELS[k],from:orig.value[k],to:cur.value[k]}) }
  return out
})
function cc(f){ return (dlg.value && String(cur.value[f])!==String(orig.value[f]))?'p-chg':'' }

async function load(){ if(!user.value){ list.value=[]; return } try{ list.value=(await api.params(user.value)).params||[] }catch(e){} }
function edit(r){ cur.value={...r}; orig.value={...r}; etab.value='base'; dlg.value=true }

// 硬校验(前端, 与后端 _param_validate 同口径)
function validate(c){
  const e=[]
  const n=k=>{ const v=Number(c[k]); return isNaN(v)?null:v }
  if(!(c.ladders>=1&&c.ladders<=20)) e.push('进单量须 1..20')
  if(!(n('base_lot')>0)) e.push('每U手数须 >0')
  if(n('entry_spread')===null||n('entry_spread')<0) e.push('入场点差须 ≥0')
  if(n('tp_points')===null) e.push('止盈点须为数字')
  if(n('sl_points')===null) e.push('止损点须为数字')
  for(const k of ['digits','digits_main','digits_hedge']){ const v=c[k]; if(v!=null&&!(v>=0&&v<=8)) e.push(k+' 进位须 0..8') }
  if(!(c.hedge_symbol||'').trim()) e.push('对冲品种不能为空')
  return e
}
async function save(){
  const errs=validate(cur.value)
  if(errs.length){ ElMessage.error('校验未通过: '+errs.join('; ')); return }
  saving.value=true
  try{
    const r=await api.paramsSave({ ...cur.value, username:user.value })
    ElMessage.success(r.msg||'参数已下发'); dlg.value=false
    const want=Number(cur.value.entry_spread)
    setTimeout(async()=>{ await load()
      const row=list.value.find(x=>x.symbol===cur.value.symbol)
      if(row && Number(row.entry_spread)===want) ElMessage.success('已回读确认: 参数落库, 引擎下轮热重载生效')
      else ElMessage.warning('已保存, 但回读未命中(引擎可能尚未刷新)')
    },3500)
  }catch(e){ ElMessage.error('下发失败: '+(e?.response?.data?.detail||e?.message||'错误')) }
  finally{ saving.value=false }
}

// ---- 预设库 ----
async function loadPresets(){ try{ presets.value=(await api.paramPresets()).presets||[] }catch(e){} }
function onPresetPick(){}
async function applyPresetToUser(){
  const p=presets.value.find(x=>x.id===presetId.value); if(!p){ return }
  const base=list.value[0]||{symbol:p.symbol||'XAUUSD'}
  cur.value={...base,...p.cfg,symbol:base.symbol||p.symbol||'XAUUSD'}; orig.value={...base}; etab.value='base'; dlg.value=true
  ElMessage.info('已载入预设「'+p.name+'」到编辑, 确认后保存下发')
}
async function saveAsPreset(){ await saveAsPresetFrom(cur.value) }
async function saveAsPresetFrom(cfg){
  try{
    const { value:name }=await ElMessageBox.prompt('预设名称', '存为参数预设', { confirmButtonText:'保存', cancelButtonText:'取消' })
    if(!name) return
    const errs=validate(cfg); if(errs.length){ ElMessage.error('校验未通过: '+errs.join('; ')); return }
    await api.paramPresetSave({ name, note:'', symbol:cfg.symbol||'XAUUSD', cfg:strip(cfg) })
    ElMessage.success('预设已保存'); loadPresets()
  }catch(e){ if(e!=='cancel') ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delPreset(){
  if(!presetId.value)return
  try{ await ElMessageBox.confirm('删除该预设？','确认',{type:'warning'}); await api.paramPresetDelete(presetId.value); ElMessage.success('已删除'); presetId.value=null; loadPresets() }
  catch(e){ if(e!=='cancel') ElMessage.error('删除失败') }
}
// 剥离非参数字段(username/id/symbol 等), 只留参数键
function strip(c){ const o={...c}; delete o.username; delete o.id; delete o.user_id; delete o.license_key; delete o.updated_at; return o }

// ---- 批量下发 ----
async function searchUsers(q){ try{ userOpts.value=(await api.adminUsers(q||'')).users||[] }catch(e){} }
function openBatch(){
  if(dlg.value){ batchSrc.value='cur' } else if(presetId.value){ batchSrc.value='preset' } else { ElMessage.warning('请先打开编辑参数, 或选择一个预设作为下发内容'); return }
  batchDlg.value=true
}
async function doBatch(){
  let cfg, symbol
  if(batchSrc.value==='preset'){ const p=presets.value.find(x=>x.id===presetId.value); cfg=p.cfg; symbol=p.symbol||'XAUUSD' }
  else { cfg=strip(cur.value); symbol=cur.value.symbol||'XAUUSD' }
  const errs=validate(cfg); if(errs.length){ ElMessage.error('校验未通过: '+errs.join('; ')); return }
  saving.value=true
  try{ const r=await api.paramsBatch(batchUsers.value, symbol, cfg)
    ElMessage.success('批量下发完成: 成功 '+r.n+(r.fail.length?(' / 失败 '+r.fail.length):''))
    if(r.fail.length) ElMessage.warning('失败: '+r.fail.map(f=>f.user+'('+f.err+')').join('; '))
    batchDlg.value=false
  }catch(e){ ElMessage.error(e?.response?.data?.detail||'批量下发失败') }
  finally{ saving.value=false }
}

// ---- 从用户复制 ----
function openCopy(){ if(!dlg.value){ ElMessage.warning('请先「编辑下发」打开某用户参数, 再从其他用户复制填入'); return } copyFrom.value=''; copyDlg.value=true }
async function doCopy(){
  try{ const rows=(await api.params(copyFrom.value)).params||[]
    const src=rows.find(x=>x.symbol===cur.value.symbol)||rows[0]
    if(!src){ ElMessage.warning('源用户无参数'); return }
    const keep={symbol:cur.value.symbol}
    cur.value={...cur.value,...strip(src),...keep}
    ElMessage.success('已复制 '+copyFrom.value+' 的参数(未下发, 可再改)'); copyDlg.value=false
  }catch(e){ ElMessage.error('复制失败') }
}
loadPresets(); searchUsers('')
</script>
<style scoped>
.ch{display:inline-flex;align-items:center;gap:6px;font-weight:600}
.ch .el-icon{color:var(--el-color-primary)}
.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;padding:8px 10px;background:var(--el-fill-color-lighter);border-radius:8px}
.tb-lbl{font-size:12px;color:var(--el-text-color-secondary);font-weight:600}
.p-chg :deep(.el-input__wrapper),.p-chg:deep(.el-input__wrapper){box-shadow:0 0 0 1px #e6a23c inset!important;background:#fdf6ec}
</style>
