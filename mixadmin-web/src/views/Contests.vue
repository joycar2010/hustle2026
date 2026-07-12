<template>
  <div>
    <el-card>
      <template #header><span class="ch"><el-icon><Trophy/></el-icon> 周期冲榜赛(月度/季度达标赛)</span>
        <span style="float:right"><el-button size="small" type="primary" @click="newC">+ 新建冲榜赛</el-button>
          <el-button size="small" @click="load">刷新</el-button></span></template>
      <el-table :data="rows" size="small" border>
        <el-table-column prop="name" label="活动名" width="150"/>
        <el-table-column label="对象" width="80"><template #default="s">{{s.row.kind==='staff'?'员工':'代理'}}</template></el-table-column>
        <el-table-column label="周期" width="70"><template #default="s">{{s.row.period==='month'?'月度':'季度'}}</template></el-table-column>
        <el-table-column label="排名指标" width="110"><template #default="s">{{ METRIC[s.row.metric]||s.row.metric }}</template></el-table-column>
        <el-table-column label="取前" width="70"><template #default="s">Top{{s.row.top_n}}</template></el-table-column>
        <el-table-column label="奖励分档"><template #default="s"><span style="font-size:12px">{{ rewardsText(s.row.rewards) }}</span></template></el-table-column>
        <el-table-column label="已结算周期" width="110"><template #default="s">{{s.row.last_settled_period||'—'}}</template></el-table-column>
        <el-table-column label="状态" width="60"><template #default="s"><el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'停用'}}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="220" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click="editC(s.row)">编辑</el-button>
          <el-button size="small" link type="warning" @click="settle(s.row)">结算上期</el-button>
          <el-button size="small" link type="primary" @click="openResults(s.row.id)">榜单</el-button>
          <el-button size="small" link type="danger" @click="delC(s.row.id)">删</el-button></template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:6px">周期结束后每小时自动检查并结算上一周期(last_settled_period 防重);也可手动结算。员工奖励用绩效积分,代理奖励发运营用户积分。</div>
    </el-card>

    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="editing?'编辑冲榜赛':'新建冲榜赛'" width="600">
      <el-form label-width="90">
        <el-form-item label="活动名"><el-input v-model="cur.name" placeholder="如 员工月度获客赛"/></el-form-item>
        <el-form-item label="对象"><el-radio-group v-model="cur.kind" @change="onKind"><el-radio value="staff">员工</el-radio><el-radio value="agent">代理</el-radio></el-radio-group></el-form-item>
        <el-form-item label="统计周期"><el-radio-group v-model="cur.period"><el-radio value="month">月度</el-radio><el-radio value="quarter">季度</el-radio></el-radio-group></el-form-item>
        <el-form-item label="排名指标"><el-select v-model="cur.metric" style="width:180px">
          <el-option v-for="m in metricOpts" :key="m" :value="m" :label="METRIC[m]"/></el-select></el-form-item>
        <el-form-item label="取前N名"><el-input-number v-model="cur.top_n" :min="1" :max="100"/></el-form-item>
        <el-form-item label="奖励分档">
          <div style="width:100%">
            <div v-for="(rw,i) in cur.rewards" :key="i" style="display:flex;gap:6px;align-items:center;margin-bottom:6px;background:#f5f7fa;padding:6px;border-radius:4px">
              <span class="hint">第</span><el-input-number v-model="rw.rank_from" :min="1" size="small" style="width:90px"/>
              <span class="hint">至</span><el-input-number v-model="rw.rank_to" :min="1" size="small" style="width:90px"/><span class="hint">名</span>
              <el-select v-model="rw.type" size="small" style="width:130px">
                <el-option v-if="cur.kind==='staff'" value="perf" label="绩效积分"/>
                <el-option value="points" label="积分(代理owner)"/></el-select>
              <el-input-number v-model="rw.value" :min="0" size="small" style="width:120px"/>
              <el-button size="small" link type="danger" @click="cur.rewards.splice(i,1)">删</el-button>
            </div>
            <el-button size="small" @click="addReward">+ 加分档</el-button>
          </div>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="cur.enabled"/></el-form-item>
        <el-form-item label="实时预览">
          <el-button size="small" @click="preview">预览上一周期排名</el-button>
          <div v-if="prev.length" style="margin-top:6px;max-height:140px;overflow:auto;width:100%;font-size:12px">
            <div v-for="p in prev" :key="p.rank" style="display:flex;justify-content:space-between;border-bottom:1px solid #eee;padding:2px 0">
              <span>#{{p.rank}} {{p.name||p.code}}</span><span style="color:#2E8BD6">{{p.value}}</span></div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="rdlg" :title="'榜单 · '+resPeriod" width="560">
      <el-table :data="results" size="small" border max-height="440">
        <el-table-column prop="rank" label="名次" width="70"/>
        <el-table-column label="对象"><template #default="s">{{s.row.name||s.row.code}}</template></el-table-column>
        <el-table-column prop="metric_value" label="成绩" width="100"/>
        <el-table-column label="奖励" width="140"><template #default="s">{{s.row.reward_type?(s.row.reward_type+' '+s.row.reward_value):'—'}}<span v-if="s.row.reward_to" style="color:#909399"> →{{s.row.reward_to}}</span></template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const METRIC={paid_users:'付费用户数',revenue:'营收(USDT)',trials:'试用数',new_users:'新增注册'}
const rows=ref([]),dlg=ref(false),cur=ref({}),editing=ref(false),prev=ref([])
const rdlg=ref(false),results=ref([]),resPeriod=ref('')
const metricOpts=ref(['paid_users','revenue','trials','new_users'])
function onKind(k){ metricOpts.value = k==='agent' ? ['paid_users','revenue','new_users'] : ['paid_users','revenue','trials','new_users']; if(!metricOpts.value.includes(cur.value.metric))cur.value.metric='paid_users'
  // 代理默认奖励类型 points, 员工 perf
  cur.value.rewards.forEach(rw=>{ if(k==='agent'&&rw.type==='perf')rw.type='points' }) }
function rewardsText(rws){ return (rws||[]).map(rw=>('#'+rw.rank_from+(rw.rank_to>rw.rank_from?('-'+rw.rank_to):'')+' '+(rw.type==='perf'?'绩效':'积分')+rw.value)).join(', ')||'无' }
async function load(){ try{ rows.value=(await api.contests()).contests||[] }catch(e){ ElMessage.error('加载失败(需 冲榜赛 权限)') } }
function blank(){ return {id:0,name:'',kind:'staff',period:'month',metric:'paid_users',top_n:10,rewards:[{rank_from:1,rank_to:1,type:'perf',value:500}],enabled:true} }
function newC(){ cur.value=blank(); prev.value=[]; onKind('staff'); editing.value=false; dlg.value=true }
function editC(r){ cur.value={...r,rewards:JSON.parse(JSON.stringify(r.rewards||[]))}; prev.value=[]; onKind(r.kind); editing.value=true; dlg.value=true }
function addReward(){ cur.value.rewards.push({rank_from:1,rank_to:3,type:cur.value.kind==='staff'?'perf':'points',value:100}) }
async function save(){
  if(!cur.value.name) return ElMessage.warning('活动名不能为空')
  try{ await api.contestSave(cur.value); ElMessage.success('已保存'); dlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delC(id){
  try{ await ElMessageBox.confirm('删除该冲榜赛?榜单历史保留。','确认删除',{type:'warning'}) }catch(e){ return }
  try{ await api.contestDel(id); ElMessage.success('已删除'); load() }catch(e){ ElMessage.error('删除失败') }
}
async function settle(row){
  let force=false
  try{ await ElMessageBox.confirm('结算「'+row.name+'」的上一周期并发奖?','确认结算',{type:'warning'}) }
  catch(e){ return }
  try{ const r=await api.contestSettle(row.id,false); ElMessage.success('已结算 '+r.period+' · '+r.ranked+' 名上榜'); load() }
  catch(e){
    const d=e?.response?.data?.detail||''
    if(d.includes('已结算')){ try{ await ElMessageBox.confirm(d+' 是否强制重结?','重复结算',{type:'warning'}); const r=await api.contestSettle(row.id,true); ElMessage.success('已重结 '+r.period+' · '+r.ranked+' 名'); load() }catch(x){} }
    else ElMessage.error(d||'结算失败')
  }
}
async function preview(){
  try{ const r=await api.contestPreview(cur.value.kind,cur.value.metric,cur.value.period); prev.value=r.ranking||[]; if(!prev.value.length)ElMessage.info('上一周期('+r.period_key+')暂无成绩') }
  catch(e){ ElMessage.error('预览失败') }
}
async function openResults(id){ try{ const r=await api.contestResults(id); results.value=r.results||[]; resPeriod.value=r.period_key||'—'; rdlg.value=true }catch(e){ ElMessage.error('榜单加载失败') } }
onMounted(load)
</script>
<style scoped>.ch{display:inline-flex;align-items:center;gap:5px}.hint{font-size:12px;color:#909399}</style>
