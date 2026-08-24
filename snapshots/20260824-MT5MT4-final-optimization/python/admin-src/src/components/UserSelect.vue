<template>
  <el-select :model-value="modelValue" filterable remote clearable :remote-method="search" :loading="loading"
    size="small" :style="{width:width}" :placeholder="placeholder" @update:model-value="$emit('update:modelValue',$event)" @focus="onFocus">
    <el-option v-for="u in opts" :key="u.username" :value="u.username"
      :label="u.username + (u.nickname?(' ('+u.nickname+')'):'') + (u.status?(' · '+zh(USER_STATUS,u.status)):'')">
      <span>{{u.username}}<span v-if="u.nickname" style="color:#909399;font-size:11px;margin-left:4px">{{u.nickname}}</span></span>
      <span style="float:right;color:#909399;font-size:11px">{{zh(USER_STATUS,u.status)}}</span>
    </el-option>
  </el-select>
</template>
<script setup>
// 远程搜索用户选择器,复用 GET /admin/users。供 Trials 发放 / Leads 绑定用户复用。
import { ref } from 'vue'
import { api } from '../api'
import { zh, USER_STATUS } from '../dicts'
const props = defineProps({ modelValue:{type:String,default:''}, width:{type:String,default:'170px'}, placeholder:{type:String,default:'搜索用户名'} })
defineEmits(['update:modelValue'])
const opts=ref([]), loading=ref(false)
async function search(q){ loading.value=true; try{ opts.value=(await api.adminUsers(q||'')).users||[] }catch(e){} loading.value=false }
function onFocus(){ if(!opts.value.length) search('') }
</script>
