#!/usr/bin/env python3
"""
Script to add modals for Security Component management
"""

def add_security_modals():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add modals before the last </template> tag
    modals_html = '''
    <!-- Security Component Config Modal -->
    <div v-if="showConfigModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <h3 class="text-xl font-bold mb-4">组件配置 - {{ currentComponent?.component_name }}</h3>

        <div class="mb-4 p-3 bg-dark-200 rounded">
          <div class="text-sm text-text-secondary mb-2">组件描述</div>
          <div class="text-sm">{{ currentComponent?.description || '无描述' }}</div>
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium mb-2">配置JSON</label>
            <textarea
              v-model="componentConfigJson"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
              rows="15"
              placeholder='{"key": "value"}'
            ></textarea>
            <div class="text-xs text-text-secondary mt-1">
              请输入有效的JSON格式配置
            </div>
          </div>
        </div>

        <div class="flex justify-end space-x-3 mt-6">
          <button @click="showConfigModal = false" class="btn-secondary">取消</button>
          <button @click="saveComponentConfig" class="btn-primary">保存配置</button>
        </div>
      </div>
    </div>

    <!-- Security Component Logs Modal -->
    <div v-if="showLogsModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <h3 class="text-xl font-bold mb-4">操作日志 - {{ currentComponent?.component_name }}</h3>

        <div class="overflow-x-auto">
          <table class="w-full">
            <thead>
              <tr class="border-b border-border-primary">
                <th class="text-left py-2 px-3 text-sm">时间</th>
                <th class="text-left py-2 px-3 text-sm">操作</th>
                <th class="text-left py-2 px-3 text-sm">结果</th>
                <th class="text-left py-2 px-3 text-sm">操作者</th>
                <th class="text-left py-2 px-3 text-sm">IP地址</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in componentLogs" :key="log.log_id" class="border-b border-border-secondary hover:bg-dark-50">
                <td class="py-2 px-3 text-sm text-text-secondary">{{ formatDate(log.performed_at) }}</td>
                <td class="py-2 px-3 text-sm">{{ getActionLabel(log.action) }}</td>
                <td class="py-2 px-3 text-sm">
                  <span :class="log.result === 'success' ? 'text-success' : 'text-danger'">
                    {{ log.result === 'success' ? '成功' : '失败' }}
                  </span>
                </td>
                <td class="py-2 px-3 text-sm text-text-secondary">{{ log.performed_by || '-' }}</td>
                <td class="py-2 px-3 text-sm font-mono text-xs">{{ log.ip_address || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="componentLogs.length === 0" class="text-center py-8 text-text-secondary">
            暂无日志记录
          </div>
        </div>

        <div class="flex justify-end mt-6">
          <button @click="showLogsModal = false" class="btn-secondary">关闭</button>
        </div>
      </div>
    </div>
'''

    # Insert before the last </template> tag
    last_template_pos = content.rfind('</template>')
    content = content[:last_template_pos] + modals_html + '\n' + content[last_template_pos:]

    # Add componentConfigJson computed property
    config_json_computed = '''
const componentConfigJson = computed({
  get: () => JSON.stringify(componentConfig.value, null, 2),
  set: (value) => {
    try {
      componentConfig.value = JSON.parse(value)
    } catch (e) {
      // Keep the string value if invalid JSON
    }
  }
})

'''

    # Insert after errorComponentsCount computed
    content = content.replace(
        "const errorComponentsCount = computed(() =>\n  securityComponents.value.filter(c => c.status === 'error').length\n)\n\n",
        "const errorComponentsCount = computed(() =>\n  securityComponents.value.filter(c => c.status === 'error').length\n)\n\n" + config_json_computed
    )

    # Add getActionLabel function
    action_label_function = '''
function getActionLabel(action) {
  const labels = {
    'enable': '启用',
    'disable': '禁用',
    'config_update': '配置更新',
    'error': '错误'
  }
  return labels[action] || action
}

'''

    # Insert before getComponentTypeLabel
    content = content.replace(
        '\nfunction getComponentTypeLabel(type) {',
        '\n' + action_label_function + 'function getComponentTypeLabel(type) {'
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Successfully added security component modals to {file_path}")

if __name__ == '__main__':
    add_security_modals()
