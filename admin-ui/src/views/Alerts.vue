<template>
  <div class="card"><h3>告警历史</h3>
    <el-table :data="rows" size="small" empty-text="暂无告警">
      <el-table-column label="时间" width="150"><template #default="s">{{ shortTs(s.row.ts) }}</template></el-table-column>
      <el-table-column label="级别" width="80"><template #default="s"><el-tag size="small" :type="s.row.level === 'fatal' ? 'danger' : (s.row.level === 'warn' ? 'warning' : 'info')">{{ s.row.level }}</el-tag></template></el-table-column>
      <el-table-column prop="title" label="标题" width="220" /><el-table-column prop="content" label="内容" />
    </el-table></div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import { shortTs } from '../lib'
const rows = ref([])
onMounted(async () => { try { rows.value = (await api.alerts(120)).alerts } catch (e) {} })
</script>
