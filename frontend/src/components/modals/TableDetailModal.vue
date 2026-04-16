<template>
  <div v-if="show" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click.self="close">
    <div class="bg-dark-200 rounded-lg p-6 w-full max-w-6xl max-h-[90vh] overflow-y-auto">
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-xl font-bold">表: {{ tableName }}</h3>
        <button @click="close" class="text-gray-400 hover:text-white">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="mb-4">
        <button @click="showAddForm = true" class="btn-primary">
          <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
          </svg>
          添加记录
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border-primary">
              <th v-for="col in columns" :key="col.name" class="text-left py-2 px-2">
                {{ col.name }}
                <span class="text-xs text-gray-500">({{ col.type }})</span>
              </th>
              <th class="text-left py-2 px-2">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in rows" :key="idx" class="border-b border-border-secondary hover:bg-dark-50">
              <td v-for="col in columns" :key="col.name" class="py-2 px-2">
                {{ formatValue(row[col.name]) }}
              </td>
              <td class="py-2 px-2">
                <button @click="editRecord(row)" class="text-primary hover:text-primary-hover mr-2">编辑</button>
                <button @click="deleteRecord(row)" class="text-danger hover:text-red-400">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="showAddForm || editingRecord" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-dark-200 rounded-lg p-6 w-full max-w-2xl">
          <h4 class="text-lg font-bold mb-4">{{ editingRecord ? '编辑记录' : '添加记录' }}</h4>
          <div class="space-y-3 max-h-96 overflow-y-auto">
            <div v-for="col in columns" :key="col.name">
              <label class="block text-sm font-medium mb-1">{{ col.name }} ({{ col.type }})</label>
              <input
                v-model="formData[col.name]"
                type="text"
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary text-sm"
              />
            </div>
          </div>
          <div class="flex justify-end space-x-3 mt-4">
            <button @click="cancelForm" class="btn-secondary">取消</button>
            <button @click="saveRecord" class="btn-primary">保存</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import api from '@/services/api'

const props = defineProps({
  show: Boolean,
  tableName: String
})

const emit = defineEmits(['close', 'refresh'])

const columns = ref([])
const rows = ref([])
const showAddForm = ref(false)
const editingRecord = ref(null)
const formData = ref({})

watch(() => props.show, async (newVal) => {
  if (newVal && props.tableName) {
    await loadTableData()
  }
})

async function loadTableData() {
  try {
    const response = await api.get(`/api/v1/system/database/table/${props.tableName}`)
    columns.value = response.data.columns
    rows.value = response.data.rows
  } catch (error) {
    console.error('Failed to load table data:', error)
    alert('加载表数据失败: ' + (error.response?.data?.detail || error.message))
  }
}

function formatValue(value) {
  if (value === null || value === undefined) return 'NULL'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value).substring(0, 50)
}

function editRecord(row) {
  editingRecord.value = row
  formData.value = { ...row }
}

async function deleteRecord(row) {
  if (!confirm('确定要删除此记录吗？')) return

  try {
    // Use primary key or first column as identifier
    const where = {}
    const firstCol = columns.value[0]?.name
    if (firstCol && row[firstCol]) {
      where[firstCol] = row[firstCol]
    }

    await api.delete(`/api/v1/system/database/table/${props.tableName}/record`, { data: { where } })
    alert('记录删除成功')
    await loadTableData()
  } catch (error) {
    console.error('Failed to delete record:', error)
    alert('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function saveRecord() {
  try {
    if (editingRecord.value) {
      // Update existing record
      const where = {}
      const firstCol = columns.value[0]?.name
      if (firstCol && editingRecord.value[firstCol]) {
        where[firstCol] = editingRecord.value[firstCol]
      }

      await api.put(`/api/v1/system/database/table/${props.tableName}/record`, {
        record: formData.value,
        where
      })
      alert('记录更新成功')
    } else {
      // Add new record
      await api.post(`/api/v1/system/database/table/${props.tableName}/record`, formData.value)
      alert('记录添加成功')
    }

    cancelForm()
    await loadTableData()
  } catch (error) {
    console.error('Failed to save record:', error)
    alert('保存失败: ' + (error.response?.data?.detail || error.message))
  }
}

function cancelForm() {
  showAddForm.value = false
  editingRecord.value = null
  formData.value = {}
}

function close() {
  emit('close')
}
</script>

<style scoped>
.btn-primary {
  @apply inline-flex items-center px-4 py-2 bg-primary hover:bg-primary-hover text-dark-300 rounded-lg transition-colors font-medium;
}

.btn-secondary {
  @apply inline-flex items-center px-4 py-2 bg-dark-200 hover:bg-dark-100 text-text-primary rounded-lg transition-colors font-medium;
}
</style>
