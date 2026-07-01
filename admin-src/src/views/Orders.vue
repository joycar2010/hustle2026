<template>
  <div>
    <el-card style="margin-bottom:12px" body-style="padding:12px">
      <template #header><span>💳 收款配置 (TRC20)</span></template>
      <el-form inline>
        <el-form-item label="TRC20 收款地址"><el-input v-model="payAddr" size="small" style="width:340px" placeholder="Txxxxxxxxxxxx (用户端二维码/转账地址)"/></el-form-item>
        <el-form-item label="备注"><el-input v-model="payNote" size="small" style="width:180px" placeholder="选填,展示在支付页"/></el-form-item>
        <el-form-item><el-button type="primary" size="small" @click="savePay">保存</el-button></el-form-item>
      </el-form>
      <div style="color:#909399;font-size:11px">此地址下发到用户端支付页(充值/包月/内购链上支付共用),前端据此生成二维码。存服务端自管文件,不入库。</div>
    </el-card>

    <el-card style="margin-bottom:12px">
      <template #header><span>收入报表</span>
        <span style="float:right"><el-select v-model="days" size="small" style="width:110px" @change="load">
          <el-option :value="7" label="近7天"/><el-option :value="30" label="近30天"/><el-option :value="90" label="近90天"/></el-select>
          <el-button size="small" @click="load" style="margin-left:8px">刷新</el-button></span></template>
      <el-row :gutter="12" v-if="rev">
        <el-col :span="6"><el-card class="stat-card"><div class="l">区间总收入</div><div class="v up">{{rev.total_revenue}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">订单数</div><div class="v">{{rev.total_orders}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">待核订单</div><div class="v" :class="pendingCnt>0?'down':''">{{pendingCnt}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">差异订单</div><div class="v" :class="discCnt>0?'down':''">{{discCnt}}</div></el-card></el-col>
      </el-row>
    </el-card>

    <el-card style="margin-bottom:12px">
      <template #header><span>对账日报(应收/已确认/差异/未核)</span>
        <span style="float:right"><el-button size="small" @click="loadDaily">刷新</el-button>
          <el-button size="small" @click="exportDaily">导出CSV</el-button></span></template>
      <el-table :data="daily" size="small" border max-height="240">
        <el-table-column prop="day" label="日期" width="110"/>
        <el-table-column label="应收" width="100"><template #default="s">{{s.row.due}}</template></el-table-column>
        <el-table-column label="已确认额" width="100"><template #default="s"><span class="up">{{s.row.confirmed_amt}}</span></template></el-table-column>
        <el-table-column prop="orders" label="订单" width="70"/>
        <el-table-column label="未核" width="70"><template #default="s"><span :class="s.row.pending_cnt>0?'down':''">{{s.row.pending_cnt}}</span></template></el-table-column>
        <el-table-column prop="confirmed_cnt" label="已核" width="70"/>
        <el-table-column label="差异" width="70"><template #default="s"><span :class="s.row.discrepancy_cnt>0?'down':''">{{s.row.discrepancy_cnt}}</span></template></el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header><span>订单明细 · 财务核对</span>
        <span style="float:right;display:inline-flex;align-items:center;gap:6px">
          <el-select v-model="fStatus" size="small" clearable placeholder="核对状态" style="width:110px" @change="loadOrders">
            <el-option v-for="(n,k) in RECONCILE_STATUS" :key="k" :label="n" :value="k"/></el-select>
          <UserSelect v-model="fUser" width="150px" placeholder="按用户"/>
          <el-button size="small" @click="loadOrders">查询</el-button>
          <el-button size="small" type="success" :disabled="!sel.length" @click="batchConfirm">批量确认({{sel.length}})</el-button>
          <el-button size="small" @click="exportOrders">导出CSV</el-button></span></template>
      <el-table :data="orders" size="small" border max-height="460" @selection-change="v=>sel=v">
        <el-table-column type="selection" width="40" :selectable="r=>(r.reconcile_status||'pending')==='pending'"/>
        <el-table-column prop="id" label="#" width="56"/>
        <el-table-column prop="paid_at" label="时间" width="150"/>
        <el-table-column prop="username" label="用户" width="110"/>
        <el-table-column label="类型" width="70"><template #default="s">
          <el-tag size="small" :type="{recharge:'warning',subscription:'success',iap:'primary'}[s.row.kind]||'info'">{{ {iap:'内购',subscription:'包月',recharge:'充值'}[s.row.kind]||s.row.kind||'内购' }}</el-tag></template></el-table-column>
        <el-table-column label="商品"><template #default="s">{{s.row.product_name||s.row.product_key}}</template></el-table-column>
        <el-table-column label="应收" width="90"><template #default="s">{{s.row.amount}} {{s.row.unit}}</template></el-table-column>
        <el-table-column label="支付" width="90"><template #default="s">
          <el-tag size="small" :type="s.row.pay_method==='balance'?'success':'info'">{{s.row.pay_method==='balance'?'余额':'链上'}}</el-tag></template></el-table-column>
        <el-table-column label="TxID" width="120"><template #default="s"><span style="font-size:10px" :title="s.row.tx_hash">{{s.row.tx_hash?(s.row.tx_hash.slice(0,10)+'…'):'—'}}</span></template></el-table-column>
        <el-table-column label="实收" width="80"><template #default="s">{{s.row.received_amount!=null?s.row.received_amount:'—'}}</template></el-table-column>
        <el-table-column label="核对" width="80"><template #default="s">
          <el-tag size="small" :type="RECONCILE_TAG[s.row.reconcile_status||'pending']">{{zh(RECONCILE_STATUS,s.row.reconcile_status||'pending')}}</el-tag></template></el-table-column>
        <el-table-column prop="confirmed_by" label="核对人" width="100"><template #default="s">{{s.row.confirmed_by||'—'}}</template></el-table-column>
        <el-table-column label="差异/备注"><template #default="s"><span style="font-size:11px;color:#909399">{{s.row.discrepancy_reason||s.row.reconcile_note||''}}</span></template></el-table-column>
        <el-table-column label="操作" width="170" fixed="right"><template #default="s">
          <template v-if="(s.row.reconcile_status||'pending')==='pending'">
            <el-button size="small" link type="success" @click="doConfirm(s.row)">确认</el-button>
            <el-button size="small" link type="warning" @click="doDiscrepancy(s.row)">差异</el-button>
            <el-button size="small" link type="info" @click="doVoid(s.row)">作废</el-button>
          </template>
          <el-button v-else size="small" link @click="doReopen(s.row)">重开</el-button>
        </template></el-table-column>
      </el-table>
      <div v-if="!orders.length" style="text-align:center;color:#909399;padding:18px">暂无订单</div>
    </el-card>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { zh, RECONCILE_STATUS, RECONCILE_TAG } from '../dicts'
import UserSelect from '../components/UserSelect.vue'
const days=ref(30),rev=ref(null),orders=ref([]),fUser=ref(''),fStatus=ref(''),daily=ref([]),sel=ref([])
const payAddr=ref(''),payNote=ref('')
async function loadPay(){ try{ const p=await api.payConfigGet(); payAddr.value=p.trc20_address||''; payNote.value=p.note||'' }catch(e){} }
async function savePay(){ try{ await api.payConfigSave({trc20_address:payAddr.value,note:payNote.value}); ElMessage.success('收款配置已保存') }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
const pendingCnt=computed(()=>orders.value.filter(o=>(o.reconcile_status||'pending')==='pending').length)
const discCnt=computed(()=>orders.value.filter(o=>o.reconcile_status==='discrepancy').length)
async function load(){ try{ rev.value=await api.revenue(days.value); loadOrders(); loadDaily() }catch(e){ ElMessage.error('加载失败') } }
async function loadOrders(){ try{ orders.value=(await api.ordersFilter({days:90,username:fUser.value,reconcile_status:fStatus.value})).orders||[] }catch(e){} }
async function loadDaily(){ try{ daily.value=(await api.reconcileDaily(days.value)).by_day||[] }catch(e){} }
async function doConfirm(row){
  const txInfo = row.tx_hash ? ('转账哈希 TxID:\n'+row.tx_hash+'\n\n') : (row.pay_method==='balance'?'(余额支付,无链上哈希)\n\n':'(用户未填哈希)\n\n');
  try{ const {value}=await ElMessageBox.prompt(txInfo+'核对链上到账后确认。实收金额(默认=应收 '+row.amount+'):','确认收款',{inputValue:String(row.amount),inputPattern:/^\d+(\.\d+)?$/,inputErrorMessage:'请输入数字'})
    await api.orderReconcile({order_id:row.id,action:'confirm',received_amount:Number(value)}); ElMessage.success('已确认'); loadOrders(); loadDaily() }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'失败') }
}
async function doDiscrepancy(row){
  try{ const {value}=await ElMessageBox.prompt('差异原因:','标记差异',{inputPlaceholder:'如 金额不符/重复支付'})
    await api.orderReconcile({order_id:row.id,action:'mark_discrepancy',reason:value||'人工标记'}); ElMessage.success('已标记差异'); loadOrders(); loadDaily() }catch(e){ if(e!=='cancel')ElMessage.error('失败') }
}
async function doVoid(row){
  try{ await ElMessageBox.confirm('作废订单 #'+row.id+'?','确认',{type:'warning'}); await api.orderReconcile({order_id:row.id,action:'void'}); ElMessage.success('已作废'); loadOrders(); loadDaily() }catch(e){}
}
async function doReopen(row){
  try{ await api.orderReconcile({order_id:row.id,action:'reopen'}); ElMessage.success('已重开'); loadOrders(); loadDaily() }catch(e){ ElMessage.error('失败') }
}
async function batchConfirm(){
  try{ await ElMessageBox.confirm('批量确认 '+sel.value.length+' 笔(按应收=实收)?','确认',{type:'warning'})
    const r=await api.orderReconcileBatch({order_ids:sel.value.map(o=>o.id),action:'confirm'}); ElMessage.success('已确认 '+r.affected+' 笔'); loadOrders(); loadDaily() }catch(e){}
}
function toCSV(rows,cols){ const head=cols.map(c=>c[1]).join(','); const body=rows.map(r=>cols.map(c=>JSON.stringify(r[c[0]]??'')).join(',')).join('\n'); return head+'\n'+body }
function download(name,text){ const b=new Blob(['﻿'+text],{type:'text/csv;charset=utf-8'}); const a=document.createElement('a'); a.href=URL.createObjectURL(b); a.download=name; a.click() }
function exportOrders(){ download('orders.csv', toCSV(orders.value,[['id','#'],['paid_at','时间'],['username','用户'],['product_name','商品'],['amount','应收'],['received_amount','实收'],['reconcile_status','核对'],['confirmed_by','核对人'],['discrepancy_reason','差异']])) }
function exportDaily(){ download('reconcile_daily.csv', toCSV(daily.value,[['day','日期'],['due','应收'],['confirmed_amt','已确认额'],['orders','订单'],['pending_cnt','未核'],['confirmed_cnt','已核'],['discrepancy_cnt','差异']])) }
onMounted(()=>{ load(); loadPay() })
</script>
