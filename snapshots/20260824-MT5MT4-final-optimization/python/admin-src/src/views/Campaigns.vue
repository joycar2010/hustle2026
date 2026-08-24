<template>
  <div>
    <el-card style="margin-bottom:12px" body-style="padding:10px">
      <template #header><span class="ch"><el-icon><MagicStick/></el-icon> 活动引擎</span>
        <span style="float:right"><el-button size="small" type="primary" @click="newCamp">+ 新建活动</el-button>
          <el-button size="small" @click="load">刷新</el-button></span></template>
      <div style="margin-bottom:6px;font-size:12px;color:#909399">五大类模板(点即填, 再改条件/动作):</div>
      <el-space wrap>
        <el-button v-for="t in meta.templates" :key="t.name" size="small" @click="fromTemplate(t)">{{t.name}}</el-button>
      </el-space>
      <el-divider style="margin:10px 0"/>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <b style="font-size:13px">流失召回日扫</b>
        <el-switch v-model="recall.enabled" active-text="开启" inactive-text="关闭" @change="saveRecall"/>
        <span style="font-size:11px;color:#E6A23C">召回类活动(recall_trial/recall_sub)依赖此开关开启才每日逐用户扫描触发</span>
        <span style="flex:1"></span>
        <span style="font-size:12px;color:#909399">提示券码(仅跑马灯提醒用):</span>
        <el-input v-model="recall.coupon_trial" size="small" style="width:120px" placeholder="试用召回券码" @change="saveRecall"/>
        <el-input v-model="recall.coupon_sub" size="small" style="width:120px" placeholder="订阅召回券码" @change="saveRecall"/>
      </div>
    </el-card>

    <el-card>
      <template #header><span>活动列表</span></template>
      <el-table :data="rows" size="small" border>
        <el-table-column prop="name" label="活动名" width="160"/>
        <el-table-column label="分类" width="90"><template #default="s">{{ catName(s.row.category) }}</template></el-table-column>
        <el-table-column label="触发事件" width="130"><template #default="s">{{ evName(s.row.event) }}</template></el-table-column>
        <el-table-column label="条件" width="150"><template #default="s"><code style="font-size:11px">{{ condText(s.row.cond) }}</code></template></el-table-column>
        <el-table-column label="动作"><template #default="s"><span style="font-size:12px">{{ actionsText(s.row.actions) }}</span></template></el-table-column>
        <el-table-column label="限次" width="90"><template #default="s">人{{s.row.per_user_limit}}/总{{s.row.total_limit>0?s.row.total_limit:'∞'}}</template></el-table-column>
        <el-table-column label="已触发" width="80"><template #default="s">{{s.row.fired_count}}</template></el-table-column>
        <el-table-column label="状态" width="60"><template #default="s"><el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'停用'}}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="160" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click="editCamp(s.row)">编辑</el-button>
          <el-button size="small" link type="primary" @click="openGrants(s.row.id)">记录</el-button>
          <el-button size="small" link type="danger" @click="delCamp(s.row.id)">删</el-button></template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:6px">活动由事件触发(注册/试用/付费/充值/签到/流失召回),满足条件即执行动作(发积分/成长值/赠天数/发专属券)。运营建活动即生效,与积分/券/试用/佣金链路复用,不碰交易引擎。</div>
    </el-card>

    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="editing?'编辑活动':'新建活动'" width="640">
      <el-form label-width="90">
        <el-form-item label="活动名"><el-input v-model="cur.name" placeholder="如 试用转正首单9折"/></el-form-item>
        <el-form-item label="分类"><el-select v-model="cur.category" style="width:180px">
          <el-option value="trial_convert" label="试用转化"/><el-option value="retention" label="订阅留存"/>
          <el-option value="agent" label="代理裂变"/><el-option value="staff" label="员工增长"/><el-option value="recall" label="流失召回"/></el-select></el-form-item>
        <el-form-item label="触发事件"><el-select v-model="cur.event" style="width:260px">
          <el-option v-for="e in meta.events" :key="e.key" :value="e.key" :label="e.name"/></el-select></el-form-item>

        <el-divider content-position="left">触发条件(留空=无条件)</el-divider>
        <el-form-item label="最低金额"><el-input-number v-model="condMinAmount" :min="0"/> <span class="hint">订单实付≥此值(付费/充值类)</span></el-form-item>
        <el-form-item label="限套餐月数"><el-checkbox-group v-model="condMonths"><el-checkbox :value="1">月卡</el-checkbox><el-checkbox :value="3">季卡</el-checkbox><el-checkbox :value="12">年卡</el-checkbox></el-checkbox-group></el-form-item>
        <el-form-item label="仅首次付费"><el-switch v-model="condFirstPaid"/> <span class="hint">仅 paid 事件生效</span></el-form-item>

        <el-divider content-position="left">动作(可多个)
          <el-button size="small" style="margin-left:8px" @click="addAction">+ 加动作</el-button></el-divider>
        <div v-for="(a,i) in cur.actions" :key="i" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:6px;background:#f5f7fa;padding:6px;border-radius:4px">
          <el-select v-model="a.type" size="small" style="width:150px" @change="onActType(a)">
            <el-option v-for="t in meta.action_types" :key="t.key" :value="t.key" :label="t.name"/></el-select>
          <template v-if="a.type==='points'||a.type==='growth'"><span class="hint">数值</span><el-input-number v-model="a.value" size="small" :min="0"/></template>
          <template v-if="a.type==='points_pct'"><span class="hint">比例</span><el-input-number v-model="a.rate" size="small" :min="0" :max="1" :step="0.01"/><span class="hint">0.1=实付10%</span></template>
          <template v-if="a.type==='extend_days'||a.type==='trial_days'"><span class="hint">天数</span><el-input-number v-model="a.days" size="small" :min="0"/></template>
          <template v-if="a.type==='coupon'">
            <el-input v-model="a.name" size="small" style="width:110px" placeholder="券名"/>
            <el-select v-model="a.kind" size="small" style="width:90px"><el-option value="percent" label="百分比"/><el-option value="fixed" label="立减"/></el-select>
            <el-input-number v-model="a.value" size="small" :min="0" style="width:100px"/>
            <el-select v-model="a.applies_to" size="small" style="width:100px"><el-option value="any" label="全部"/><el-option value="subscription" label="订阅"/><el-option value="iap" label="内购"/></el-select>
            <span class="hint">有效天</span><el-input-number v-model="a.valid_days" size="small" :min="1" style="width:90px"/>
          </template>
          <el-button size="small" link type="danger" @click="cur.actions.splice(i,1)">删</el-button>
        </div>

        <el-divider content-position="left">限制与有效期</el-divider>
        <el-form-item label="每人限次"><el-input-number v-model="cur.per_user_limit" :min="0"/> <span class="hint">0=不限</span></el-form-item>
        <el-form-item label="总触发上限"><el-input-number v-model="cur.total_limit" :min="0"/> <span class="hint">0=不限</span></el-form-item>
        <el-form-item label="优先级"><el-input-number v-model="cur.priority" :min="0"/> <span class="hint">大者先触发</span></el-form-item>
        <el-form-item label="有效期至"><el-date-picker v-model="cur.valid_until" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="留空=长期" style="width:220px"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="cur.enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="gdlg" title="活动发放记录" width="600">
      <el-table :data="grants" size="small" border max-height="440">
        <el-table-column prop="created_at" label="时间" width="180"/>
        <el-table-column prop="username" label="用户" width="130"/>
        <el-table-column prop="event" label="事件" width="110"/>
        <el-table-column label="结果"><template #default="s">{{ (s.row.detail&&s.row.detail.results||[]).join(', ') }}</template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const rows=ref([]),meta=ref({events:[],action_types:[],templates:[]}),dlg=ref(false),cur=ref({}),editing=ref(false)
const gdlg=ref(false),grants=ref([])
const recall=ref({enabled:false,coupon_trial:'',coupon_sub:''})
async function loadRecall(){ try{ const r=await api.recallCfgGet(); recall.value={enabled:!!r.enabled,coupon_trial:r.coupon_trial||'',coupon_sub:r.coupon_sub||''} }catch(e){} }
async function saveRecall(){ try{ await api.recallCfgSave(recall.value); ElMessage.success('召回配置已保存') }catch(e){ ElMessage.error('保存失败') } }
// 条件三件套(与 cur.cond 双向映射, 保存时组装)
const condMinAmount=ref(0),condMonths=ref([]),condFirstPaid=ref(false)
const CATN={trial_convert:'试用转化',retention:'订阅留存',agent:'代理裂变',staff:'员工增长',recall:'流失召回'}
function catName(k){ return CATN[k]||k }
function evName(k){ const e=meta.value.events.find(x=>x.key===k); return e?e.name:k }
function condText(c){ if(!c||!Object.keys(c).length)return '无'; const p=[]; if(c.min_amount)p.push('≥'+c.min_amount); if(c.months_in)p.push('月数'+c.months_in.join('/')); if(c.first_paid)p.push('首付'); return p.join(' · ')||'无' }
function actionsText(as){ return (as||[]).map(a=>{
  if(a.type==='points')return '积分+'+a.value; if(a.type==='points_pct')return '积分'+(a.rate*100)+'%';
  if(a.type==='growth')return '成长+'+a.value; if(a.type==='extend_days')return '订阅+'+a.days+'天';
  if(a.type==='trial_days')return '试用+'+a.days+'天'; if(a.type==='coupon')return '发券('+(a.kind==='percent'?a.value+'%':'减'+a.value)+')';
  return a.type }).join(', ') }
async function load(){ try{ rows.value=(await api.campaigns()).campaigns||[] }catch(e){ ElMessage.error('加载失败(需 活动引擎 权限)') } }
async function loadMeta(){ try{ meta.value=await api.campaignMeta() }catch(e){} }
function blank(){ return {id:0,name:'',category:'retention',event:'paid',cond:{},actions:[],per_user_limit:1,total_limit:0,priority:1,valid_until:'',enabled:true} }
function syncCondIn(c){ condMinAmount.value=c.min_amount||0; condMonths.value=(c.months_in||[]).map(Number); condFirstPaid.value=!!c.first_paid }
function buildCond(){ const c={}; if(condMinAmount.value>0)c.min_amount=condMinAmount.value; if(condMonths.value.length)c.months_in=condMonths.value.slice(); if(condFirstPaid.value)c.first_paid=true; return c }
function newCamp(){ cur.value=blank(); syncCondIn({}); editing.value=false; dlg.value=true }
function fromTemplate(t){ cur.value={...blank(),name:t.name,category:t.category,event:t.event,cond:{...(t.cond||{})},actions:JSON.parse(JSON.stringify(t.actions||[]))}; syncCondIn(cur.value.cond); editing.value=false; dlg.value=true }
function editCamp(r){ cur.value={...r,valid_until:r.valid_until?String(r.valid_until).slice(0,19):'',actions:JSON.parse(JSON.stringify(r.actions||[]))}; syncCondIn(r.cond||{}); editing.value=true; dlg.value=true }
function addAction(){ cur.value.actions.push({type:'points',value:100}) }
function onActType(a){ if(a.type==='coupon'){ a.kind=a.kind||'percent'; a.applies_to=a.applies_to||'any'; a.valid_days=a.valid_days||7; a.value=a.value||10; a.name=a.name||'活动券' } }
async function save(){
  if(!cur.value.name) return ElMessage.warning('活动名不能为空')
  if(!cur.value.actions.length) return ElMessage.warning('至少加一个动作')
  const body={...cur.value,cond:buildCond()}
  try{ await api.campaignSave(body); ElMessage.success('已保存'); dlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delCamp(id){
  try{ await ElMessageBox.confirm('删除该活动?发放历史保留。','确认删除',{type:'warning'}) }catch(e){ return }
  try{ await api.campaignDel(id); ElMessage.success('已删除'); load() }catch(e){ ElMessage.error('删除失败') }
}
async function openGrants(id){ try{ grants.value=(await api.campaignGrants(id,100)).grants||[]; gdlg.value=true }catch(e){ ElMessage.error('记录加载失败') } }
onMounted(()=>{ loadMeta(); load(); loadRecall() })
</script>
<style scoped>.ch{display:inline-flex;align-items:center;gap:5px}.hint{font-size:11px;color:#909399}</style>
