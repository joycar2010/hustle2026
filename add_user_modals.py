#!/usr/bin/env python3
"""
Script to add modals for User Management
"""

def add_user_modals():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add modals before the last </template> tag
    modals_html = '''
    <!-- User Modal -->
    <div v-if="showUserModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-md">
        <h3 class="text-xl font-bold mb-4">{{ isEditingUser ? '编辑用户' : '添加用户' }}</h3>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium mb-2">用户名</label>
            <input
              v-model="userForm.username"
              type="text"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="请输入用户名"
              :disabled="isEditingUser"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">邮箱</label>
            <input
              v-model="userForm.email"
              type="email"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="请输入邮箱"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">密码{{ isEditingUser ? '（留空则不修改）' : '' }}</label>
            <input
              v-model="userForm.password"
              type="password"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              :placeholder="isEditingUser ? '留空则不修改密码' : '请输入密码'"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-2">角色</label>
            <select
              v-model="userForm.role"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
            >
              <option value="管理员">管理员</option>
              <option value="交易员">交易员</option>
              <option value="观察员">观察员</option>
            </select>
          </div>
          <div class="flex items-center">
            <input
              v-model="userForm.is_active"
              type="checkbox"
              id="user-active"
              class="mr-2"
            />
            <label for="user-active" class="text-sm">启用此用户</label>
          </div>
        </div>
        <div class="flex justify-end space-x-3 mt-6">
          <button @click="showUserModal = false" class="btn-secondary">取消</button>
          <button @click="saveUser" class="btn-primary">保存</button>
        </div>
      </div>
    </div>

    <!-- User Roles Assignment Modal -->
    <div v-if="showUserRolesModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <h3 class="text-xl font-bold mb-4">分配角色 - {{ currentUser?.username }}</h3>

        <div class="mb-4 text-sm text-text-secondary">
          已选择 {{ selectedUserRoles.length }} 个角色
        </div>

        <div class="space-y-3">
          <div v-for="role in roles" :key="role.role_id" class="flex items-start p-3 bg-dark-200 rounded hover:bg-dark-300">
            <input
              type="checkbox"
              :id="'user-role-' + role.role_id"
              :value="role.role_id"
              v-model="selectedUserRoles"
              class="mt-1 mr-3"
            />
            <label :for="'user-role-' + role.role_id" class="flex-1 cursor-pointer">
              <div class="font-medium">{{ role.role_name }}</div>
              <div class="text-xs text-text-secondary">{{ role.role_code }}</div>
              <div v-if="role.description" class="text-xs text-text-secondary mt-1">{{ role.description }}</div>
            </label>
            <span :class="role.is_active ? 'text-success' : 'text-text-secondary'" class="text-xs">
              {{ role.is_active ? '启用' : '禁用' }}
            </span>
          </div>
        </div>

        <div v-if="roles.length === 0" class="text-center py-8 text-text-secondary">
          暂无可用角色
        </div>

        <div class="flex justify-end space-x-3 mt-6">
          <button @click="showUserRolesModal = false" class="btn-secondary">取消</button>
          <button @click="saveUserRoles" class="btn-primary">保存角色</button>
        </div>
      </div>
    </div>
'''

    # Insert before the last </template> tag
    last_template_pos = content.rfind('</template>')
    content = content[:last_template_pos] + modals_html + '\n' + content[last_template_pos:]

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Successfully added user management modals to {file_path}")

if __name__ == '__main__':
    add_user_modals()
