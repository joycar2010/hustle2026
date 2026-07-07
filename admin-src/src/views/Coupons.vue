<template>
  <div>
    <el-card>
      <template #header><span class="ch"><el-icon><Ticket/></el-icon> 折扣券管理</span>
        <span style="float:right"><el-button size="small" type="primary" @click="newCoupon">+ 新增券</el-button>
          <el-button size="small" @click="load">刷新</el-button></span></template>
      <el-table :data="rows" size="small" border>
        <el-table-column prop="code" label="券码" width="130"/>
        <el-table-column prop="name" label="名称" width="130"/>
        <el-table-column label="折扣" width="110"><template #default="s">
          {{ s.row.kind==='percent' ? (s.row.value+'% 折') : ('立减 '+s.row.value) }}
          <div v-if="s.row.max_discount>0" style="font-size:10px;color:#909399">上限{{s.row.max_discount}}</div></template></el-table-column>
        <el-table-column label="适用" width="90"><template #default="s">{{ {any:'全部',iap:'内购',subscription:'订阅'}[s.row.applies_to] }}</template></el-table-column>
        <el-table-column label="门槛" width="80"><template #default="s">{{s.row.min_amount>0?('≥'+s.row.min_amount):'—'}}</template></el-table-column>
        <el-table-column label="用量" width="100"><template #default="s">{{s.row.used_qty}}/{{s.row.total_qty>0?s.row.total_qty:'∞'}} · 人{{s.row.per_user_limit}}</template></el-table-column>
        <el-table-column label="专属" width="100"><template #default="s">{{s.row.target_username||'通用'}}</template></el-table-column>
        <el-table-column label="有效期" width="150"><template #default="s">{{fmt(s.row.valid_until)}}</template></el-table-column>
        <el-table-column label="状态" width="60"><template #default="s"><el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'停用'}}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="160" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click="editCoupon(s.row)">编辑</el-button>
          <el-button size="small" link type="primary" @click="openRed(s.row.code)">核销</el-button>
          <el-button size="small" link type="danger" @click="delCoupon(s.row.code)">删</el-button></template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:6px">折扣券服务端权威计算, 下单时校验(有效期/适用/门槛/专属/余量/逐用户次数), 与积分/佣金链路解耦;佣金按券后实付计。</div>
    </el-card>

    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="editing?'编辑券':'新增券'" width="520">
      <el-form label-width="100">
        <el-form-item label="券码"><el-input v-model="cur.code" :disabled="editing" placeholder="唯一,如 NEW9/RECALL7"/></el-form-item>
        <el-form-item label="名称"><el-input v-model="cur.name" placeholder="如 新人首单9折"/></el-form-item>
        <el-form-item label="折扣类型">
          <el-radio-group v-model="cur.kind">
            <el-radio value="percent">百分比折扣</el-radio><el-radio value="fixed">立减固定额</el-radio></el-radio-group></el-form-item>
        <el-form-item :label="cur.kind==='percent'?'折扣(%)':'立减(USDT)'">
          <el-input-number v-model="cur.value" :min="0" :max="cur.kind==='percent'?100:100000" :step="cur.kind==='percent'?5:10"/>
          <span v-if="cur.kind==='percent'" style="color:#909399;font-size:11px;margin-left:6px">如 10 = 打9折的"减10%"; 即减掉10%</span></el-form-item>
        <el-form-item label="折扣上限"><el-input-number v-model="cur.max_discount" :min="0"/> <span style="color:#909399;font-size:11px">0=不限(仅百分比券常用)</span></el-form-item>
        <el-form-item label="适用类型"><el-select v-model="cur.applies_to" style="width:160px">
          <el-option value="any" label="全部(内购+订阅)"/><el-option value="subscription" label="仅订阅"/><el-option value="iap" label="仅内购"/></el-select></el-form-item>
        <el-form-item label="最低金额"><el-input-number v-model="cur.min_amount" :min="0"/></el-form-item>
        <el-form-item label="总发放量"><el-input-number v-model="cur.total_qty" :min="0"/> <span style="color:#909399;font-size:11px">0=不限量</span></el-form-item>
        <el-form-item label="每人限用"><el-input-number v-model="cur.per_user_limit" :min="0"/> <span style="color:#909399;font-size:11px">0=不限次</span></el-form-item>
        <el-form-item label="专属用户"><el-input v-model="cur.target_username" placeholder="留空=通用活动券;填用户名=仅该用户可用"/></el-form-item>
        <el-form-item label="有效期至"><el-date-picker v-model="cur.valid_until" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="留空=长期" style="width:220px"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="cur.enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="rdlg" :title="'核销记录 · '+redCode" width="560">
      <el-table :data="reds" size="small" border max-height="440">
        <el-table-column prop="created_at" label="时间" width="180"/>
        <el-table-column prop="username" label="用户"/>
        <el-table-column prop="order_id" label="订单" width="90"/>
        <el-table-column label="折扣额" width="90"><template #default="s">{{s.row.discount}}</template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const rows=ref([]),dlg=ref(false),cur=ref({}),editing=ref(false)
const rdlg=ref(false),reds=ref([]),redCode=ref('')
function fmt(t){ return t?String(t).slice(0,16).replace('T',' '):'长期' }
async function load(){ try{ rows.value=(await api.coupons()).coupons||[] }catch(e){ ElMessage.error('加载失败(需 折扣券 权限)') } }
function newCoupon(){ cur.value={code:'',name:'',kind:'percent',value:10,max_discount:0,applies_to:'any',min_amount:0,total_qty:0,per_user_limit:1,target_username:'',valid_until:'',enabled:true}; editing.value=false; dlg.value=true }
function editCoupon(r){ cur.value={...r,valid_until:r.valid_until?String(r.valid_until).slice(0,19):''}; editing.value=true; dlg.value=true }
async function save(){
  if(!cur.value.code) return ElMessage.warning('券码不能为空')
  try{ await api.couponSave(cur.value); ElMessage.success('已保存'); dlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delCoupon(code){
  try{ await ElMessageBox.confirm('删除券「'+code+'」?核销历史保留。','确认删除',{type:'warning'}) }catch(e){ return }
  try{ await api.couponDel(code); ElMessage.success('已删除'); load() }catch(e){ ElMessage.error('删除失败') }
}
async function openRed(code){ redCode.value=code; try{ reds.value=(await api.couponRedemptions(code,100)).redemptions||[]; rdlg.value=true }catch(e){ ElMessage.error('核销记录加载失败') } }
onMounted(load)
</script>
<style scoped>.ch{display:inline-flex;align-items:center;gap:5px}</style>
