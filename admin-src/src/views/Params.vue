<template>
  <el-card><template #header><span>参数下发 · 模板管理</span>
    <span style="float:right"><el-input v-model="user" size="small" style="width:130px;margin-right:8px"/><el-button size="small" @click="load">{{t('refresh')}}</el-button></span></template>
    <el-table :data="list" size="small" border>
      <el-table-column prop="symbol" label="品种"/>
      <el-table-column prop="entry_spread" label="入场点差"/>
      <el-table-column prop="tp_points" label="止盈点"/>
      <el-table-column prop="sl_points" label="止损点"/>
      <el-table-column prop="ladders" label="阶梯数"/>
      <el-table-column prop="hold_secs" label="持仓秒"/>
      <el-table-column label="周末保护"><template #default="s"><el-tag size="small" :type="s.row.weekend_guard?'success':'info'">{{s.row.weekend_guard?'开':'关'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="120"><template #default="s"><el-button size="small" type="primary" @click="edit(s.row)">编辑下发</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="dlg" title="参数编辑（下发后引擎热重载）" width="420">
      <el-form label-width="90">
        <el-form-item label="入场点差"><el-input-number v-model="cur.entry_spread" :step="0.01" :precision="2"/></el-form-item>
        <el-form-item label="止盈点"><el-input-number v-model="cur.tp_points" :step="0.5"/></el-form-item>
        <el-form-item label="止损点"><el-input-number v-model="cur.sl_points" :step="1"/></el-form-item>
        <el-form-item label="阶梯数"><el-input-number v-model="cur.ladders" :min="1" :max="10"/></el-form-item>
        <el-form-item label="持仓秒"><el-input-number v-model="cur.hold_secs" :step="30"/></el-form-item>
        <el-form-item label="周末保护"><el-switch v-model="cur.weekend_guard"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="save">保存并热重载</el-button></template>
    </el-dialog>
  </el-card>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const { t }=useI18n()
const user=ref('hedge_pro'),list=ref([]),dlg=ref(false),cur=ref({})
async function load(){ try{ list.value=(await api.params(user.value)).params||[] }catch(e){} }
function edit(r){ cur.value={...r}; dlg.value=true }
function save(){ dlg.value=false; ElMessage.success('参数已下发（演示：写端点待接 require_admin）') }
onMounted(load)
</script>
