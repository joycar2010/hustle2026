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
                  <!-- Stop icon when playing -->
                  <svg v-if="playingSound === alertSounds.singleLeg" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10h6v4H9z" />
                  </svg>
                  <!-- Play icon when not playing -->
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                  <!-- Stop icon when playing -->
                  <svg v-if="playingSound === alertSounds.spread" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10h6v4H9z" />
                  </svg>
                  <!-- Play icon when not playing -->
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                  <!-- Stop icon when playing -->
                  <svg v-if="playingSound === alertSounds.netAsset" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10h6v4H9z" />
                  </svg>
                  <!-- Play icon when not playing -->
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                  <!-- Stop icon when playing -->
                  <svg v-if="playingSound === alertSounds.mt5" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10h6v4H9z" />
                  </svg>
                  <!-- Play icon when not playing -->
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                  <!-- Stop icon when playing -->
                  <svg v-if="playingSound === alertSounds.liquidation" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10h6v4H9z" />
                  </svg>
                  <!-- Play icon when not playing -->
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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



      <!-- RBAC权限管理 Tab -->
      <div v-if="activeTab === 'rbac'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">角色权限管理</h2>
            <div class="flex space-x-3">
              <button @click="openAddRoleModal" class="btn-primary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                </svg>
                添加角色
              </button>
              <button @click="loadRoles" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">角色名称</th>
                  <th class="text-left py-3 px-4">角色代码</th>
                  <th class="text-left py-3 px-4">描述</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">创建时间</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="role in roles" :key="role.role_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4">{{ role.role_name }}</td>
                  <td class="py-3 px-4 font-mono text-sm">{{ role.role_code }}</td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ role.description || '-' }}</td>
                  <td class="py-3 px-4">
                    <span :class="role.is_active ? 'text-success' : 'text-danger'">
                      {{ role.is_active ? '启用' : '禁用' }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ formatDate(role.created_at) }}</td>
                  <td class="py-3 px-4">
                    <button @click="editRole(role)" class="text-primary hover:text-blue-400 mr-2">编辑</button>
                    <button @click="managePermissions(role)" class="text-success hover:text-green-400 mr-2">权限</button>
                    <button v-if="!role.is_system" @click="deleteRole(role.role_id)" class="text-danger hover:text-red-400">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="roles.length === 0" class="text-center py-8 text-text-secondary">
              暂无角色数据
            </div>
          </div>
        </div>
      </div>

      <!-- SSL证书管理 Tab -->
      <div v-if="activeTab === 'ssl'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">SSL证书管理</h2>
            <div class="flex space-x-3">
              <button @click="openUploadCertModal" class="btn-primary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                上传证书
              </button>
              <button @click="loadCertificates" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">证书名称</th>
                  <th class="text-left py-3 px-4">域名</th>
                  <th class="text-left py-3 px-4">类型</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">过期时间</th>
                  <th class="text-left py-3 px-4">剩余天数</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="cert in certificates" :key="cert.cert_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4">{{ cert.cert_name }}</td>
                  <td class="py-3 px-4 font-mono text-sm">{{ cert.domain_name }}</td>
                  <td class="py-3 px-4 text-sm">{{ getCertTypeLabel(cert.cert_type) }}</td>
                  <td class="py-3 px-4">
                    <span :class="getCertStatusClass(cert.status)">
                      {{ getCertStatusLabel(cert.status) }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ formatDate(cert.expires_at) }}</td>
                  <td class="py-3 px-4">
                    <span :class="cert.days_before_expiry <= 30 ? 'text-danger' : 'text-success'">
                      {{ cert.days_before_expiry }} 天
                    </span>
                  </td>
                  <td class="py-3 px-4">
                    <button @click="viewCertDetails(cert)" class="text-primary hover:text-blue-400 mr-2">详情</button>
                    <button @click="deleteCertificate(cert.cert_id)" class="text-danger hover:text-red-400">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="certificates.length === 0" class="text-center py-8 text-text-secondary">
              暂无证书数据
            </div>
          </div>
        </div>
      </div>


      <!-- 安全组件管理 Tab -->
      <div v-if="activeTab === 'security'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">安全组件管理</h2>
            <button @click="loadSecurityComponents" class="btn-secondary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              刷新
            </button>
          </div>

          <!-- Component Type Filters -->
          <div class="flex space-x-2 mb-4">
            <button
              v-for="type in componentTypes"
              :key="type.value"
              @click="filterComponentType = type.value"
              :class="[
                'px-4 py-2 rounded text-sm font-medium transition-colors',
                filterComponentType === type.value
                  ? 'bg-primary text-white'
                  : 'bg-dark-200 text-text-secondary hover:bg-dark-300'
              ]"
            >
              {{ type.label }}
            </button>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">组件名称</th>
                  <th class="text-left py-3 px-4">组件代码</th>
                  <th class="text-left py-3 px-4">类型</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">优先级</th>
                  <th class="text-left py-3 px-4">最后检查</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="component in filteredComponents" :key="component.component_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4">
                    <div class="font-medium">{{ component.component_name }}</div>
                    <div class="text-xs text-text-secondary">{{ component.description }}</div>
                  </td>
                  <td class="py-3 px-4 font-mono text-sm">{{ component.component_code }}</td>
                  <td class="py-3 px-4">
                    <span class="px-2 py-1 rounded text-xs" :class="getComponentTypeClass(component.component_type)">
                      {{ getComponentTypeLabel(component.component_type) }}
                    </span>
                  </td>
                  <td class="py-3 px-4">
                    <div class="flex items-center space-x-2">
                      <span :class="component.is_enabled ? 'text-success' : 'text-text-secondary'">
                        {{ component.is_enabled ? '已启用' : '已禁用' }}
                      </span>
                      <span v-if="component.status === 'error'" class="text-danger text-xs">(错误)</span>
                    </div>
                  </td>
                  <td class="py-3 px-4">{{ component.priority }}</td>
                  <td class="py-3 px-4 text-text-secondary text-sm">
                    {{ component.last_check_at ? formatDate(component.last_check_at) : '-' }}
                  </td>
                  <td class="py-3 px-4">
                    <button
                      v-if="!component.is_enabled"
                      @click="enableComponent(component)"
                      class="text-success hover:text-green-400 mr-2"
                    >
                      启用
                    </button>
                    <button
                      v-if="component.is_enabled"
                      @click="disableComponent(component)"
                      class="text-warning hover:text-yellow-400 mr-2"
                    >
                      禁用
                    </button>
                    <button @click="configureComponent(component)" class="text-primary hover:text-blue-400 mr-2">
                      配置
                    </button>
                    <button @click="viewComponentLogs(component)" class="text-text-secondary hover:text-text-primary">
                      日志
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="filteredComponents.length === 0" class="text-center py-8 text-text-secondary">
              暂无安全组件数据
            </div>
          </div>
        </div>

        <!-- Statistics -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">总组件数</div>
            <div class="text-2xl font-bold">{{ securityComponents.length }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">已启用</div>
            <div class="text-2xl font-bold text-success">{{ enabledComponentsCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">已禁用</div>
            <div class="text-2xl font-bold text-text-secondary">{{ disabledComponentsCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">错误状态</div>
            <div class="text-2xl font-bold text-danger">{{ errorComponentsCount }}</div>
          </div>
        </div>
      </div>


      <!-- 用户管理 Tab -->
      <div v-if="activeTab === 'users'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">用户管理</h2>
            <div class="flex space-x-3">
              <button @click="openAddUserModal" class="btn-primary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                </svg>
                添加用户
              </button>
              <button @click="loadUsers" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">用户名</th>
                  <th class="text-left py-3 px-4">邮箱</th>
                  <th class="text-left py-3 px-4">RBAC角色</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">创建时间</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in users" :key="user.user_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4 font-medium">{{ user.username }}</td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ user.email }}</td>
                  <td class="py-3 px-4">
                    <div class="flex flex-wrap gap-1">
                      <span
                        v-for="rbacRole in user.rbac_roles"
                        :key="rbacRole.role_id"
                        class="px-2 py-1 rounded text-xs bg-success text-white"
                      >
                        {{ rbacRole.role_name }}
                      </span>
                      <span v-if="!user.rbac_roles || user.rbac_roles.length === 0" class="text-xs text-text-secondary">
                        未分配
                      </span>
                    </div>
                  </td>
                  <td class="py-3 px-4">
                    <span :class="user.is_active ? 'text-success' : 'text-danger'">
                      {{ user.is_active ? '启用' : '禁用' }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-text-secondary text-sm">
                    {{ formatDate(user.create_time) }}
                  </td>
                  <td class="py-3 px-4">
                    <button @click="editUser(user)" class="text-primary hover:text-blue-400 mr-2">编辑</button>
                    <button @click="assignUserRoles(user)" class="text-success hover:text-green-400 mr-2">分配角色</button>
                    <button @click="toggleUserStatus(user)" :class="user.is_active ? 'text-warning hover:text-yellow-400 mr-2' : 'text-success hover:text-green-400 mr-2'">
                      {{ user.is_active ? '禁用' : '启用' }}
                    </button>
                    <button @click="deleteUser(user)" class="text-danger hover:text-red-400">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="users.length === 0" class="text-center py-8 text-text-secondary">
              暂无用户数据
            </div>
          </div>
        </div>

        <!-- Statistics -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">总用户数</div>
            <div class="text-2xl font-bold">{{ users.length }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">启用用户</div>
            <div class="text-2xl font-bold text-success">{{ activeUsersCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">禁用用户</div>
            <div class="text-2xl font-bold text-danger">{{ inactiveUsersCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">管理员</div>
            <div class="text-2xl font-bold text-warning">{{ adminUsersCount }}</div>
          </div>
        </div>
      </div>


      <!-- 系统日志管理 Tab -->
      <div v-if="activeTab === 'systemlogs'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">系统日志管理</h2>
            <div class="flex space-x-3">
              <button @click="clearOldLogs" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                清理旧日志
              </button>
              <button @click="loadSystemLogs" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新
              </button>
            </div>
          </div>

          <!-- Filters -->
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
            <div>
              <label class="block text-sm font-medium mb-2">日志级别</label>
              <select
                v-model="logFilters.level"
                @change="loadSystemLogs"
                class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              >
                <option value="">全部</option>
                <option value="info">INFO</option>
                <option value="warning">WARNING</option>
                <option value="error">ERROR</option>
                <option value="critical">CRITICAL</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium mb-2">日志类别</label>
              <select
                v-model="logFilters.category"
                @change="loadSystemLogs"
                class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              >
                <option value="">全部</option>
                <option value="api">API</option>
                <option value="trade">交易</option>
                <option value="system">系统</option>
                <option value="auth">认证</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium mb-2">显示数量</label>
              <select
                v-model="logFilters.limit"
                @change="loadSystemLogs"
                class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
              >
                <option :value="50">50条</option>
                <option :value="100">100条</option>
                <option :value="200">200条</option>
                <option :value="500">500条</option>
              </select>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">时间</th>
                  <th class="text-left py-3 px-4">级别</th>
                  <th class="text-left py-3 px-4">类别</th>
                  <th class="text-left py-3 px-4">消息</th>
                  <th class="text-left py-3 px-4">用户</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="log in systemLogs" :key="log.log_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4 text-sm text-text-secondary whitespace-nowrap">
                    {{ formatDate(log.timestamp) }}
                  </td>
                  <td class="py-3 px-4">
                    <span :class="getLogLevelClass(log.level)" class="px-2 py-1 rounded text-xs font-medium">
                      {{ log.level.toUpperCase() }}
                    </span>
                  </td>
                  <td class="py-3 px-4">
                    <span :class="getLogCategoryClass(log.category)" class="px-2 py-1 rounded text-xs">
                      {{ getLogCategoryLabel(log.category) }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-sm">
                    <div class="max-w-md truncate">{{ log.message }}</div>
                  </td>
                  <td class="py-3 px-4 text-sm text-text-secondary">
                    {{ log.user_id ? log.user_id.substring(0, 8) : '-' }}
                  </td>
                  <td class="py-3 px-4">
                    <button @click="viewLogDetails(log)" class="text-primary hover:text-blue-400">
                      详情
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="systemLogs.length === 0" class="text-center py-8 text-text-secondary">
              暂无日志数据
            </div>
          </div>
        </div>

        <!-- Statistics -->
        <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">总日志数</div>
            <div class="text-2xl font-bold">{{ systemLogs.length }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">INFO</div>
            <div class="text-2xl font-bold text-primary">{{ infoLogsCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">WARNING</div>
            <div class="text-2xl font-bold text-warning">{{ warningLogsCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">ERROR</div>
            <div class="text-2xl font-bold text-danger">{{ errorLogsCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">CRITICAL</div>
            <div class="text-2xl font-bold text-danger">{{ criticalLogsCount }}</div>
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

    <BackupActionModal
      :show="showBackupActionModal"
      title="备份数据库"
      githubLabel="备份至 GitHub"
      githubDesc="将数据库备份推送到 GitHub 仓库"
      serverLabel="备份至服务器"
      serverDesc="将数据库备份保存到本地服务器"
      @close="showBackupActionModal = false"
      @select="handleBackupSelect"
    />

    <BackupActionModal
      :show="showRestoreActionModal"
      title="恢复数据库"
      githubLabel="从 GitHub 还原"
      githubDesc="从 GitHub 仓库的历史版本还原"
      serverLabel="从服务器还原"
      serverDesc="从本地服务器的备份文件还原"
      @close="showRestoreActionModal = false"
      @select="handleRestoreSelect"
    />
  </div>

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


    <!-- Permission Management Modal -->
    <div v-if="showPermissionModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <h3 class="text-xl font-bold mb-4">权限管理 - {{ currentRole?.role_name }}</h3>

        <div class="mb-4 flex justify-between items-center">
          <div class="text-sm text-text-secondary">
            已选择 {{ selectedPermissions.length }} 个权限
          </div>
          <div class="flex space-x-2">
            <button @click="selectAllPermissions" class="btn-secondary text-sm">全选</button>
            <button @click="clearAllPermissions" class="btn-secondary text-sm">清空</button>
          </div>
        </div>

        <!-- Permission Categories -->
        <div class="space-y-4">
          <!-- API Permissions -->
          <div class="bg-dark-200 rounded p-4">
            <h4 class="font-bold mb-3 flex items-center">
              <svg class="w-5 h-5 mr-2 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              API接口权限
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              <div v-for="perm in apiPermissions" :key="perm.permission_id" class="flex items-start">
                <input
                  type="checkbox"
                  :id="'perm-' + perm.permission_id"
                  :value="perm.permission_id"
                  v-model="selectedPermissions"
                  class="mt-1 mr-2"
                />
                <label :for="'perm-' + perm.permission_id" class="text-sm cursor-pointer">
                  <div class="font-medium">{{ perm.permission_name }}</div>
                  <div class="text-xs text-text-secondary">{{ perm.description || perm.resource_path }}</div>
                </label>
              </div>
            </div>
            <div v-if="apiPermissions.length === 0" class="text-sm text-text-secondary text-center py-4">
              暂无API权限
            </div>
          </div>

          <!-- Menu Permissions -->
          <div class="bg-dark-200 rounded p-4">
            <h4 class="font-bold mb-3 flex items-center">
              <svg class="w-5 h-5 mr-2 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
              菜单导航权限
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              <div v-for="perm in menuPermissions" :key="perm.permission_id" class="flex items-start">
                <input
                  type="checkbox"
                  :id="'perm-' + perm.permission_id"
                  :value="perm.permission_id"
                  v-model="selectedPermissions"
                  class="mt-1 mr-2"
                />
                <label :for="'perm-' + perm.permission_id" class="text-sm cursor-pointer">
                  <div class="font-medium">{{ perm.permission_name }}</div>
                  <div class="text-xs text-text-secondary">{{ perm.description || perm.resource_path }}</div>
                </label>
              </div>
            </div>
            <div v-if="menuPermissions.length === 0" class="text-sm text-text-secondary text-center py-4">
              暂无菜单权限
            </div>
          </div>

          <!-- Button Permissions -->
          <div class="bg-dark-200 rounded p-4">
            <h4 class="font-bold mb-3 flex items-center">
              <svg class="w-5 h-5 mr-2 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122" />
              </svg>
              按钮操作权限
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              <div v-for="perm in buttonPermissions" :key="perm.permission_id" class="flex items-start">
                <input
                  type="checkbox"
                  :id="'perm-' + perm.permission_id"
                  :value="perm.permission_id"
                  v-model="selectedPermissions"
                  class="mt-1 mr-2"
                />
                <label :for="'perm-' + perm.permission_id" class="text-sm cursor-pointer">
                  <div class="font-medium">{{ perm.permission_name }}</div>
                  <div class="text-xs text-text-secondary">{{ perm.description || perm.resource_path }}</div>
                </label>
              </div>
            </div>
            <div v-if="buttonPermissions.length === 0" class="text-sm text-text-secondary text-center py-4">
              暂无按钮权限
            </div>
          </div>
        </div>

        <div class="flex justify-end space-x-3 mt-6">
          <button @click="closePermissionModal" class="btn-secondary">取消</button>
          <button @click="savePermissions" class="btn-primary">保存权限</button>
        </div>
      </div>
    </div>


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


    <!-- System Log Detail Modal -->
    <div v-if="showSystemLogDetailModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click="showSystemLogDetailModal = false">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto" @click.stop>
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-xl font-bold">日志详情</h3>
          <button @click="showSystemLogDetailModal = false" class="text-text-secondary hover:text-text-primary text-2xl leading-none">&times;</button>
        </div>
        <div v-if="selectedSystemLog" class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-text-secondary mb-1">日志ID</label>
              <div class="text-text-primary">{{ selectedSystemLog.log_id }}</div>
            </div>
            <div>
              <label class="block text-sm font-medium text-text-secondary mb-1">时间</label>
              <div class="text-text-primary">{{ formatDate(selectedSystemLog.timestamp) }}</div>
            </div>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-text-secondary mb-1">级别</label>
              <span :class="getLogLevelClass(selectedSystemLog.level)" class="inline-block px-3 py-1 rounded text-sm font-medium">
                {{ selectedSystemLog.level.toUpperCase() }}
              </span>
            </div>
            <div>
              <label class="block text-sm font-medium text-text-secondary mb-1">分类</label>
              <span :class="getLogCategoryClass(selectedSystemLog.category)" class="inline-block px-3 py-1 rounded text-sm">
                {{ getLogCategoryLabel(selectedSystemLog.category) }}
              </span>
            </div>
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-1">用户</label>
            <div class="text-text-primary">{{ selectedSystemLog.user_id || 'System' }}</div>
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-1">消息</label>
            <div class="text-text-primary">{{ selectedSystemLog.message }}</div>
          </div>
          <div v-if="selectedSystemLog.details">
            <label class="block text-sm font-medium text-text-secondary mb-1">详细信息</label>
            <pre class="bg-dark-300 p-4 rounded text-sm overflow-x-auto">{{ JSON.stringify(selectedSystemLog.details, null, 2) }}</pre>
          </div>
        </div>
        <div class="flex justify-end mt-6">
          <button @click="showSystemLogDetailModal = false" class="btn-secondary">关闭</button>
        </div>
      </div>
    </div>

</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/services/api'
import TableDetailModal from '@/components/modals/TableDetailModal.vue'
import BackupSelectModal from '@/components/modals/BackupSelectModal.vue'
import BackupActionModal from '@/components/modals/BackupActionModal.vue'
import WebSocketMonitor from '@/components/system/WebSocketMonitor.vue'
import { useMarketStore } from '@/stores/market'

// 引入market store以获取WebSocket连接状态
const marketStore = useMarketStore()
const router = useRouter()

const activeTab = ref('version')

// RBAC state
const roles = ref([])
const showRoleModal = ref(false)
const roleForm = ref({
  role_name: '',
  role_code: '',
  description: '',
  is_active: true
})
const isEditingRole = ref(false)
const editingRoleId = ref(null)

// SSL Certificate state
const certificates = ref([])
const showCertModal = ref(false)

const certForm = ref({
  cert_name: '',
  domain_name: '',
  cert_type: 'ca_signed',
  cert_content: '',
  key_content: '',
  auto_renew: false
})


// Permission management state
const showPermissionModal = ref(false)
const currentRole = ref(null)
const allPermissions = ref([])
const selectedPermissions = ref([])

const apiPermissions = computed(() =>
  allPermissions.value.filter(p => p.resource_type === 'api')
)
const menuPermissions = computed(() =>
  allPermissions.value.filter(p => p.resource_type === 'menu')
)
const buttonPermissions = computed(() =>
  allPermissions.value.filter(p => p.resource_type === 'button')
)


// Security Component state
const securityComponents = ref([])
const filterComponentType = ref('all')
const showConfigModal = ref(false)
const showLogsModal = ref(false)
const currentComponent = ref(null)
const componentConfig = ref({})
const componentLogs = ref([])

const componentTypes = [
  { value: 'all', label: '全部' },
  { value: 'middleware', label: '中间件' },
  { value: 'service', label: '服务' },
  { value: 'protection', label: '防护' }
]

const filteredComponents = computed(() => {
  if (filterComponentType.value === 'all') {
    return securityComponents.value
  }
  return securityComponents.value.filter(c => c.component_type === filterComponentType.value)
})

const enabledComponentsCount = computed(() =>
  securityComponents.value.filter(c => c.is_enabled).length
)

const disabledComponentsCount = computed(() =>
  securityComponents.value.filter(c => !c.is_enabled).length
)

const errorComponentsCount = computed(() =>
  securityComponents.value.filter(c => c.status === 'error').length
)



// User Management state
const users = ref([])
const showUserModal = ref(false)
const showUserRolesModal = ref(false)
const isEditingUser = ref(false)
const currentUser = ref(null)
const userForm = ref({
  username: '',
  email: '',
  password: '',
  role: '交易员',
  is_active: true
})
const selectedUserRoles = ref([])

const activeUsersCount = computed(() =>
  users.value.filter(u => u.is_active).length
)

const inactiveUsersCount = computed(() =>
  users.value.filter(u => !u.is_active).length
)

const adminUsersCount = computed(() =>
  users.value.filter(u => u.role === '管理员').length
)


// System Logs state
const systemLogs = ref([])
const showSystemLogDetailModal = ref(false)
const selectedSystemLog = ref(null)
const showLogDetailModal = ref(false)
const currentLog = ref(null)
const logFilters = ref({
  level: '',
  category: '',
  limit: 100
})

const infoLogsCount = computed(() =>
  systemLogs.value.filter(l => l.level === 'info').length
)

const warningLogsCount = computed(() =>
  systemLogs.value.filter(l => l.level === 'warning').length
)

const errorLogsCount = computed(() =>
  systemLogs.value.filter(l => l.level === 'error').length
)

const criticalLogsCount = computed(() =>
  systemLogs.value.filter(l => l.level === 'critical').length
)

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

const tabs = [
  { id: 'users', label: '用户管理' },
  { id: 'rbac', label: '角色权限管理' },
  { id: 'refresh', label: '刷新管理' },
  { id: 'websocket', label: 'WebSocket监控' },
  { id: 'alerts', label: '提醒声音设置' },
  { id: 'security', label: '安全组件管理' },
  { id: 'ssl', label: 'SSL证书管理' },
  { id: 'systemlogs', label: '系统日志' },
  { id: 'version', label: '系统版本管理' },
  { id: 'database', label: 'PostgreSQL数据库管理' }
]


const showTableModal = ref(false)
const selectedTable = ref('')
const showBackupModal = ref(false)
const showBackupActionModal = ref(false)
const showRestoreActionModal = ref(false)

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

// Audio playback state
const currentAudio = ref(null)
const playingSound = ref(null)

// Logging state


// RBAC Functions
async function loadRoles() {
  try {
    const response = await api.get('/api/v1/rbac/roles')
    roles.value = response.data
  } catch (error) {
    console.error('Failed to load roles:', error)
    alert('加载角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openAddRoleModal() {
  roleForm.value = {
    role_name: '',
    role_code: '',
    description: '',
    is_active: true
  }
  isEditingRole.value = false
  showRoleModal.value = true
}

function editRole(role) {
  roleForm.value = {
    role_name: role.role_name,
    role_code: role.role_code,
    description: role.description || '',
    is_active: role.is_active
  }
  editingRoleId.value = role.role_id
  isEditingRole.value = true
  showRoleModal.value = true
}

async function saveRole() {
  try {
    if (isEditingRole.value) {
      await api.put(`/api/v1/rbac/roles/${editingRoleId.value}`, roleForm.value)
      alert('角色更新成功')
    } else {
      await api.post('/api/v1/rbac/roles', roleForm.value)
      alert('角色创建成功')
    }
    showRoleModal.value = false
    await loadRoles()
  } catch (error) {
    console.error('Failed to save role:', error)
    alert('保存角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function deleteRole(roleId) {
  if (!confirm('确定要删除此角色吗？')) return
  try {
    await api.delete(`/api/v1/rbac/roles/${roleId}`)
    alert('角色删除成功')
    await loadRoles()
  } catch (error) {
    console.error('Failed to delete role:', error)
    alert('删除角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

// SSL Certificate Functions
async function loadCertificates() {
  try {
    const response = await api.get('/api/v1/ssl/certificates')
    certificates.value = response.data
  } catch (error) {
    console.error('Failed to load certificates:', error)
    alert('加载证书失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openUploadCertModal() {
  showCertModal.value = true
}

async function deleteCertificate(certId) {
  if (!confirm('确定要删除此证书吗？')) return
  try {
    await api.delete(`/api/v1/ssl/certificates/${certId}`)
    alert('证书删除成功')
    await loadCertificates()
  } catch (error) {
    console.error('Failed to delete certificate:', error)
    alert('删除证书失败: ' + (error.response?.data?.detail || error.message))
  }
}

function viewCertDetails(cert) {
  alert(`证书详情:\n域名: ${cert.domain_name}\n颁发者: ${cert.issuer || 'N/A'}\n主题: ${cert.subject || 'N/A'}\n序列号: ${cert.serial_number || 'N/A'}`)
}

function getCertTypeLabel(type) {
  const labels = {
    'self_signed': '自签名',
    'ca_signed': 'CA签名',
    'letsencrypt': "Let's Encrypt"
  }
  return labels[type] || type
}

function getCertStatusLabel(status) {
  const labels = {
    'active': '已激活',
    'inactive': '未激活',
    'expired': '已过期',
    'expiring_soon': '即将过期'
  }
  return labels[status] || status
}

function getCertStatusClass(status) {
  const classes = {
    'active': 'text-success',
    'inactive': 'text-text-secondary',
    'expired': 'text-danger',
    'expiring_soon': 'text-warning'
  }
  return classes[status] || 'text-text-secondary'
}






// System Logs Functions
async function loadSystemLogs() {
  try {
    const params = new URLSearchParams()
    if (logFilters.value.level) params.append('level', logFilters.value.level)
    if (logFilters.value.category) params.append('category', logFilters.value.category)
    params.append('limit', logFilters.value.limit)

    const response = await api.get(`/api/v1/system/logs?${params.toString()}`)
    systemLogs.value = response.data.logs || []
  } catch (error) {
    console.error('Failed to load system logs:', error)
    alert('加载系统日志失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function clearOldLogs() {
  if (!confirm('确定要清理7天前的旧日志吗？此操作不可恢复！')) return

  try {
    await api.delete('/api/v1/system/logs/old')
    alert('旧日志清理成功')
    await loadSystemLogs()
  } catch (error) {
    console.error('Failed to clear old logs:', error)
    alert('清理日志失败: ' + (error.response?.data?.detail || error.message))
  }
}

function viewLogDetails(log) {
  selectedSystemLog.value = log
  showSystemLogDetailModal.value = true
}

function getLogLevelClass(level) {
  const classes = {
    'info': 'bg-primary text-white',
    'warning': 'bg-warning text-dark-100',
    'error': 'bg-danger text-white',
    'critical': 'bg-danger text-white'
  }
  return classes[level] || 'bg-dark-300 text-text-secondary'
}

function getLogCategoryClass(category) {
  const classes = {
    'api': 'bg-blue-500 text-white',
    'trade': 'bg-green-500 text-white',
    'system': 'bg-purple-500 text-white',
    'auth': 'bg-yellow-500 text-dark-100'
  }
  return classes[category] || 'bg-dark-300 text-text-secondary'
}

function getLogCategoryLabel(category) {
  const labels = {
    'api': 'API',
    'trade': '交易',
    'system': '系统',
    'auth': '认证'
  }
  return labels[category] || category
}

// User Management Functions
async function loadUsers() {
  try {
    const response = await api.get('/api/v1/users/')
    users.value = response.data
  } catch (error) {
    console.error('Failed to load users:', error)
    alert('加载用户失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openAddUserModal() {
  userForm.value = {
    username: '',
    email: '',
    password: '',
    role: '交易员',
    is_active: true
  }
  isEditingUser.value = false
  showUserModal.value = true
}

function editUser(user) {
  userForm.value = {
    username: user.username,
    email: user.email,
    password: '',
    role: user.role,
    is_active: user.is_active
  }
  currentUser.value = user
  isEditingUser.value = true
  showUserModal.value = true
}

async function saveUser() {
  try {
    if (!userForm.value.username || !userForm.value.email) {
      alert('请填写用户名和邮箱')
      return
    }

    if (!isEditingUser.value && !userForm.value.password) {
      alert('请填写密码')
      return
    }

    if (isEditingUser.value) {
      const updateData = {
        email: userForm.value.email,
        role: userForm.value.role,
        is_active: userForm.value.is_active
      }
      if (userForm.value.password) {
        updateData.password = userForm.value.password
      }
      await api.put(`/api/v1/users/${currentUser.value.user_id}`, updateData)
      alert('用户更新成功')
    } else {
      await api.post('/api/v1/users/', userForm.value)
      alert('用户创建成功')
    }

    showUserModal.value = false
    await loadUsers()
  } catch (error) {
    console.error('Failed to save user:', error)
    alert('保存用户失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function toggleUserStatus(user) {
  const action = user.is_active ? '禁用' : '启用'
  if (!confirm(`确定要${action}用户"${user.username}"吗？`)) return

  try {
    await api.put(`/api/v1/users/${user.user_id}`, {
      is_active: !user.is_active
    })
    alert(`用户${action}成功`)
    await loadUsers()
  } catch (error) {
    console.error('Failed to toggle user status:', error)
    alert(`${action}用户失败: ` + (error.response?.data?.detail || error.message))
  }
}

async function deleteUser(user) {
  if (!confirm(`确定要删除用户"${user.username}"吗？此操作不可恢复！`)) return

  try {
    await api.delete(`/api/v1/users/${user.user_id}`)
    alert('用户删除成功')
    await loadUsers()
  } catch (error) {
    console.error('Failed to delete user:', error)
    alert('删除用户失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function assignUserRoles(user) {
  try {
    currentUser.value = user

    // Load all roles if not loaded
    if (roles.value.length === 0) {
      await loadRoles()
    }

    // Set selected roles
    selectedUserRoles.value = user.rbac_roles ? user.rbac_roles.map(r => r.role_id) : []

    showUserRolesModal.value = true
  } catch (error) {
    console.error('Failed to load user roles:', error)
    alert('加载用户角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function saveUserRoles() {
  try {
    await api.post(`/api/v1/rbac/users/${currentUser.value.user_id}/roles`, {
      role_ids: selectedUserRoles.value
    })

    alert('角色分配成功')
    showUserRolesModal.value = false
    await loadUsers()
  } catch (error) {
    console.error('Failed to save user roles:', error)
    alert('保存用户角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

// Security Component Functions
async function loadSecurityComponents() {
  try {
    const response = await api.get('/api/v1/security/components')
    securityComponents.value = response.data
  } catch (error) {
    console.error('Failed to load security components:', error)
    alert('加载安全组件失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function enableComponent(component) {
  if (!confirm(`确定要启用组件"${component.component_name}"吗？`)) return
  try {
    await api.post(`/api/v1/security/components/${component.component_id}/enable`, {
      reason: '手动启用'
    })
    alert('组件启用成功')
    await loadSecurityComponents()
  } catch (error) {
    console.error('Failed to enable component:', error)
    alert('启用组件失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function disableComponent(component) {
  if (!confirm(`确定要禁用组件"${component.component_name}"吗？`)) return
  try {
    await api.post(`/api/v1/security/components/${component.component_id}/disable`, {
      reason: '手动禁用'
    })
    alert('组件禁用成功')
    await loadSecurityComponents()
  } catch (error) {
    console.error('Failed to disable component:', error)
    alert('禁用组件失败: ' + (error.response?.data?.detail || error.message))
  }
}

function configureComponent(component) {
  currentComponent.value = component
  componentConfig.value = component.config_json || {}
  showConfigModal.value = true
}

async function saveComponentConfig() {
  try {
    await api.put(`/api/v1/security/components/${currentComponent.value.component_id}/config`, {
      config_json: componentConfig.value
    })
    alert('配置保存成功')
    showConfigModal.value = false
    await loadSecurityComponents()
  } catch (error) {
    console.error('Failed to save config:', error)
    alert('保存配置失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function viewComponentLogs(component) {
  try {
    currentComponent.value = component
    const response = await api.get(`/api/v1/security/components/${component.component_id}/logs`)
    componentLogs.value = response.data
    showLogsModal.value = true
  } catch (error) {
    console.error('Failed to load logs:', error)
    alert('加载日志失败: ' + (error.response?.data?.detail || error.message))
  }
}


function getActionLabel(action) {
  const labels = {
    'enable': '启用',
    'disable': '禁用',
    'config_update': '配置更新',
    'error': '错误'
  }
  return labels[action] || action
}

function getComponentTypeLabel(type) {
  const labels = {
    'middleware': '中间件',
    'service': '服务',
    'protection': '防护'
  }
  return labels[type] || type
}

function getComponentTypeClass(type) {
  const classes = {
    'middleware': 'bg-primary text-white',
    'service': 'bg-success text-white',
    'protection': 'bg-warning text-dark-100'
  }
  return classes[type] || 'bg-dark-300 text-text-secondary'
}

// Permission Management Functions
async function loadAllPermissions() {
  try {
    const response = await api.get('/api/v1/rbac/permissions')
    allPermissions.value = response.data
  } catch (error) {
    console.error('Failed to load permissions:', error)
  }
}

async function managePermissions(role) {
  try {
    currentRole.value = role

    // Load all permissions if not loaded
    if (allPermissions.value.length === 0) {
      await loadAllPermissions()
    }

    // Load role's current permissions
    const response = await api.get(`/api/v1/rbac/roles/${role.role_id}`)
    selectedPermissions.value = response.data.permissions.map(p => p.permission_id)

    showPermissionModal.value = true
  } catch (error) {
    console.error('Failed to load role permissions:', error)
    alert('加载角色权限失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function savePermissions() {
  try {
    await api.post(`/api/v1/rbac/roles/${currentRole.value.role_id}/permissions`, {
      permission_ids: selectedPermissions.value
    })

    alert('权限保存成功')
    closePermissionModal()
  } catch (error) {
    console.error('Failed to save permissions:', error)
    alert('保存权限失败: ' + (error.response?.data?.detail || error.message))
  }
}

function closePermissionModal() {
  showPermissionModal.value = false
  currentRole.value = null
  selectedPermissions.value = []
}

function selectAllPermissions() {
  selectedPermissions.value = allPermissions.value.map(p => p.permission_id)
}

function clearAllPermissions() {
  selectedPermissions.value = []
}

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

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}


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
  { id: 'spread_history', name: '点差历史图表', description: '历史数据展示', interval: 5000, enabled: true, default: 5000 },
  { id: 'asset_dashboard', name: '资产仪表盘', description: '资产数据刷新', interval: 10000, enabled: true, default: 10000 },
  { id: 'account_status', name: '账户状态面板', description: '账户信息更新', interval: 30000, enabled: true, default: 30000 }
])

// WebSocket连接状态 - 从market store获取实时状态
const wsConnected = computed(() => marketStore.connected)

onMounted(async () => {
  loadRoles()
  loadCertificates()
  loadAllPermissions()
  loadSecurityComponents()
  loadUsers()
  loadSystemLogs()
  // 确保WebSocket连接已建立（如果配置启用）
  if (refreshSettings.value.useWebSocket && !marketStore.connected) {
    marketStore.connect()
  }

  await loadSystemInfo()
  await loadDbStats()
  await loadVersionHistory()
  await loadAlertSounds()
  await loadRefreshSettings()
})


// 导航到管理页面









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
  showBackupActionModal.value = true
}

async function handleBackupSelect(type) {
  if (type === 'github') {
    if (!confirm('确定要备份数据库至 GitHub 吗？')) return
    try {
      const response = await api.post('/api/v1/system/github/push', { remark: '数据库备份' })
      alert(`备份至 GitHub 成功: ${response.data.branch}`)
    } catch (error) {
      console.error('Failed to backup to GitHub:', error)
      alert('备份失败: ' + (error.response?.data?.detail || error.message))
    }
  } else {
    if (!confirm('确定要备份数据库至服务器吗？')) return
    try {
      const response = await api.post('/api/v1/system/database/backup')
      alert(`备份至服务器成功: ${response.data.filename}`)
    } catch (error) {
      console.error('Failed to backup to server:', error)
      alert('备份失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

function restoreDatabase() {
  showRestoreActionModal.value = true
}

function handleRestoreSelect(type) {
  if (type === 'github') {
    // Show GitHub version history for restore
    showRestoreActionModal.value = false
    // Navigate to version management tab or show GitHub restore modal
    alert('请在下方"版本管理"区域选择要还原的 GitHub 版本')
  } else {
    // Show server backup list for restore
    showRestoreActionModal.value = false
    showBackupModal.value = true
  }
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

  console.log('playSound called with:', soundPath)

  // If this sound is already playing, stop it
  if (playingSound.value === soundPath && currentAudio.value) {
    currentAudio.value.pause()
    currentAudio.value.currentTime = 0
    currentAudio.value = null
    playingSound.value = null
    return
  }

  // Stop any currently playing sound
  if (currentAudio.value) {
    currentAudio.value.pause()
    currentAudio.value.currentTime = 0
  }

  // Construct full URL for uploaded sound files
  const soundUrl = soundPath.startsWith('/uploads/')
    ? `http://13.115.21.77:8001${soundPath}`
    : soundPath

  console.log('Constructed soundUrl:', soundUrl)

  // Create and play new audio
  const audio = new Audio(soundUrl)
  currentAudio.value = audio
  playingSound.value = soundPath

  // Clear state when audio ends
  audio.onended = () => {
    currentAudio.value = null
    playingSound.value = null
  }

  audio.play().catch(error => {
    console.error('Failed to play sound:', error)
    console.error('Sound path was:', soundPath)
    console.error('Sound URL was:', soundUrl)
    alert('播放失败: ' + error.message)
    currentAudio.value = null
    playingSound.value = null
  })
}

function getFileName(path) {
  if (!path) return ''
  return path.split('/').pop()
}

// Logging functions

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

/* System Logs Styles */
.log-detail-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.detail-row.full-width {
  flex-direction: column;
}

.detail-label {
  font-weight: 600;
  color: #666;
  min-width: 100px;
  flex-shrink: 0;
}

.detail-value {
  color: #333;
  word-break: break-word;
}

.detail-json {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
  width: 100%;
}

.log-level-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.log-level-info {
  background: #e3f2fd;
  color: #1976d2;
}

.log-level-warning {
  background: #fff3e0;
  color: #f57c00;
}

.log-level-error {
  background: #ffebee;
  color: #d32f2f;
}

.log-level-critical {
  background: #fce4ec;
  color: #c2185b;
}

.log-category-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.log-category-api {
  background: #e8f5e9;
  color: #388e3c;
}

.log-category-trade {
  background: #fff9c4;
  color: #f57f17;
}

.log-category-system {
  background: #e1f5fe;
  color: #0277bd;
}

.log-category-auth {
  background: #f3e5f5;
  color: #7b1fa2;
}

.logs-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  background: #f8f9fa;
  padding: 16px;
  border-radius: 8px;
  text-align: center;
}

.stat-card h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: #666;
}

.stat-card .stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #333;
}

</style>
