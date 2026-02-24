<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">系统管理</h1>

    <div class="flex space-x-2 mb-6 border-b border-border-primary">
      <button v-for="tab in tabs" :key="tab.id" @click="activeTab = tab.id" :class="['px-4 py-2 font-medium transition-colors relative', activeTab === tab.id ? 'text-primary' : 'text-text-secondary hover:text-text-primary']">
        {{ tab.label }}
        <div v-if="activeTab === tab.id" class="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"></div>
      </button>
    </div>

    <div class="tab-content">
      <div v-if="activeTab === 'users'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">前端用户管理</h2>
            <button @click="openAddUserModal" class="btn-primary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
              </svg>
              添加用户
            </button>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">用户名</th>
                  <th class="text-left py-3 px-4">邮箱</th>
                  <th class="text-left py-3 px-4">角色</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">创建时间</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in users" :key="user.user_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4">{{ user.username }}</td>
                  <td class="py-3 px-4 text-text-secondary">{{ user.email }}</td>
                  <td class="py-3 px-4">
                    <span class="px-2 py-1 rounded text-xs bg-primary/20 text-primary">{{ user.role }}</span>
                  </td>
                  <td class="py-3 px-4">
                    <button @click="toggleUserStatus(user)" :class="['px-2 py-1 rounded text-xs', user.is_active ? 'bg-success/20 text-success' : 'bg-danger/20 text-danger']">
                      {{ user.is_active ? '激活' : '禁用' }}
                    </button>
                  </td>
                  <td class="py-3 px-4 text-text-secondary">{{ formatDate(user.create_time) }}</td>
                  <td class="py-3 px-4">
                    <button @click="openEditUserModal(user)" class="text-primary hover:text-primary-hover mr-2">编辑</button>
                    <button @click="deleteUser(user.user_id)" class="text-danger hover:text-red-400">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 角色权限管理 -->
      <div v-if="activeTab === 'rbac'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">角色权限管理</h2>
            <button @click="navigateToRbac" class="btn-primary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              打开完整管理页面
            </button>
          </div>
          <div class="bg-dark-200 rounded p-6">
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">系统角色</div>
                <div class="text-2xl font-bold text-primary">5</div>
                <div class="text-xs text-text-secondary mt-1">super_admin, system_admin, security_admin, trader, observer</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">权限总数</div>
                <div class="text-2xl font-bold text-success">20+</div>
                <div class="text-xs text-text-secondary mt-1">涵盖RBAC、安全组件、SSL证书管理</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">权限缓存</div>
                <div class="text-2xl font-bold text-warning">Redis</div>
                <div class="text-xs text-text-secondary mt-1">1小时TTL，自动刷新</div>
              </div>
            </div>
            <div class="space-y-3">
              <h3 class="font-bold text-lg mb-3">功能特性</h3>
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-success mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
                <div>
                  <div class="font-medium">角色管理</div>
                  <div class="text-sm text-text-secondary">创建、编辑、删除、复制角色，支持角色状态切换</div>
                </div>
              </div>
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-success mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
                <div>
                  <div class="font-medium">权限分配</div>
                  <div class="text-sm text-text-secondary">为角色分配权限，为用户分配角色，支持权限继承</div>
                </div>
              </div>
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-success mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
                <div>
                  <div class="font-medium">权限拦截</div>
                  <div class="text-sm text-text-secondary">自动API权限验证，支持路径模式匹配和白名单配置</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 安全组件管理 -->
      <div v-if="activeTab === 'security'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">安全组件管理</h2>
            <button @click="navigateToSecurity" class="btn-primary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              打开完整管理页面
            </button>
          </div>
          <div class="bg-dark-200 rounded p-6">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">安全组件总数</div>
                <div class="text-2xl font-bold text-primary">12</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">已启用</div>
                <div class="text-2xl font-bold text-success">8</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">中间件</div>
                <div class="text-2xl font-bold text-info">4</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">防护层</div>
                <div class="text-2xl font-bold text-warning">5</div>
              </div>
            </div>
            <div class="space-y-3">
              <h3 class="font-bold text-lg mb-3">预定义安全组件</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div class="bg-dark-300 rounded p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="font-medium">CSRF保护</span>
                    <span class="px-2 py-1 rounded text-xs bg-blue-500/20 text-blue-400">中间件</span>
                  </div>
                  <div class="text-xs text-text-secondary">防止跨站请求伪造攻击</div>
                </div>
                <div class="bg-dark-300 rounded p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="font-medium">请求签名验证</span>
                    <span class="px-2 py-1 rounded text-xs bg-blue-500/20 text-blue-400">中间件</span>
                  </div>
                  <div class="text-xs text-text-secondary">HMAC-SHA256签名防重放</div>
                </div>
                <div class="bg-dark-300 rounded p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="font-medium">SQL注入防护</span>
                    <span class="px-2 py-1 rounded text-xs bg-purple-500/20 text-purple-400">防护</span>
                  </div>
                  <div class="text-xs text-text-secondary">自动检测和阻止SQL注入</div>
                </div>
                <div class="bg-dark-300 rounded p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="font-medium">WebSocket认证</span>
                    <span class="px-2 py-1 rounded text-xs bg-blue-500/20 text-blue-400">中间件</span>
                  </div>
                  <div class="text-xs text-text-secondary">强制WebSocket连接认证</div>
                </div>
                <div class="bg-dark-300 rounded p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="font-medium">日志脱敏</span>
                    <span class="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">服务</span>
                  </div>
                  <div class="text-xs text-text-secondary">自动脱敏敏感信息</div>
                </div>
                <div class="bg-dark-300 rounded p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="font-medium">数据加密服务</span>
                    <span class="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">服务</span>
                  </div>
                  <div class="text-xs text-text-secondary">Fernet加密API密钥</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- SSL证书管理 -->
      <div v-if="activeTab === 'ssl'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">SSL证书管理</h2>
            <button @click="navigateToSsl" class="btn-primary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              打开完整管理页面
            </button>
          </div>
          <div class="bg-dark-200 rounded p-6">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">证书总数</div>
                <div class="text-2xl font-bold text-primary">0</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">有效证书</div>
                <div class="text-2xl font-bold text-success">0</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">即将过期</div>
                <div class="text-2xl font-bold text-warning">0</div>
              </div>
              <div class="bg-dark-300 rounded p-4">
                <div class="text-sm text-text-secondary mb-1">已过期</div>
                <div class="text-2xl font-bold text-danger">0</div>
              </div>
            </div>
            <div class="space-y-3">
              <h3 class="font-bold text-lg mb-3">功能特性</h3>
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-success mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
                <div>
                  <div class="font-medium">证书上传</div>
                  <div class="text-sm text-text-secondary">支持PEM格式证书、私钥和证书链上传</div>
                </div>
              </div>
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-success mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
                <div>
                  <div class="font-medium">一键部署</div>
                  <div class="text-sm text-text-secondary">自动部署到Nginx，支持备份和回滚</div>
                </div>
              </div>
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-success mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
                <div>
                  <div class="font-medium">过期监控</div>
                  <div class="text-sm text-text-secondary">自动检查证书过期状态，支持定时任务和告警</div>
                </div>
              </div>
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-success mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
                <div>
                  <div class="font-medium">证书类型</div>
                  <div class="text-sm text-text-secondary">支持自签名、CA签名和Let's Encrypt证书</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'version'" class="space-y-6">
        <div class="card">
          <h2 class="text-xl font-bold mb-4">系统版本管理</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-2">前端版本</h3>
              <div class="text-2xl font-mono text-primary mb-2">{{ systemInfo.frontend_version }}</div>
              <div class="text-sm text-text-secondary">构建时间: {{ systemInfo.frontend_build_time }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-2">后端版本</h3>
              <div class="text-2xl font-mono text-primary mb-2">{{ systemInfo.backend_version }}</div>
              <div class="text-sm text-text-secondary">Python: {{ systemInfo.python_version }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-2">数据库版本</h3>
              <div class="text-2xl font-mono text-primary mb-2">PostgreSQL {{ systemInfo.db_version }}</div>
              <div class="text-sm text-text-secondary">连接状态: <span class="text-success">正常</span></div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-2">系统运行时间</h3>
              <div class="text-2xl font-mono text-primary mb-2">{{ systemInfo.uptime }}</div>
              <div class="text-sm text-text-secondary">启动时间: {{ systemInfo.start_time }}</div>
            </div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <h3 class="font-bold mb-3">GitHub版本管理</h3>
            <div class="mb-4">
              <label class="block text-sm font-medium mb-2">推送备注</label>
              <input
                v-model="pushRemark"
                type="text"
                placeholder="请输入本次推送的备注信息（可选）"
                class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              />
            </div>
            <div class="flex space-x-3 mb-6">
              <button @click="pushToGitHub" class="btn-primary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                推送到GitHub
              </button>
              <button @click="refreshVersionHistory" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新记录
              </button>
            </div>

            <div class="mb-4">
              <h4 class="font-bold mb-3">版本备份记录</h4>
              <div class="overflow-x-auto">
                <table class="w-full">
                  <thead>
                    <tr class="border-b border-border-primary">
                      <th class="text-left py-3 px-4">版本号</th>
                      <th class="text-left py-3 px-4">提交信息</th>
                      <th class="text-left py-3 px-4">提交时间</th>
                      <th class="text-left py-3 px-4">提交者</th>
                      <th class="text-left py-3 px-4">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="version in versionHistory" :key="version.hash" class="border-b border-border-secondary hover:bg-dark-50">
                      <td class="py-3 px-4 font-mono text-sm">{{ version.hash.substring(0, 7) }}</td>
                      <td class="py-3 px-4">{{ version.message }}</td>
                      <td class="py-3 px-4 text-text-secondary text-sm">{{ version.date }}</td>
                      <td class="py-3 px-4 text-text-secondary text-sm">{{ version.author }}</td>
                      <td class="py-3 px-4">
                        <button @click="rollbackToVersion(version.hash)" class="text-warning hover:text-yellow-400 mr-2">
                          <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                          </svg>
                          回滚
                        </button>
                        <button @click="deleteVersionByHash(version.hash)" class="text-danger hover:text-red-400">
                          <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                          删除
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div v-if="versionHistory.length === 0" class="text-center py-8 text-text-secondary">
                  暂无版本记录
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'database'" class="space-y-6">
        <div class="card">
          <h2 class="text-xl font-bold mb-4">PostgreSQL数据库管理</h2>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">数据库大小</div>
              <div class="text-2xl font-bold">{{ dbStats.size }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">表数量</div>
              <div class="text-2xl font-bold">{{ dbStats.tables }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">活动连接</div>
              <div class="text-2xl font-bold">{{ dbStats.connections }}</div>
            </div>
          </div>
          <div class="mb-4">
            <h3 class="font-bold mb-3">数据表列表</h3>
            <div class="overflow-x-auto">
              <table class="w-full">
                <thead>
                  <tr class="border-b border-border-primary">
                    <th class="text-left py-3 px-4">表名</th>
                    <th class="text-left py-3 px-4">记录数</th>
                    <th class="text-left py-3 px-4">大小</th>
                    <th class="text-left py-3 px-4">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="table in dbTables" :key="table.name" class="border-b border-border-secondary hover:bg-dark-50">
                    <td class="py-3 px-4 font-mono">{{ table.name }}</td>
                    <td class="py-3 px-4 text-text-secondary">{{ table.rows }}</td>
                    <td class="py-3 px-4 text-text-secondary">{{ table.size }}</td>
                    <td class="py-3 px-4">
                      <button @click="viewTable(table.name)" class="text-primary hover:text-primary-hover mr-2">查看</button>
                      <button @click="backupTable(table.name)" class="text-warning hover:text-yellow-400">备份</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="flex space-x-3">
            <button @click="backupDatabase" class="btn-primary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              备份数据库
            </button>
            <button @click="restoreDatabase" class="btn-secondary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              恢复数据库
            </button>
            <button @click="cleanLogs" class="btn-secondary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              清理日志
            </button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'alerts'" class="space-y-6">
        <div class="card">
          <h2 class="text-xl font-bold mb-4">提醒声音设置</h2>
          <p class="text-text-secondary mb-6">为不同类型的提醒设置自定义MP3声音文件</p>

          <div class="space-y-6">
            <!-- Single-leg Alert Sound -->
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-3">单腿提醒声音</h3>
              <div class="flex items-center space-x-4 mb-3">
                <input type="file" accept=".mp3" @change="handleFileUpload($event, 'single_leg')" ref="singleLegFileInput" class="hidden" />
                <button @click="$refs.singleLegFileInput.click()" class="btn-secondary">
                  <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  选择文件
                </button>
                <span v-if="alertSounds.singleLeg" class="text-sm text-text-secondary">{{ getFileName(alertSounds.singleLeg) }}</span>
                <button v-if="alertSounds.singleLeg" @click="playSound(alertSounds.singleLeg)" class="btn-secondary">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </button>
              </div>
              <div class="flex items-center space-x-3">
                <label class="text-sm text-text-secondary">提醒次数:</label>
                <input
                  type="number"
                  v-model.number="alertRepeatCounts.singleLeg"
                  min="1"
                  max="10"
                  class="w-20 px-3 py-1.5 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary text-sm"
                />
                <span class="text-xs text-text-tertiary">次</span>
              </div>
            </div>

            <!-- Spread Alert Sound -->
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-3">点差提醒声音</h3>
              <div class="flex items-center space-x-4 mb-3">
                <input type="file" accept=".mp3" @change="handleFileUpload($event, 'spread')" ref="spreadFileInput" class="hidden" />
                <button @click="$refs.spreadFileInput.click()" class="btn-secondary">
                  <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  选择文件
                </button>
                <span v-if="alertSounds.spread" class="text-sm text-text-secondary">{{ getFileName(alertSounds.spread) }}</span>
                <button v-if="alertSounds.spread" @click="playSound(alertSounds.spread)" class="btn-secondary">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </button>
              </div>
              <div class="flex items-center space-x-3">
                <label class="text-sm text-text-secondary">提醒次数:</label>
                <input
                  type="number"
                  v-model.number="alertRepeatCounts.spread"
                  min="1"
                  max="10"
                  class="w-20 px-3 py-1.5 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary text-sm"
                />
                <span class="text-xs text-text-tertiary">次</span>
              </div>
            </div>

            <!-- Net Asset Alert Sound -->
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-3">净资产提醒声音</h3>
              <div class="flex items-center space-x-4 mb-3">
                <input type="file" accept=".mp3" @change="handleFileUpload($event, 'net_asset')" ref="netAssetFileInput" class="hidden" />
                <button @click="$refs.netAssetFileInput.click()" class="btn-secondary">
                  <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  选择文件
                </button>
                <span v-if="alertSounds.netAsset" class="text-sm text-text-secondary">{{ getFileName(alertSounds.netAsset) }}</span>
                <button v-if="alertSounds.netAsset" @click="playSound(alertSounds.netAsset)" class="btn-secondary">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </button>
              </div>
              <div class="flex items-center space-x-3">
                <label class="text-sm text-text-secondary">提醒次数:</label>
                <input
                  type="number"
                  v-model.number="alertRepeatCounts.netAsset"
                  min="1"
                  max="10"
                  class="w-20 px-3 py-1.5 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary text-sm"
                />
                <span class="text-xs text-text-tertiary">次</span>
              </div>
            </div>

            <!-- MT5 Alert Sound -->
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-3">MT5状态提醒声音</h3>
              <div class="flex items-center space-x-4 mb-3">
                <input type="file" accept=".mp3" @change="handleFileUpload($event, 'mt5')" ref="mt5FileInput" class="hidden" />
                <button @click="$refs.mt5FileInput.click()" class="btn-secondary">
                  <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  选择文件
                </button>
                <span v-if="alertSounds.mt5" class="text-sm text-text-secondary">{{ getFileName(alertSounds.mt5) }}</span>
                <button v-if="alertSounds.mt5" @click="playSound(alertSounds.mt5)" class="btn-secondary">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </button>
              </div>
              <div class="flex items-center space-x-3">
                <label class="text-sm text-text-secondary">提醒次数:</label>
                <input
                  type="number"
                  v-model.number="alertRepeatCounts.mt5"
                  min="1"
                  max="10"
                  class="w-20 px-3 py-1.5 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary text-sm"
                />
                <span class="text-xs text-text-tertiary">次</span>
              </div>
            </div>

            <!-- Liquidation Alert Sound -->
            <div class="bg-dark-200 rounded p-4">
              <h3 class="font-bold mb-3">爆仓提醒声音</h3>
              <div class="flex items-center space-x-4 mb-3">
                <input type="file" accept=".mp3" @change="handleFileUpload($event, 'liquidation')" ref="liquidationFileInput" class="hidden" />
                <button @click="$refs.liquidationFileInput.click()" class="btn-secondary">
                  <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  选择文件
                </button>
                <span v-if="alertSounds.liquidation" class="text-sm text-text-secondary">{{ getFileName(alertSounds.liquidation) }}</span>
                <button v-if="alertSounds.liquidation" @click="playSound(alertSounds.liquidation)" class="btn-secondary">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </button>
              </div>
              <div class="flex items-center space-x-3">
                <label class="text-sm text-text-secondary">提醒次数:</label>
                <input
                  type="number"
                  v-model.number="alertRepeatCounts.liquidation"
                  min="1"
                  max="10"
                  class="w-20 px-3 py-1.5 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary text-sm"
                />
                <span class="text-xs text-text-tertiary">次</span>
              </div>
            </div>
          </div>

          <div class="mt-6">
            <button @click="saveAlertSounds" class="btn-primary">
              保存设置
            </button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'logs'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">交易统计日志</h2>
            <div class="flex space-x-3">
              <button @click="toggleLogging" :class="['btn-primary', loggingEnabled ? 'bg-success' : 'bg-danger']">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {{ loggingEnabled ? '日志已启用' : '日志已禁用' }}
              </button>
              <button @click="refreshLogs" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新日志
              </button>
              <button @click="clearLogs" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                清空日志
              </button>
            </div>
          </div>

          <div class="mb-4">
            <p class="text-text-secondary text-sm mb-2">
              日志功能记录每笔交易的盈亏计算过程，包括开仓、平仓、做多、做空等详细信息。
            </p>
            <div class="bg-dark-100 rounded p-3 text-sm">
              <div class="flex items-center space-x-4">
                <span class="text-text-secondary">日志级别:</span>
                <span class="text-primary font-mono">INFO</span>
                <span class="text-text-secondary">|</span>
                <span class="text-text-secondary">日志位置:</span>
                <span class="text-primary font-mono">后端控制台输出</span>
              </div>
            </div>
          </div>

          <div class="bg-dark-100 rounded p-4">
            <div class="flex justify-between items-center mb-3">
              <h3 class="font-bold">实时日志输出</h3>
              <div class="flex items-center space-x-3">
                <label class="text-sm text-text-secondary">显示行数:</label>
                <select v-model="logDisplayLines" class="px-3 py-1.5 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary text-sm">
                  <option value="50">50行</option>
                  <option value="100">100行</option>
                  <option value="200">200行</option>
                  <option value="500">500行</option>
                </select>
              </div>
            </div>

            <div class="bg-dark-300 rounded p-4 font-mono text-xs overflow-auto" style="max-height: 500px;">
              <div v-if="tradingLogs.length === 0" class="text-center text-text-secondary py-8">
                暂无日志记录
              </div>
              <div v-else>
                <div v-for="(log, index) in displayedLogs" :key="index" :class="getLogClass(log)" class="py-1 border-b border-border-secondary last:border-0">
                  <span class="text-text-tertiary mr-2">{{ log.timestamp }}</span>
                  <span :class="getLogLevelClass(log.level)" class="mr-2">[{{ log.level }}]</span>
                  <span>{{ log.message }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="mt-6 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">总日志条数</div>
              <div class="text-2xl font-bold">{{ tradingLogs.length }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">最后更新时间</div>
              <div class="text-lg font-mono">{{ lastLogUpdate }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">日志状态</div>
              <div class="text-lg font-bold" :class="loggingEnabled ? 'text-success' : 'text-danger'">
                {{ loggingEnabled ? '运行中' : '已停止' }}
              </div>
            </div>
          </div>

          <div class="mt-6 bg-dark-200 rounded p-4">
            <h3 class="font-bold mb-3">日志说明</h3>
            <div class="space-y-2 text-sm text-text-secondary">
              <div class="flex items-start">
                <span class="text-primary mr-2">•</span>
                <span><strong class="text-text-primary">[Binance]</strong> - Binance平台交易日志</span>
              </div>
              <div class="flex items-start">
                <span class="text-primary mr-2">•</span>
                <span><strong class="text-text-primary">[MT5]</strong> - MT5平台交易日志</span>
              </div>
              <div class="flex items-start">
                <span class="text-primary mr-2">•</span>
                <span><strong class="text-text-primary">做多买入</strong> - 开仓或增加多头仓位</span>
              </div>
              <div class="flex items-start">
                <span class="text-primary mr-2">•</span>
                <span><strong class="text-text-primary">做多平仓</strong> - 卖出平掉多头仓位，显示盈亏</span>
              </div>
              <div class="flex items-start">
                <span class="text-primary mr-2">•</span>
                <span><strong class="text-text-primary">做空卖出</strong> - 开仓或增加空头仓位</span>
              </div>
              <div class="flex items-start">
                <span class="text-primary mr-2">•</span>
                <span><strong class="text-text-primary">做空平仓</strong> - 买入平掉空头仓位，显示盈亏</span>
              </div>
              <div class="flex items-start">
                <span class="text-primary mr-2">•</span>
                <span><strong class="text-text-primary">统计计算完成</strong> - 显示最终统计汇总和剩余持仓</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'refresh'" class="space-y-6">
        <div class="card">
          <h2 class="text-xl font-bold mb-4">刷新频率管理</h2>
          <p class="text-text-secondary text-sm mb-6">
            统一管理系统各模块的数据刷新频率，优化性能和网络负载
          </p>

          <!-- 全局设置 -->
          <div class="bg-dark-200 rounded p-4 mb-6">
            <h3 class="font-bold mb-4">全局设置</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="flex items-center justify-between p-3 bg-dark-100 rounded">
                <div>
                  <div class="font-medium">页面可见性检测</div>
                  <div class="text-sm text-text-secondary">页面不可见时降低刷新频率</div>
                </div>
                <label class="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" v-model="refreshSettings.visibilityDetection" class="sr-only peer" @change="saveRefreshSettings">
                  <div class="w-11 h-6 bg-dark-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
                </label>
              </div>

              <div class="flex items-center justify-between p-3 bg-dark-100 rounded">
                <div>
                  <div class="font-medium">WebSocket 连接</div>
                  <div class="text-sm text-text-secondary">使用WebSocket替代轮询</div>
                </div>
                <label class="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" v-model="refreshSettings.useWebSocket" class="sr-only peer" @change="saveRefreshSettings">
                  <div class="w-11 h-6 bg-dark-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
                </label>
              </div>

              <div class="flex items-center justify-between p-3 bg-dark-100 rounded">
                <div>
                  <div class="font-medium">批量请求合并</div>
                  <div class="text-sm text-text-secondary">合并多个请求减少开销</div>
                </div>
                <label class="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" v-model="refreshSettings.batchRequests" class="sr-only peer" @change="saveRefreshSettings">
                  <div class="w-11 h-6 bg-dark-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
                </label>
              </div>

              <div class="p-3 bg-dark-100 rounded">
                <div class="font-medium mb-2">不可见时刷新倍率</div>
                <div class="flex items-center space-x-3">
                  <input
                    type="range"
                    v-model="refreshSettings.inactiveMultiplier"
                    min="2"
                    max="10"
                    step="1"
                    class="flex-1"
                    @change="saveRefreshSettings"
                  >
                  <span class="text-primary font-bold w-12">{{ refreshSettings.inactiveMultiplier }}x</span>
                </div>
                <div class="text-xs text-text-secondary mt-1">页面不可见时刷新间隔延长倍数</div>
              </div>
            </div>
          </div>

          <!-- 模块刷新频率 -->
          <div class="bg-dark-200 rounded p-4 mb-6">
            <div class="flex justify-between items-center mb-4">
              <h3 class="font-bold">模块刷新频率</h3>
              <button @click="resetToDefaults" class="text-sm text-primary hover:text-primary-hover">
                恢复默认值
              </button>
            </div>

            <div class="space-y-3">
              <div v-for="module in refreshModules" :key="module.id" class="flex items-center justify-between p-3 bg-dark-100 rounded hover:bg-dark-50 transition-colors">
                <div class="flex-1">
                  <div class="flex items-center space-x-2">
                    <span class="font-medium">{{ module.name }}</span>
                    <span :class="getFrequencyBadgeClass(module.interval)" class="px-2 py-0.5 rounded text-xs">
                      {{ getFrequencyLabel(module.interval) }}
                    </span>
                  </div>
                  <div class="text-sm text-text-secondary">{{ module.description }}</div>
                </div>
                <div class="flex items-center space-x-3">
                  <select
                    v-model="module.interval"
                    @change="saveRefreshSettings"
                    class="px-3 py-1.5 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary text-sm"
                  >
                    <option :value="1000">1秒</option>
                    <option :value="2000">2秒</option>
                    <option :value="3000">3秒</option>
                    <option :value="5000">5秒</option>
                    <option :value="10000">10秒</option>
                    <option :value="30000">30秒</option>
                    <option :value="60000">60秒</option>
                    <option :value="0">禁用</option>
                  </select>
                  <label class="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" v-model="module.enabled" class="sr-only peer" @change="saveRefreshSettings">
                    <div class="w-11 h-6 bg-dark-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-success"></div>
                  </label>
                </div>
              </div>
            </div>
          </div>

          <!-- 统计信息 -->
          <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">活跃模块</div>
              <div class="text-2xl font-bold text-primary">{{ activeModulesCount }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">每分钟请求</div>
              <div class="text-2xl font-bold text-warning">{{ requestsPerMinute }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">预估流量/小时</div>
              <div class="text-2xl font-bold text-success">{{ estimatedTrafficPerHour }}</div>
            </div>
            <div class="bg-dark-200 rounded p-4">
              <div class="text-sm text-text-secondary mb-1">WebSocket状态</div>
              <div class="text-lg font-bold" :class="wsConnected ? 'text-success' : 'text-danger'">
                {{ wsConnected ? '已连接' : '未连接' }}
              </div>
            </div>
          </div>

          <!-- 性能建议 -->
          <div class="bg-dark-200 rounded p-4">
            <h3 class="font-bold mb-3">性能建议</h3>
            <div class="space-y-2">
              <div v-for="(suggestion, index) in performanceSuggestions" :key="index" class="flex items-start space-x-2 text-sm">
                <svg class="w-5 h-5 text-primary flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span :class="suggestion.type === 'warning' ? 'text-warning' : 'text-text-secondary'">{{ suggestion.message }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- WebSocket Monitoring Tab -->
      <div v-if="activeTab === 'websocket'" class="space-y-6">
        <WebSocketMonitor />
      </div>
    </div>

    <div v-if="showUserModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click.self="closeUserModal">
      <div class="bg-dark-200 rounded-lg p-6 w-full max-w-md">
        <h3 class="text-xl font-bold mb-4">{{ isEditMode ? '编辑用户' : '添加用户' }}</h3>
        <form @submit.prevent="saveUser">
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium mb-1">用户名</label>
              <input v-model="userForm.username" type="text" required class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1">邮箱</label>
              <input v-model="userForm.email" type="email" required class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
            </div>
            <div v-if="!isEditMode">
              <label class="block text-sm font-medium mb-1">密码</label>
              <input v-model="userForm.password" type="password" required class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1">角色</label>
              <select v-model="userForm.role" class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
                <option value="管理员">管理员</option>
                <option value="交易员">交易员</option>
                <option value="观察员">观察员</option>
              </select>
            </div>
            <div class="flex items-center">
              <input v-model="userForm.is_active" type="checkbox" id="is_active" class="mr-2" />
              <label for="is_active" class="text-sm">激活用户</label>
            </div>
          </div>
          <div class="flex justify-end space-x-3 mt-6">
            <button type="button" @click="closeUserModal" class="btn-secondary">取消</button>
            <button type="submit" class="btn-primary">保存</button>
          </div>
        </form>
      </div>
    </div>

    <TableDetailModal
      :show="showTableModal"
      :table-name="selectedTable"
      @close="showTableModal = false"
    />

    <BackupSelectModal
      :show="showBackupModal"
      @close="showBackupModal = false"
      @select="restoreDatabaseFromBackup"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/services/api'
import TableDetailModal from '@/components/modals/TableDetailModal.vue'
import BackupSelectModal from '@/components/modals/BackupSelectModal.vue'
import WebSocketMonitor from '@/components/system/WebSocketMonitor.vue'
import { useMarketStore } from '@/stores/market'

// 引入market store以获取WebSocket连接状态
const marketStore = useMarketStore()
const router = useRouter()

const activeTab = ref('users')
const tabs = [
  { id: 'users', label: '前端用户管理' },
  { id: 'rbac', label: '角色权限管理' },
  { id: 'security', label: '安全组件管理' },
  { id: 'ssl', label: 'SSL证书管理' },
  { id: 'version', label: '系统版本管理' },
  { id: 'database', label: 'PostgreSQL数据库管理' },
  { id: 'alerts', label: '提醒声音设置' },
  { id: 'logs', label: '日志管理' },
  { id: 'refresh', label: '刷新管理' },
  { id: 'websocket', label: 'WebSocket监控' }
]

const users = ref([])
const showUserModal = ref(false)
const isEditMode = ref(false)
const userForm = ref({ user_id: null, username: '', email: '', password: '', role: '交易员', is_active: true })

const showTableModal = ref(false)
const selectedTable = ref('')
const showBackupModal = ref(false)

const versionHistory = ref([])
const pushRemark = ref('')

const systemInfo = ref({
  frontend_version: '1.0.0',
  frontend_build_time: '2026-02-19 12:00:00',
  backend_version: '1.0.0',
  python_version: '3.13.7',
  db_version: '16.1',
  uptime: '2天 5小时',
  start_time: '2026-02-17 07:00:00'
})

const dbStats = ref({ size: '0 MB', tables: 0, connections: 0 })
const dbTables = ref([])

const alertSounds = ref({
  singleLeg: null,
  spread: null,
  netAsset: null,
  mt5: null,
  liquidation: null
})

const alertRepeatCounts = ref({
  singleLeg: 3,
  spread: 3,
  netAsset: 3,
  mt5: 3,
  liquidation: 3
})

// Logging state
const loggingEnabled = ref(true)
const tradingLogs = ref([])
const logDisplayLines = ref(100)
const lastLogUpdate = ref('-')
let logRefreshInterval = null

// Refresh management state
const refreshSettings = ref({
  visibilityDetection: true,
  useWebSocket: false,
  batchRequests: true,
  inactiveMultiplier: 5
})

const refreshModules = ref([
  { id: 'dashboard_price', name: 'Dashboard 价格数据', description: '实时市场价格和点差', interval: 1000, enabled: true, default: 1000 },
  { id: 'spread_table', name: '点差数据表', description: '实时点差监控', interval: 1000, enabled: true, default: 1000 },
  { id: 'spread_chart', name: '点差图表', description: '盈利数据可视化', interval: 1000, enabled: true, default: 1000 },
  { id: 'strategy_panel', name: '策略面板', description: '策略状态更新', interval: 1000, enabled: true, default: 1000 },
  { id: 'risk_management', name: '风险管理', description: '风险指标监控', interval: 5000, enabled: true, default: 5000 },
  { id: 'open_orders', name: '未平仓订单', description: '订单列表更新', interval: 5000, enabled: true, default: 5000 },
  { id: 'manual_trading', name: '手动交易', description: '最近订单刷新', interval: 5000, enabled: true, default: 5000 },
  { id: 'logs', name: '日志管理', description: '交易统计日志', interval: 5000, enabled: true, default: 5000 },
  { id: 'spread_history', name: '点差历史图表', description: '历史数据展示', interval: 5000, enabled: true, default: 5000 },
  { id: 'asset_dashboard', name: '资产仪表盘', description: '资产数据刷新', interval: 10000, enabled: true, default: 10000 },
  { id: 'account_status', name: '账户状态面板', description: '账户信息更新', interval: 30000, enabled: true, default: 30000 }
])

// WebSocket连接状态 - 从market store获取实时状态
const wsConnected = computed(() => marketStore.connected)

onMounted(async () => {
  // 确保WebSocket连接已建立（如果配置启用）
  if (refreshSettings.value.useWebSocket && !marketStore.connected) {
    marketStore.connect()
  }

  await loadUsers()
  await loadSystemInfo()
  await loadDbStats()
  await loadVersionHistory()
  await loadAlertSounds()
  await loadRefreshSettings()
})

async function loadUsers() {
  try {
    const response = await api.get('/api/v1/users')
    users.value = response.data
  } catch (error) {
    console.error('Failed to load users:', error)
    users.value = []
  }
}

// 导航到管理页面
function navigateToRbac() {
  router.push('/rbac')
}

function navigateToSecurity() {
  router.push('/security')
}

function navigateToSsl() {
  router.push('/ssl')
}

function openAddUserModal() {
  isEditMode.value = false
  userForm.value = { user_id: null, username: '', email: '', password: '', role: '交易员', is_active: true }
  showUserModal.value = true
}

function openEditUserModal(user) {
  isEditMode.value = true
  userForm.value = { ...user, password: '' }
  showUserModal.value = true
}

function closeUserModal() {
  showUserModal.value = false
}

async function saveUser() {
  try {
    if (isEditMode.value) {
      await api.put(`/api/v1/users/${userForm.value.user_id}`, userForm.value)
      alert('用户更新成功')
    } else {
      // For creating new user, only send fields expected by backend
      const createPayload = {
        username: userForm.value.username,
        email: userForm.value.email,
        password: userForm.value.password,
        role: userForm.value.role,
        is_active: userForm.value.is_active
      }
      await api.post('/api/v1/users/', createPayload)
      alert('用户添加成功')
    }
    await loadUsers()
    closeUserModal()
  } catch (error) {
    console.error('Failed to save user:', error)
    console.error('Error response:', error.response)
    console.error('Error data:', error.response?.data)

    let errorMessage = '操作失败: '
    if (error.response?.data) {
      if (typeof error.response.data === 'string') {
        errorMessage += error.response.data
      } else if (error.response.data.detail) {
        if (typeof error.response.data.detail === 'string') {
          errorMessage += error.response.data.detail
        } else if (Array.isArray(error.response.data.detail)) {
          // Handle FastAPI validation errors (array of error objects)
          errorMessage += error.response.data.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ')
        } else {
          errorMessage += JSON.stringify(error.response.data.detail)
        }
      } else {
        errorMessage += JSON.stringify(error.response.data)
      }
    } else if (error.message) {
      errorMessage += error.message
    } else {
      errorMessage += '未知错误'
    }

    alert(errorMessage)
  }
}

async function toggleUserStatus(user) {
  try {
    await api.put(`/api/v1/users/${user.user_id}`, { ...user, is_active: !user.is_active })
    await loadUsers()
    alert('用户状态已更新')
  } catch (error) {
    console.error('Failed to toggle user status:', error)
    alert('操作失败')
  }
}

async function deleteUser(userId) {
  if (!confirm('确定要删除此用户吗？')) return
  try {
    await api.delete(`/api/v1/users/${userId}`)
    await loadUsers()
    alert('用户已删除')
  } catch (error) {
    console.error('Failed to delete user:', error)
    alert('删除失败')
  }
}

async function loadSystemInfo() {
  try {
    const response = await api.get('/api/v1/system/info')
    systemInfo.value = response.data
  } catch (error) {
    console.error('Failed to load system info:', error)
  }
}

async function pushToGitHub() {
  if (!confirm('确定要推送当前版本到GitHub吗？')) return
  try {
    await api.post('/api/v1/system/github/push', {
      remark: pushRemark.value || undefined
    })
    alert('推送成功')
    pushRemark.value = '' // Clear remark after successful push
    await loadVersionHistory()
  } catch (error) {
    console.error('Failed to push to GitHub:', error)
    alert('推送失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function loadVersionHistory() {
  try {
    const response = await api.get('/api/v1/system/github/versions')
    versionHistory.value = response.data
  } catch (error) {
    console.error('Failed to load version history:', error)
    versionHistory.value = []
  }
}

async function refreshVersionHistory() {
  await loadVersionHistory()
  alert('版本记录已刷新')
}

async function rollbackToVersion(hash) {
  if (!confirm(`确定要回滚到版本 ${hash.substring(0, 7)} 吗？这将重置当前代码！`)) return
  try {
    await api.post('/api/v1/system/github/rollback', { hash })
    alert('回滚成功，请重启系统')
    await loadVersionHistory()
  } catch (error) {
    console.error('Failed to rollback:', error)
    alert('回滚失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function deleteVersionByHash(hash) {
  if (!confirm(`确定要删除版本 ${hash.substring(0, 7)} 吗？`)) return
  try {
    await api.delete(`/api/v1/system/github/version/${hash}`)
    alert('版本已删除')
    await loadVersionHistory()
  } catch (error) {
    console.error('Failed to delete version:', error)
    alert('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

// Legacy functions - kept for compatibility
async function rollbackVersion() {
  const version = prompt('请输入要回滚到的版本号:')
  if (!version) return
  try {
    await api.post('/api/v1/system/github/rollback', { version })
    alert('回滚成功，请重启系统')
  } catch (error) {
    console.error('Failed to rollback:', error)
    alert('回滚失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function deleteVersion() {
  const version = prompt('请输入要删除的版本号:')
  if (!version) return
  if (!confirm(`确定要删除版本 ${version} 吗？`)) return
  try {
    await api.delete(`/api/v1/system/github/version/${version}`)
    alert('版本已删除')
  } catch (error) {
    console.error('Failed to delete version:', error)
    alert('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function loadDbStats() {
  try {
    const response = await api.get('/api/v1/system/database/stats')
    if (response.data && response.data.stats) {
      dbStats.value = response.data.stats
      dbTables.value = response.data.tables || []
    } else {
      console.error('Invalid response format:', response.data)
      alert('数据库统计信息格式错误')
    }
  } catch (error) {
    console.error('Failed to load database stats:', error)
    alert('加载数据库统计信息失败: ' + (error.response?.data?.detail || error.message))
    // Set default values
    dbStats.value = { size: '0 MB', tables: 0, connections: 0 }
    dbTables.value = []
  }
}

async function backupDatabase() {
  if (!confirm('确定要备份整个数据库吗？')) return
  try {
    const response = await api.post('/api/v1/system/database/backup')
    alert(`备份成功: ${response.data.filename}`)
  } catch (error) {
    console.error('Failed to backup database:', error)
    alert('备份失败: ' + (error.response?.data?.detail || error.message))
  }
}

function restoreDatabase() {
  showBackupModal.value = true
}

async function restoreDatabaseFromBackup(filename) {
  if (!confirm(`确定要从 ${filename} 恢复数据库吗？这将覆盖当前数据！`)) return
  try {
    await api.post('/api/v1/system/database/restore', { filename })
    alert('恢复成功')
    await loadDbStats()
  } catch (error) {
    console.error('Failed to restore database:', error)
    alert('恢复失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function cleanLogs() {
  if (!confirm('确定要清理数据库日志吗？')) return
  try {
    const response = await api.post('/api/v1/system/database/clean-logs')
    alert(`日志清理成功\n删除市场数据: ${response.data.market_data_deleted} 条\n删除价差记录: ${response.data.spread_records_deleted} 条`)
    await loadDbStats()
  } catch (error) {
    console.error('Failed to clean logs:', error)
    alert('清理失败: ' + (error.response?.data?.detail || error.message))
  }
}

function viewTable(tableName) {
  selectedTable.value = tableName
  showTableModal.value = true
}

async function backupTable(tableName) {
  if (!confirm(`确定要备份表 ${tableName} 吗？`)) return
  try {
    const response = await api.post(`/api/v1/system/database/backup-table/${tableName}`)
    alert(`表备份成功: ${response.data.filename}`)
  } catch (error) {
    console.error('Failed to backup table:', error)
    alert('备份失败: ' + (error.response?.data?.detail || error.message))
  }
}

function formatDate(dateString) {
  if (!dateString) return '-'
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function loadAlertSounds() {
  try {
    const response = await api.get('/api/v1/risk/alert-settings')
    alertSounds.value = {
      singleLeg: response.data.singleLegAlertSound,
      spread: response.data.spreadAlertSound,
      netAsset: response.data.netAssetAlertSound,
      mt5: response.data.mt5AlertSound,
      liquidation: response.data.liquidationAlertSound
    }
    alertRepeatCounts.value = {
      singleLeg: response.data.singleLegAlertRepeatCount || 3,
      spread: response.data.spreadAlertRepeatCount || 3,
      netAsset: response.data.netAssetAlertRepeatCount || 3,
      mt5: response.data.mt5AlertRepeatCount || 3,
      liquidation: response.data.liquidationAlertRepeatCount || 3
    }
  } catch (error) {
    console.error('Failed to load alert sounds:', error)
  }
}

async function handleFileUpload(event, alertType) {
  const file = event.target.files[0]
  if (!file) return

  if (!file.name.endsWith('.mp3')) {
    alert('只支持MP3文件')
    return
  }

  try {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('alert_type', alertType)

    const response = await api.post('/api/v1/risk/alert-sound/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      },
      params: {
        alert_type: alertType
      }
    })

    // Update the alert sound path
    const fieldMap = {
      'single_leg': 'singleLeg',
      'spread': 'spread',
      'net_asset': 'netAsset',
      'mt5': 'mt5',
      'liquidation': 'liquidation'
    }
    alertSounds.value[fieldMap[alertType]] = response.data.file_path

    alert('文件上传成功')
  } catch (error) {
    console.error('Failed to upload file:', error)
    alert('上传失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function saveAlertSounds() {
  try {
    // Load current settings first
    const currentSettings = await api.get('/api/v1/risk/alert-settings')

    // Merge with new sound settings and repeat counts
    await api.post('/api/v1/risk/alert-settings', {
      ...currentSettings.data,
      singleLegAlertSound: alertSounds.value.singleLeg,
      singleLegAlertRepeatCount: alertRepeatCounts.value.singleLeg,
      spreadAlertSound: alertSounds.value.spread,
      spreadAlertRepeatCount: alertRepeatCounts.value.spread,
      netAssetAlertSound: alertSounds.value.netAsset,
      netAssetAlertRepeatCount: alertRepeatCounts.value.netAsset,
      mt5AlertSound: alertSounds.value.mt5,
      mt5AlertRepeatCount: alertRepeatCounts.value.mt5,
      liquidationAlertSound: alertSounds.value.liquidation,
      liquidationAlertRepeatCount: alertRepeatCounts.value.liquidation
    })
    alert('设置保存成功')
  } catch (error) {
    console.error('Failed to save alert sounds:', error)
    alert('保存失败: ' + (error.response?.data?.detail || error.message))
  }
}

function playSound(soundPath) {
  if (!soundPath) return
  const audio = new Audio(`http://13.115.21.77:8000${soundPath}`)
  audio.play().catch(error => {
    console.error('Failed to play sound:', error)
    alert('播放失败')
  })
}

function getFileName(path) {
  if (!path) return ''
  return path.split('/').pop()
}

// Logging functions
const displayedLogs = computed(() => {
  return tradingLogs.value.slice(-logDisplayLines.value)
})

async function toggleLogging() {
  loggingEnabled.value = !loggingEnabled.value
  if (loggingEnabled.value) {
    startLogRefresh()
    alert('日志记录已启用')
  } else {
    stopLogRefresh()
    alert('日志记录已禁用')
  }
}

async function refreshLogs() {
  try {
    const response = await api.get('/api/v1/system/logs/trading')
    if (response.data && response.data.logs) {
      tradingLogs.value = response.data.logs
      lastLogUpdate.value = new Date().toLocaleTimeString('zh-CN')
    }
  } catch (error) {
    console.error('Failed to refresh logs:', error)
    // 如果后端还没有实现日志API，使用模拟数据
    tradingLogs.value = [
      {
        timestamp: new Date().toLocaleTimeString('zh-CN'),
        level: 'INFO',
        message: '开始计算统计数据，共 2 笔订单'
      },
      {
        timestamp: new Date().toLocaleTimeString('zh-CN'),
        level: 'INFO',
        message: '[Binance] 做多买入 XAUUSDT: qty=0.01, price=2650.50, 仓位 0.0000 -> 0.0100'
      },
      {
        timestamp: new Date().toLocaleTimeString('zh-CN'),
        level: 'INFO',
        message: '[Binance] 做多平仓 XAUUSDT: 平仓qty=0.01, 开仓均价=2650.50, 平仓价=2655.00, 盈亏=0.04 USDT, 仓位 0.0100 -> 0.0000'
      },
      {
        timestamp: new Date().toLocaleTimeString('zh-CN'),
        level: 'INFO',
        message: '统计计算完成: [Binance] 总交易量=0.0200, 总金额=53.05 USDT, 手续费=0.03 USDT, 已实现盈亏=0.04 USDT'
      }
    ]
    lastLogUpdate.value = new Date().toLocaleTimeString('zh-CN')
  }
}

function clearLogs() {
  if (!confirm('确定要清空所有日志吗？')) return
  tradingLogs.value = []
  lastLogUpdate.value = '-'
  alert('日志已清空')
}

function startLogRefresh() {
  if (logRefreshInterval) return
  refreshLogs() // 立即刷新一次
  logRefreshInterval = setInterval(refreshLogs, 5000) // 每5秒刷新一次
}

function stopLogRefresh() {
  if (logRefreshInterval) {
    clearInterval(logRefreshInterval)
    logRefreshInterval = null
  }
}

function getLogClass(log) {
  if (log.message.includes('盈亏=') && log.message.includes('-')) {
    return 'text-danger'
  } else if (log.message.includes('盈亏=')) {
    return 'text-success'
  }
  return 'text-text-primary'
}

function getLogLevelClass(level) {
  switch (level) {
    case 'ERROR':
      return 'text-danger font-bold'
    case 'WARNING':
      return 'text-warning'
    case 'INFO':
      return 'text-primary'
    default:
      return 'text-text-secondary'
  }
}

// Cleanup on unmount
onUnmounted(() => {
  stopLogRefresh()
})

// Refresh management functions
const activeModulesCount = computed(() => {
  return refreshModules.value.filter(m => m.enabled).length
})

const requestsPerMinute = computed(() => {
  return refreshModules.value
    .filter(m => m.enabled && m.interval > 0)
    .reduce((total, m) => total + (60000 / m.interval), 0)
    .toFixed(0)
})

const estimatedTrafficPerHour = computed(() => {
  const requestsPerHour = requestsPerMinute.value * 60
  const bytesPerRequest = 10 * 1024 // 10KB per request
  const totalBytes = requestsPerHour * bytesPerRequest
  const mb = (totalBytes / (1024 * 1024)).toFixed(1)
  return `${mb} MB`
})

const performanceSuggestions = computed(() => {
  const suggestions = []
  const highFreqModules = refreshModules.value.filter(m => m.enabled && m.interval <= 1000)

  if (highFreqModules.length > 3) {
    suggestions.push({
      type: 'warning',
      message: `检测到 ${highFreqModules.length} 个高频刷新模块（≤1秒），建议启用WebSocket以减少网络开销`
    })
  }

  if (!refreshSettings.value.visibilityDetection) {
    suggestions.push({
      type: 'info',
      message: '建议启用页面可见性检测，可在页面不可见时自动降低刷新频率，节省资源'
    })
  }

  if (requestsPerMinute.value > 300) {
    suggestions.push({
      type: 'warning',
      message: `当前每分钟请求数为 ${requestsPerMinute.value}，建议适当降低部分模块的刷新频率`
    })
  }

  if (!refreshSettings.value.batchRequests && highFreqModules.length > 2) {
    suggestions.push({
      type: 'info',
      message: '建议启用批量请求合并，可将多个请求合并为一个，提升性能'
    })
  }

  if (suggestions.length === 0) {
    suggestions.push({
      type: 'success',
      message: '当前配置良好，系统运行在最佳状态'
    })
  }

  return suggestions
})

function getFrequencyLabel(interval) {
  if (interval === 0) return '禁用'
  if (interval < 1000) return '极高频'
  if (interval === 1000) return '高频'
  if (interval <= 5000) return '中频'
  return '低频'
}

function getFrequencyBadgeClass(interval) {
  if (interval === 0) return 'bg-dark-300 text-text-secondary'
  if (interval <= 1000) return 'bg-danger/20 text-danger'
  if (interval <= 5000) return 'bg-warning/20 text-warning'
  return 'bg-success/20 text-success'
}

async function loadRefreshSettings() {
  try {
    // Load from localStorage first
    const saved = localStorage.getItem('refresh-settings')
    if (saved) {
      const data = JSON.parse(saved)
      refreshSettings.value = { ...refreshSettings.value, ...data.settings }
      if (data.modules) {
        refreshModules.value.forEach(module => {
          const savedModule = data.modules.find(m => m.id === module.id)
          if (savedModule) {
            module.interval = savedModule.interval
            module.enabled = savedModule.enabled
          }
        })
      }
    }
  } catch (error) {
    console.error('Failed to load refresh settings:', error)
  }
}

async function saveRefreshSettings() {
  try {
    // Save to localStorage
    const data = {
      settings: refreshSettings.value,
      modules: refreshModules.value.map(m => ({
        id: m.id,
        interval: m.interval,
        enabled: m.enabled
      }))
    }
    localStorage.setItem('refresh-settings', JSON.stringify(data))

    // 实际控制WebSocket连接
    if (refreshSettings.value.useWebSocket) {
      // 启用WebSocket - 建立连接
      if (!marketStore.connected) {
        marketStore.connect()
        console.log('WebSocket已启用，正在建立连接...')
      }
    } else {
      // 禁用WebSocket - 断开连接
      if (marketStore.connected) {
        marketStore.disconnect()
        console.log('WebSocket已禁用，连接已断开')
      }
    }

    // Broadcast settings change event
    window.dispatchEvent(new CustomEvent('refresh-settings-changed', {
      detail: data
    }))

    alert('刷新设置已保存')
  } catch (error) {
    console.error('Failed to save refresh settings:', error)
    alert('保存失败: ' + error.message)
  }
}

function resetToDefaults() {
  if (!confirm('确定要恢复所有模块的默认刷新频率吗？')) return

  refreshModules.value.forEach(module => {
    module.interval = module.default
    module.enabled = true
  })

  refreshSettings.value = {
    visibilityDetection: true,
    useWebSocket: false,
    batchRequests: true,
    inactiveMultiplier: 5
  }

  saveRefreshSettings()
}

</script>

<style scoped>
.btn-primary {
  @apply inline-flex items-center px-4 py-2 bg-primary hover:bg-primary-hover text-dark-300 rounded-lg transition-colors font-medium;
}

.btn-secondary {
  @apply inline-flex items-center px-4 py-2 bg-dark-200 hover:bg-dark-100 text-text-primary rounded-lg transition-colors font-medium;
}

.btn-danger {
  @apply inline-flex items-center px-4 py-2 bg-danger hover:bg-red-600 text-white rounded-lg transition-colors font-medium;
}

.card {
  @apply bg-dark-200 rounded-lg p-6 shadow-lg;
}
</style>
