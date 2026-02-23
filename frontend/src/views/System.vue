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
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import TableDetailModal from '@/components/modals/TableDetailModal.vue'
import BackupSelectModal from '@/components/modals/BackupSelectModal.vue'

const activeTab = ref('users')
const tabs = [
  { id: 'users', label: '前端用户管理' },
  { id: 'version', label: '系统版本管理' },
  { id: 'database', label: 'PostgreSQL数据库管理' },
  { id: 'alerts', label: '提醒声音设置' }
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

onMounted(async () => {
  await loadUsers()
  await loadSystemInfo()
  await loadDbStats()
  await loadVersionHistory()
  await loadAlertSounds()
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
