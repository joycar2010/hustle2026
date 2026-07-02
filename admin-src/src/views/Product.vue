<template>
  <div>
    <el-tabs v-model="tab" type="border-card">
      <!-- 币产品交易分析(已平仓获利) -->
      <el-tab-pane name="symbol">
        <template #label><span class="tl"><el-icon><PieChart/></el-icon> 币产品交易分析</span></template>
        <div style="margin-bottom:12px">
          <el-select v-model="days" size="small" style="width:110px" @change="load">
            <el-option :value="7" label="近7天"/><el-option :value="30" label="近30天"/><el-option :value="90" label="近90天"/></el-select>
          <el-button size="small" @click="load" style="margin-left:8px">刷新</el-button>
          <el-button size="small" type="primary" plain @click="exportPdf('symbol')" style="margin-left:8px"><el-icon><Printer/></el-icon> 导出PDF</el-button>
        </div>
        <div id="print-symbol">
          <h3 class="rpt-title">币产品交易分析 · 跨用户(近{{days}}天)</h3>
          <el-table :data="symbols" size="small" border>
            <el-table-column prop="symbol" label="币产品" width="120"/>
            <el-table-column label="活跃用户" width="110"><template #default="s">
              <el-button link type="primary" @click="drill(s.row)">{{s.row.users}} <el-icon style="margin-left:2px"><ArrowRightBold/></el-icon></el-button></template></el-table-column>
            <el-table-column prop="deals" label="成交笔数" width="90"/>
            <el-table-column prop="volume" label="成交量(手)" width="110"/>
            <el-table-column label="净盈亏" width="100"><template #default="s"><span :class="s.row.net_profit>=0?'up':'down'">{{s.row.net_profit}}</span></template></el-table-column>
            <el-table-column prop="fees" label="手续费" width="90"/>
            <el-table-column prop="swap" label="过夜费" width="90"/>
            <el-table-column label="胜率" width="90"><template #default="s">{{s.row.win_rate==null?'—':s.row.win_rate+'%'}}</template></el-table-column>
          </el-table>
          <div v-if="!symbols.length" style="text-align:center;color:#909399;padding:18px">暂无成交数据</div>
        </div>
        <div style="color:#909399;font-size:12px;margin-top:8px">点「活跃用户」列可下钻查看该产品下每个用户的单独交易数据。</div>
      </el-tab-pane>

      <!-- AI套利分析成功数据 -->
      <el-tab-pane name="arb">
        <template #label><span class="tl"><el-icon><MagicStick/></el-icon> AI套利分析</span></template>
        <div style="margin-bottom:12px">
          <el-select v-model="days" size="small" style="width:110px" @change="load">
            <el-option :value="7" label="近7天"/><el-option :value="30" label="近30天"/><el-option :value="90" label="近90天"/></el-select>
          <el-button size="small" @click="load" style="margin-left:8px">刷新</el-button>
          <el-button size="small" type="primary" plain @click="exportPdf('arb')" style="margin-left:8px"><el-icon><Printer/></el-icon> 导出PDF</el-button>
        </div>
        <div id="print-arb">
          <h3 class="rpt-title">AI 套利分析成功数据统计 · 全用户(近{{days}}天)</h3>
          <el-row :gutter="12" v-if="arb" style="margin-bottom:12px">
            <el-col :span="4"><el-card class="stat-card"><div class="l">扫描次数</div><div class="v">{{arb.overview.scans}}</div></el-card></el-col>
            <el-col :span="4"><el-card class="stat-card"><div class="l">命中次数</div><div class="v up">{{arb.overview.hits}}</div></el-card></el-col>
            <el-col :span="4"><el-card class="stat-card"><div class="l">命中率</div><div class="v">{{arb.overview.hit_rate}}%</div></el-card></el-col>
            <el-col :span="4"><el-card class="stat-card"><div class="l">使用用户</div><div class="v">{{arb.overview.users}}</div></el-card></el-col>
            <el-col :span="4"><el-card class="stat-card"><div class="l">平均最高分</div><div class="v">{{arb.overview.avg_top}}</div></el-card></el-col>
            <el-col :span="4"><el-card class="stat-card"><div class="l">累计可套利</div><div class="v">{{arb.overview.total_reachable}}</div></el-card></el-col>
          </el-row>
          <el-table :data="arb?arb.users:[]" size="small" border>
            <el-table-column prop="username" label="用户" width="150"/>
            <el-table-column prop="scans" label="扫描次数" width="100"/>
            <el-table-column label="命中次数" width="100"><template #default="s"><span class="up">{{s.row.hits}}</span></template></el-table-column>
            <el-table-column label="命中率" width="100"><template #default="s">{{s.row.hit_rate}}%</template></el-table-column>
            <el-table-column prop="best_score" label="最高分" width="90"/>
            <el-table-column prop="avg_score" label="平均分" width="90"/>
            <el-table-column label="最近使用"><template #default="s">{{(s.row.last_scan||'').replace('T',' ').slice(0,16)}}</template></el-table-column>
          </el-table>
          <div v-if="arb&&!arb.users.length" style="text-align:center;color:#909399;padding:18px">暂无 AI 套利分析使用记录(用户在控制台使用后累积)</div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="'产品下钻 — '+drillSymbol+' · 单用户(近'+days+'天)'" width="720">
      <el-table :data="userRows" size="small" border max-height="460" v-loading="drilling">
        <el-table-column prop="username" label="用户" width="150"/>
        <el-table-column prop="deals" label="成交笔数" width="90"/>
        <el-table-column prop="volume" label="成交量(手)" width="110"/>
        <el-table-column label="净盈亏" width="100"><template #default="s"><span :class="s.row.net_profit>=0?'up':'down'">{{s.row.net_profit}}</span></template></el-table-column>
        <el-table-column prop="fees" label="手续费" width="90"/>
        <el-table-column prop="swap" label="过夜费" width="90"/>
        <el-table-column label="胜率" width="90"><template #default="s">{{s.row.win_rate==null?'—':s.row.win_rate+'%'}}</template></el-table-column>
      </el-table>
      <div v-if="!drilling&&!userRows.length" style="text-align:center;color:#909399;padding:18px">该产品暂无用户成交</div>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const tab=ref('symbol'),days=ref(30),symbols=ref([]),arb=ref(null)
const dlg=ref(false),drillSymbol=ref(''),userRows=ref([]),drilling=ref(false)
async function load(){
  try{ symbols.value=(await api.biSymbols(days.value)).symbols||[] }catch(e){ ElMessage.error('加载失败') }
  try{ arb.value=await api.biArbStats(days.value) }catch(e){}
}
async function drill(row){
  drillSymbol.value=row.symbol; dlg.value=true; drilling.value=true; userRows.value=[]
  try{ userRows.value=(await api.biSymbolUsers(row.symbol,days.value)).users||[] }
  catch(e){ ElMessage.error('下钻加载失败') } finally{ drilling.value=false }
}
// PDF 导出: 打开只含报表区的打印窗口, 浏览器"保存为 PDF"(零服务端依赖, 中文完美)
function exportPdf(which){
  const el=document.getElementById('print-'+which); if(!el){ return }
  const w=window.open('','_blank','width=900,height=700'); if(!w){ ElMessage.warning('请允许弹窗以导出PDF'); return }
  const title = which==='arb'?'AI套利分析统计':'币产品交易分析'
  w.document.write('<html><head><meta charset="utf-8"><title>'+title+' - Quant Hedge</title>'+
    '<style>body{font-family:"Microsoft YaHei",sans-serif;padding:24px;color:#1a2033}'+
    'h3{color:#08113A}table{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px}'+
    'th,td{border:1px solid #dde2ee;padding:6px 8px;text-align:left}th{background:#eaf0fa}'+
    '.up{color:#1aa86a}.down{color:#e0683a}.rpt-hd{color:#909399;font-size:12px;margin-bottom:8px}'+
    '.el-card,.stat-card{display:inline-block;border:1px solid #dde2ee;border-radius:8px;padding:10px 16px;margin:4px}'+
    '</style></head><body>'+
    '<div class="rpt-hd">Quant Hedge · 导出时间 '+new Date().toLocaleString('zh-CN')+' · 近'+days.value+'天</div>'+
    el.innerHTML+'</body></html>')
  w.document.close(); setTimeout(()=>{ w.print(); }, 300)
}
onMounted(load)
</script>
<style scoped>
.tl{display:inline-flex;align-items:center;gap:5px}
.rpt-title{font-size:15px;color:#08113A;margin:0 0 8px}
.stat-card .v{font-size:22px;font-weight:700;font-family:"Roboto Mono",monospace}
.stat-card .l{color:#46506e;font-size:12px}
.up{color:var(--el-color-success)} .down{color:var(--el-color-danger)}
</style>
