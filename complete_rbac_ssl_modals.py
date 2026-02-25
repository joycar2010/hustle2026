#!/usr/bin/env python3
"""
Script to add complete modals and functionality for RBAC and SSL management
"""

def add_modals():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add modal components after BackupSelectModal
    modals_html = """
    <!-- RBAC Role Modal -->
    <div v-if="showRoleModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-md">
        <h3 class="text-xl font-bold mb-4">{{ isEditingRole ? '编辑角色' : '添加角色' }}</h3>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium mb-2">角色名称</label>
            <input
              v-model="roleForm.role_name"
              type="text"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="请输入角色名称"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">角色代码</label>
            <input
              v-model="roleForm.role_code"
              type="text"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="请输入角色代码（如：admin, user）"
              :disabled="isEditingRole"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">描述</label>
            <textarea
              v-model="roleForm.description"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              rows="3"
              placeholder="请输入角色描述"
            ></textarea>
          </div>
          <div class="flex items-center">
            <input
              v-model="roleForm.is_active"
              type="checkbox"
              id="role-active"
              class="mr-2"
            />
            <label for="role-active" class="text-sm">启用此角色</label>
          </div>
        </div>
        <div class="flex justify-end space-x-3 mt-6">
          <button @click="showRoleModal = false" class="btn-secondary">取消</button>
          <button @click="saveRole" class="btn-primary">保存</button>
        </div>
      </div>
    </div>

    <!-- SSL Certificate Upload Modal -->
    <div v-if="showCertModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-md">
        <h3 class="text-xl font-bold mb-4">上传SSL证书</h3>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium mb-2">证书名称</label>
            <input
              v-model="certForm.cert_name"
              type="text"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="请输入证书名称"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">域名</label>
            <input
              v-model="certForm.domain_name"
              type="text"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="例如：example.com"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">证书类型</label>
            <select
              v-model="certForm.cert_type"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
            >
              <option value="self_signed">自签名</option>
              <option value="ca_signed">CA签名</option>
              <option value="letsencrypt">Let's Encrypt</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">证书内容（PEM格式）</label>
            <textarea
              v-model="certForm.cert_content"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-xs"
              rows="6"
              placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
            ></textarea>
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">私钥内容（PEM格式）</label>
            <textarea
              v-model="certForm.key_content"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-xs"
              rows="6"
              placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
            ></textarea>
          </div>
          <div class="flex items-center">
            <input
              v-model="certForm.auto_renew"
              type="checkbox"
              id="cert-auto-renew"
              class="mr-2"
            />
            <label for="cert-auto-renew" class="text-sm">自动续期</label>
          </div>
        </div>
        <div class="flex justify-end space-x-3 mt-6">
          <button @click="closeCertModal" class="btn-secondary">取消</button>
          <button @click="uploadCertificate" class="btn-primary">上传</button>
        </div>
      </div>
    </div>
"""

    # Insert modals before the closing </template> tag
    content = content.replace(
        "  </div>\n</template>",
        "  </div>\n" + modals_html + "\n</template>"
    )

    # Add certForm state variable
    cert_form_state = """
const certForm = ref({
  cert_name: '',
  domain_name: '',
  cert_type: 'ca_signed',
  cert_content: '',
  key_content: '',
  auto_renew: false
})

"""

    # Insert after showCertModal
    content = content.replace(
        "const showCertModal = ref(false)\n\n",
        "const showCertModal = ref(false)\n" + cert_form_state
    )

    # Add upload and close functions
    upload_functions = """
async function uploadCertificate() {
  try {
    if (!certForm.value.cert_name || !certForm.value.domain_name || !certForm.value.cert_content || !certForm.value.key_content) {
      alert('请填写所有必填字段')
      return
    }

    await api.post('/api/v1/ssl/certificates/upload', {
      cert_name: certForm.value.cert_name,
      domain_name: certForm.value.domain_name,
      cert_type: certForm.value.cert_type,
      cert_content: certForm.value.cert_content,
      key_content: certForm.value.key_content,
      auto_renew: certForm.value.auto_renew
    })

    alert('证书上传成功')
    closeCertModal()
    await loadCertificates()
  } catch (error) {
    console.error('Failed to upload certificate:', error)
    alert('上传证书失败: ' + (error.response?.data?.detail || error.message))
  }
}

function closeCertModal() {
  showCertModal.value = false
  certForm.value = {
    cert_name: '',
    domain_name: '',
    cert_type: 'ca_signed',
    cert_content: '',
    key_content: '',
    auto_renew: false
  }
}

"""

    # Insert before formatDate function
    content = content.replace(
        "\nfunction formatDate(dateStr) {",
        "\n" + upload_functions + "function formatDate(dateStr) {"
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Successfully added modals and complete functionality to {file_path}")

if __name__ == '__main__':
    add_modals()
