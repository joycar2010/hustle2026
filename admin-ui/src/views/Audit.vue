<template>
  <div class="card"><h3>操作审计</h3>
    <el-table :data="rows" size="small" empty-text="暂无操作">
      <el-table-column label="时间" width="150"><template #default="s">{{ shortTs(s.row.ts) }}</template></el-table-column>
      <el-table-column prop="operator" label="操作员" width="100" /><el-table-column prop="role" label="角色" width="120" />
      <el-table-column prop="action" label="动作" width="180" /><el-table-column prop="target" label="对象" width="150" /><el-table-column prop="result" label="结果" />
    </el-table></div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import { shortTs } from '../lib'
const rows = ref([])
onMounted(async () => { try { rows.value = (await api.audit(120)).audit } catch (e) { rows.value = [] } })
</script>
