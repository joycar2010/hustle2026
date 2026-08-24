<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span>内购商品配置 · 三类可自定义</span>
        <span style="float:right"><el-button size="small" type="primary" @click="newProd">+ 新增商品</el-button>
          <el-button size="small" @click="load">刷新</el-button></span>
      </template>
      <el-table :data="products" size="small" border>
        <el-table-column prop="key" label="商品键" width="130"/>
        <el-table-column label="分类" width="100"><template #default="s">{{catName(s.row.category)}}</template></el-table-column>
        <el-table-column prop="name" label="名称"/>
        <el-table-column prop="price" label="价格" width="90"><template #default="s">{{s.row.price}} {{s.row.unit}}</template></el-table-column>
        <el-table-column label="时长" width="80"><template #default="s">{{s.row.duration_days?s.row.duration_days+'天':'永久'}}</template></el-table-column>
        <el-table-column label="授予权益"><template #default="s"><span style="font-size:12px">{{grantsToText(s.row.grants)}}</span></template></el-table-column>
        <el-table-column label="操作" width="150"><template #default="s">
          <el-button size="small" @click="editProd(s.row)">编辑</el-button>
          <el-button size="small" type="danger" @click="delProd(s.row.key)">下架</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header><span>用户权益授予 · 内购/手工/赠送</span></template>
      <el-form inline>
        <el-form-item label="用户"><UserSelect v-model="g.username" width="150px"/></el-form-item>
        <el-form-item label="按商品"><el-select v-model="g.product_key" size="small" clearable style="width:170px" placeholder="选商品(自动授权益)" @change="onPickProduct">
          <el-option v-for="p in products" :key="p.key" :label="p.name" :value="p.key"/></el-select></el-form-item>
        <el-form-item label="或单项权益"><el-select v-model="g.feature_key" size="small" clearable filterable style="width:150px" placeholder="选权益项" :disabled="!!g.product_key">
          <el-option v-for="f in feats" :key="f.key" :label="f.name" :value="f.key"/></el-select></el-form-item>
        <el-form-item label="值" v-if="g.feature_key && !g.product_key">
          <el-switch v-if="featType(g.feature_key)==='bool'" v-model="g.boolVal"/>
          <el-input-number v-else v-model="g.numVal" size="small" :min="0" style="width:100px"/>
        </el-form-item>
        <el-form-item label="来源"><el-select v-model="g.source" size="small" style="width:100px">
          <el-option v-for="(n,k) in GRANT_SOURCE" :key="k" :label="n" :value="k"/></el-select></el-form-item>
        <el-form-item label="天数"><el-input-number v-model="g.duration_days" size="small" :min="0" style="width:110px"/> <span style="color:#909399;font-size:11px">0=永久</span></el-form-item>
        <el-form-item><el-button type="primary" size="small" @click="doGrant">授予</el-button></el-form-item>
      </el-form>
      <el-divider/>
      <el-form inline><el-form-item label="查权益(用户)"><UserSelect v-model="qUser" width="150px"/></el-form-item>
        <el-form-item><el-button size="small" @click="loadEnt">查询</el-button></el-form-item></el-form>
      <el-descriptions v-if="ent" :column="3" border size="small">
        <el-descriptions-item v-for="(v,k) in ent" :key="k" :label="featName(k)">{{entValText(k,v)}}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top:12px">
      <template #header><span>权益项目录 · 可自定义(商品与授予据此渲染)</span>
        <span style="float:right"><el-button size="small" type="primary" @click="newFeat">+ 新增权益项</el-button></span></template>
      <el-table :data="feats" size="small" border>
        <el-table-column prop="key" label="权益键" width="140"/>
        <el-table-column prop="name" label="中文名"/>
        <el-table-column label="类型" width="80"><template #default="s"><el-tag size="small">{{s.row.type==='num'?'数值':'开关'}}</el-tag></template></el-table-column>
        <el-table-column prop="hint" label="说明"/>
        <el-table-column label="操作" width="140"><template #default="s">
          <el-button size="small" @click="editFeat(s.row)">编辑</el-button>
          <el-button size="small" type="danger" @click="delFeat(s.row.key)">下架</el-button>
        </template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:6px">新增权益项后,商品编辑与用户授予处自动出现该项;纯开关/数值类前端门控即生效,无需改代码。</div>
    </el-card>

    <el-dialog :close-on-click-modal="false" v-model="fdlg" :title="fediting?'编辑权益项':'新增权益项'" width="440">
      <el-form label-width="92">
        <el-form-item label="权益键"><el-input v-model="fcur.key" :disabled="fediting" placeholder="如 max_pairs / vip_signal"/></el-form-item>
        <el-form-item label="中文名"><el-input v-model="fcur.name"/></el-form-item>
        <el-form-item label="类型"><el-select v-model="fcur.ftype"><el-option label="开关(bool)" value="bool"/><el-option label="数值(num)" value="num"/></el-select></el-form-item>
        <el-form-item label="默认值"><el-input v-model="fcur.default_value" placeholder="免费档默认: bool填 false, 数值填数"/></el-form-item>
        <el-form-item label="说明"><el-input v-model="fcur.hint"/></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="fcur.sort" :min="0"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="fdlg=false">取消</el-button><el-button type="primary" @click="saveFeat">保存</el-button></template>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="cur.key?'编辑商品':'新增商品'" width="460">
      <el-form label-width="92">
        <el-form-item label="商品键"><el-input v-model="cur.key" :disabled="editing" placeholder="如 pairs_3 / auto_loop_pro"/></el-form-item>
        <el-form-item label="分类"><el-select v-model="cur.category"><el-option v-for="c in categories" :key="c.key" :label="c.name" :value="c.key"/></el-select></el-form-item>
        <el-form-item label="名称"><el-input v-model="cur.name"/></el-form-item>
        <el-form-item label="说明"><el-input v-model="cur.descr"/></el-form-item>
        <el-form-item label="价格"><el-input-number v-model="cur.price" :step="1" :min="0"/> <el-input v-model="cur.unit" style="width:80px;margin-left:8px"/></el-form-item>
        <el-form-item label="时长(天)"><el-input-number v-model="cur.duration_days" :min="0"/> <span style="color:#909399;font-size:11px;margin-left:6px">0=永久</span></el-form-item>
        <el-form-item label="授予权益">
          <div style="width:100%">
            <div v-for="f in feats" :key="f.key" style="display:flex;align-items:center;gap:8px;padding:3px 0">
              <el-checkbox v-model="gm[f.key+'_on']" style="width:130px">{{f.name}}</el-checkbox>
              <el-input-number v-if="f.type==='num'&&gm[f.key+'_on']" v-model="gm[f.key]" :min="1" size="small" style="width:110px"/>
              <span style="color:#909399;font-size:11px">{{f.hint}}</span>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="saveProd">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { FEATURES, FEATURE_MAP, grantsToText, featName, entValText, mergeRuntimeFeatures, currentFeatures } from '../features'
import { GRANT_SOURCE } from '../dicts'
import UserSelect from '../components/UserSelect.vue'
const products=ref([]),categories=ref([]),dlg=ref(false),cur=ref({}),editing=ref(false)
const feats=ref(FEATURES.slice())   // 动态权益目录(/iap/features), 回落静态
async function loadFeatures(){ try{ const list=(await api.iapFeatures()).features||[]; if(list.length){ mergeRuntimeFeatures(list); feats.value=currentFeatures() } }catch(e){} }
// 权益目录管理
const fdlg=ref(false), fcur=ref({}), fediting=ref(false)
function newFeat(){ fcur.value={key:'',name:'',ftype:'bool',hint:'',default_value:'false',sort:(feats.value.length+1),enabled:true}; fediting.value=false; fdlg.value=true }
function editFeat(f){ fcur.value={key:f.key,name:f.name,ftype:f.type==='num'?'num':'bool',hint:f.hint||'',default_value:(f.type==='num'?'1':'false'),sort:f.sort||0,enabled:true}; fediting.value=true; fdlg.value=true }
async function saveFeat(){
  if(!fcur.value.key||!fcur.value.name) return ElMessage.warning('key 与名称必填')
  try{ await api.iapSaveFeature(fcur.value); ElMessage.success('已保存'); fdlg.value=false; await loadFeatures() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delFeat(key){
  try{ await ElMessageBox.confirm('下架权益项 '+key+'?(已授予用户不受影响,仅目录不再可选)','确认',{type:'warning'}) }catch(e){ return }
  try{ await api.iapDelFeature(key); ElMessage.success('已下架'); await loadFeatures() }
  catch(e){ ElMessage.error('失败') }
}
const g=ref({username:'hedge_pro',product_key:'',feature_key:'',boolVal:true,numVal:1,source:'manual',duration_days:0})
function featType(k){ return FEATURE_MAP[k]?.type || 'bool' }
function onPickProduct(){ if(g.value.product_key){ g.value.feature_key='' } }
const gm=ref({})  // 权益勾选模型: {auto_loop_on:bool, max_pairs_on:bool, max_pairs:num,...}
function gmFromGrants(grants){ const m={}; feats.value.forEach(f=>{ const v=grants&&grants[f.key]; m[f.key+'_on']=(v!=null&&v!==''&&String(v)!=='false'); if(f.type==='num')m[f.key]=(v!=null&&v!=='')?Number(v):1; }); return m }
function gmToGrants(){ const grants={}; feats.value.forEach(f=>{ if(!gm.value[f.key+'_on'])return; grants[f.key]=f.type==='bool'?'true':String(gm.value[f.key]||1); }); return grants }
const qUser=ref('hedge_pro'),ent=ref(null)
function catName(k){ const c=categories.value.find(x=>x.key===k); return c?c.name:k }
async function load(){ try{ const d=await api.iapCatalog(); categories.value=d.categories||[]; products.value=d.products||[] }catch(e){ ElMessage.error('加载失败') } }
function newProd(){ cur.value={key:'',category:(categories.value[0]||{}).key||'scale',name:'',descr:'',price:0,unit:'USDT',duration_days:0}; gm.value=gmFromGrants({}); editing.value=false; dlg.value=true }
function editProd(r){ cur.value={...r}; gm.value=gmFromGrants(r.grants||{}); editing.value=true; dlg.value=true }
async function saveProd(){
  const grants=gmToGrants()
  try{ await api.iapSaveProduct({...cur.value,grants}); ElMessage.success('已保存'); dlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败(检查 Admin Token)') }
}
async function delProd(key){ try{ await api.iapDelProduct(key); ElMessage.success('已下架'); load() }catch(e){ ElMessage.error('失败') } }
async function doGrant(){
  const body={ username:g.value.username, source:g.value.source, duration_days:g.value.duration_days }
  if(g.value.product_key){ body.product_key=g.value.product_key }
  else if(g.value.feature_key){
    body.feature_key=g.value.feature_key
    body.value = featType(g.value.feature_key)==='bool' ? (g.value.boolVal?'true':'false') : String(g.value.numVal||0)
  } else { return ElMessage.warning('请选商品或单项权益') }
  try{ const r=await api.grant(body); ElMessage.success('已授予:'+grantsToText(r.granted||{})); if(qUser.value===g.value.username)loadEnt() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'授予失败') }
}
async function loadEnt(){ try{ ent.value=(await api.entitlements(qUser.value)).entitlements }catch(e){ ElMessage.error('查询失败') } }
onMounted(()=>{ load(); loadFeatures(); loadEnt() })
</script>
