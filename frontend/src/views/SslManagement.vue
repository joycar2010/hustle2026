<template>
  <div class="ssl-management p-6">
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-2xl font-bold">SSL证书管理</h1>
      <button
        @click="showUploadDialog = true"
        class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded"
      >
        上传证书
      </button>
    </div>

    <div v-if="error" class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
      {{ error }}
    </div>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-gray-600">总证书数</div>
        <div class="text-2xl font-bold">{{ certificates.length }}</div>
      </div>
      <div class="bg-green-50 rounded-lg shadow p-4">
        <div class="text-sm text-green-600">有效证书</div>
        <div class="text-2xl font-bold text-green-600">{{ activeCertificates.length }}</div>
      </div>
      <div class="bg-yellow-50 rounded-lg shadow p-4">
        <div class="text-sm text-yellow-600">即将过期</div>
        <div class="text-2xl font-bold text-yellow-600">{{ expiringSoonCertificates.length }}</div>
      </div>
      <div class="bg-red-50 rounded-lg shadow p-4">
        <div class="text-sm text-red-600">已过期</div>
        <div class="text-2xl font-bold text-red-600">{{ expiredCertificates.length }}</div>
      </div>
    </div>

    <div v-if="loading" class="text-center py-8">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
    </div>

    <div v-else class="bg-white rounded-lg shadow">
      <div class="p-4 border-b">
        <h2 class="text-lg font-semibold">证书列表</h2>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">证书名称</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">域名</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">类型</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">过期时间</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">剩余天数</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">状态</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            <tr v-for="cert in certificates" :key="cert.cert_id">
              <td class="px-6 py-4 whitespace-nowrap">{{ cert.cert_name }}</td>
              <td class="px-6 py-4 whitespace-nowrap">
                <code class="bg-gray-100 px-2 py-1 rounded text-sm">{{ cert.domain_name }}</code>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span class="text-xs px-2 py-1 rounded bg-blue-100 text-blue-800">
                  {{ getCertTypeLabel(cert.cert_type) }}
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm">
                {{ formatDate(cert.expires_at) }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span :class="getDaysColor(cert.days_before_expiry)">
                  {{ cert.days_before_expiry }} 天
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span
                  :class="getStatusColor(cert.status)"
                  class="px-2 py-1 rounded text-xs"
                >
                  {{ getStatusLabel(cert.status) }}
                </span>
                <span
                  v-if="cert.is_deployed"
                  class="ml-2 px-2 py-1 rounded text-xs bg-green-100 text-green-800"
                >
                  已部署
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm">
                <button
                  @click="viewCertificate(cert)"
                  class="text-blue-600 hover:text-blue-900 mr-3"
                >
                  查看
                </button>
                <button
                  v-if="!cert.is_deployed && cert.status !== 'expired'"
                  @click="deployCertificate(cert)"
                  class="text-green-600 hover:text-green-900 mr-3"
                >
                  部署
                </button>
                <button
                  v-if="!cert.is_deployed"
                  @click="deleteCertificate(cert)"
                  class="text-red-600 hover:text-red-900"
                >
                  删除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 上传证书对话框 -->
    <div v-if="showUploadDialog" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <h3 class="text-lg font-semibold mb-4">上传SSL证书</h3>
        <form @submit.prevent="handleUpload">
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">证书名称</label>
            <input
              v-model="uploadForm.cert_name"
              type="text"
              required
              class="w-full border rounded px-3 py-2"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">域名</label>
            <input
              v-model="uploadForm.domain_name"
              type="text"
              required
              placeholder="example.com 或 192.168.1.1"
              class="w-full border rounded px-3 py-2"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">证书类型</label>
            <select
              v-model="uploadForm.cert_type"
              required
              class="w-full border rounded px-3 py-2"
            >
              <option value="self_signed">自签名证书</option>
              <option value="ca_signed">CA签名证书</option>
              <option value="letsencrypt">Let's Encrypt</option>
            </select>
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">证书内容 (PEM格式)</label>
            <textarea
              v-model="uploadForm.cert_content"
              rows="8"
              required
              placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
              class="w-full border rounded px-3 py-2 font-mono text-xs"
            ></textarea>
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">私钥内容 (PEM格式)</label>
            <textarea
              v-model="uploadForm.key_content"
              rows="8"
              required
              placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
              class="w-full border rounded px-3 py-2 font-mono text-xs"
            ></textarea>
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">证书链 (可选)</label>
            <textarea
              v-model="uploadForm.chain_content"
              rows="6"
              placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
              class="w-full border rounded px-3 py-2 font-mono text-xs"
            ></textarea>
          </div>
          <div class="mb-4">
            <label class="flex items-center">
              <input
                v-model="uploadForm.auto_renew"
                type="checkbox"
                class="mr-2"
              />
              <span class="text-sm">自动续期</span>
            </label>
          </div>
          <div class="flex justify-end gap-2">
            <button
              type="button"
              @click="closeUploadDialog"
              class="px-4 py-2 border rounded hover:bg-gray-100"
            >
              取消
            </button>
            <button
              type="submit"
              class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              上传
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 证书详情对话框 -->
    <div v-if="showDetailDialog" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[80vh] overflow-y-auto">
        <h3 class="text-lg font-semibold mb-4">证书详情</h3>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="text-sm font-medium text-gray-600">证书名称</label>
              <p class="text-sm">{{ currentCertificate?.cert_name }}</p>
            </div>
            <div>
              <label class="text-sm font-medium text-gray-600">域名</label>
              <p class="text-sm"><code class="bg-gray-100 px-2 py-1 rounded">{{ currentCertificate?.domain_name }}</code></p>
            </div>
            <div>
              <label class="text-sm font-medium text-gray-600">颁发者</label>
              <p class="text-xs">{{ currentCertificate?.issuer }}</p>
            </div>
            <div>
              <label class="text-sm font-medium text-gray-600">主题</label>
              <p class="text-xs">{{ currentCertificate?.subject }}</p>
            </div>
            <div>
              <label class="text-sm font-medium text-gray-600">序列号</label>
              <p class="text-xs font-mono">{{ currentCertificate?.serial_number }}</p>
            </div>
            <div>
              <label class="text-sm font-medium text-gray-600">颁发时间</label>
              <p class="text-sm">{{ formatDate(currentCertificate?.issued_at) }}</p>
            </div>
            <div>
              <label class="text-sm font-medium text-gray-600">过期时间</label>
              <p class="text-sm">{{ formatDate(currentCertificate?.expires_at) }}</p>
            </div>
            <div>
              <label class="text-sm font-medium text-gray-600">剩余天数</label>
              <p :class="getDaysColor(currentCertificate?.days_before_expiry)">
                {{ currentCertificate?.days_before_expiry }} 天
              </p>
            </div>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <button
            @click="closeDetailDialog"
            class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSslStore } from '@/stores/ssl'
import { storeToRefs } from 'pinia'

const sslStore = useSslStore()
const { certificates, loading, error, activeCertificates, expiringSoonCertificates, expiredCertificates } = storeToRefs(sslStore)

const showUploadDialog = ref(false)
const showDetailDialog = ref(false)
const currentCertificate = ref(null)
const uploadForm = ref({
  cert_name: '',
  domain_name: '',
  cert_type: 'ca_signed',
  cert_content: '',
  key_content: '',
  chain_content: '',
  auto_renew: false
})

onMounted(async () => {
  await sslStore.fetchCertificates()
})

const getCertTypeLabel = (type) => {
  const labels = {
    self_signed: '自签名',
    ca_signed: 'CA签名',
    letsencrypt: "Let's Encrypt"
  }
  return labels[type] || type
}

const getStatusLabel = (status) => {
  const labels = {
    active: '有效',
    inactive: '未激活',
    expired: '已过期',
    expiring_soon: '即将过期'
  }
  return labels[status] || status
}

const getStatusColor = (status) => {
  const colors = {
    active: 'bg-green-100 text-green-800',
    inactive: 'bg-gray-100 text-gray-800',
    expired: 'bg-red-100 text-red-800',
    expiring_soon: 'bg-yellow-100 text-yellow-800'
  }
  return colors[status] || 'bg-gray-100 text-gray-800'
}

const getDaysColor = (days) => {
  if (days <= 0) return 'text-red-600 font-semibold'
  if (days <= 30) return 'text-yellow-600 font-semibold'
  return 'text-green-600'
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

const viewCertificate = (cert) => {
  currentCertificate.value = cert
  showDetailDialog.value = true
}

const deployCertificate = async (cert) => {
  if (confirm(`确定要部署证书 "${cert.cert_name}" 吗？`)) {
    try {
      await sslStore.deployCertificate(cert.cert_id, {
        nginx_config_path: '/etc/nginx/sites-available/hustle',
        reload_nginx: true,
        backup_old_cert: true
      })
      alert('证书部署成功')
    } catch (err) {
      alert('证书部署失败')
    }
  }
}

const deleteCertificate = async (cert) => {
  if (confirm(`确定要删除证书 "${cert.cert_name}" 吗？`)) {
    try {
      await sslStore.deleteCertificate(cert.cert_id)
      alert('证书删除成功')
    } catch (err) {
      alert('证书删除失败')
    }
  }
}

const handleUpload = async () => {
  try {
    await sslStore.uploadCertificate(uploadForm.value)
    alert('证书上传成功')
    closeUploadDialog()
  } catch (err) {
    alert('证书上传失败')
  }
}

const closeUploadDialog = () => {
  showUploadDialog.value = false
  uploadForm.value = {
    cert_name: '',
    domain_name: '',
    cert_type: 'ca_signed',
    cert_content: '',
    key_content: '',
    chain_content: '',
    auto_renew: false
  }
}

const closeDetailDialog = () => {
  showDetailDialog.value = false
  currentCertificate.value = null
}
</script>
