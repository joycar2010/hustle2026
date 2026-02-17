<template>
  <div class="min-h-screen bg-slate-900 text-slate-200">
    <!-- 顶部导航栏 -->
    <header class="bg-slate-800 border-b border-slate-700 py-3">
      <div class="container mx-auto px-4 flex justify-between items-center">
        <div class="flex items-center gap-6">
          <h1 class="text-xl font-bold text-white">Hustle XAU搬砖系统</h1>
          <div class="flex items-center gap-4">
            <div class="flex items-center gap-2">
              <span @click="showAccountsModal = true" class="text-sm text-slate-400 cursor-pointer hover:text-white transition-colors">账户管理</span>
              <span class="text-sm text-slate-400">|</span>
              <span @click="showStrategyModal = true" class="text-sm text-slate-400 cursor-pointer hover:text-white transition-colors">策略管理</span>
              <span class="text-sm text-slate-400">|</span>
              <span @click="showProfitModal = true" class="text-sm text-green-400 cursor-pointer hover:text-green-300 transition-colors">总盈利</span>
              <span @click="showProfitModal = true" class="text-sm text-red-400 cursor-pointer hover:text-red-300 transition-colors">{{ totalProfit || '-0.00' }}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <div class="flex items-center gap-2">
            <span class="text-sm text-green-400">做多Bybit</span>
            <span class="text-sm text-green-400">{{ spreadData.forward_spread || '0.00' }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-sm text-red-400">做多Binance</span>
            <span class="text-sm text-red-400">{{ spreadData.reverse_spread || '0.00' }}</span>
          </div>
          <div class="flex items-center gap-3">
            <button v-if="!isLoggedIn" @click="showLoginModal = true" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">登录</button>
            <button v-if="!isLoggedIn" @click="showRegisterModal = true" class="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 transition-colors">注册</button>
            <div v-else class="flex items-center gap-2">
              <span class="text-sm text-white">{{ userInfo.username || '用户' }}</span>
              <button @click="logout" class="px-3 py-1 bg-red-600 text-white text-sm rounded hover:bg-red-700 transition-colors">退出</button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- 未登录状态的模糊透明层 -->
    <div v-if="!isLoggedIn" class="fixed inset-0 bg-black bg-opacity-70 z-40 flex items-center justify-center">
      <div class="text-center">
        <h2 class="text-2xl font-bold text-white mb-4">请先登录</h2>
        <p class="text-slate-300 mb-6">登录后即可使用完整功能</p>
        <div class="flex gap-4 justify-center">
          <button @click="showLoginModal = true" class="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 transition-colors">登录</button>
          <button @click="showRegisterModal = true" class="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">注册</button>
        </div>
      </div>
    </div>

    <!-- 登录模态框 -->
    <div v-if="showLoginModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-96">
        <h3 class="text-lg font-medium text-white mb-4">用户登录</h3>
        <div class="space-y-4">
          <div>
            <label class="block text-xs text-slate-400 mb-1">用户名</label>
            <input type="text" v-model="loginForm.username" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="请输入用户名">
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">密码</label>
            <input type="password" v-model="loginForm.password" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="请输入密码">
          </div>
          <div v-if="loginError" class="text-sm text-red-400">{{ loginError }}</div>
          <div class="flex gap-2">
            <button @click="handleLogin" :disabled="isLoginLoading" class="flex-1 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 transition-colors" :class="{ 'opacity-50 cursor-not-allowed': isLoginLoading }">
              {{ isLoginLoading ? '登录中...' : '登录' }}
            </button>
            <button @click="showLoginModal = false" class="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 注册模态框 -->
    <div v-if="showRegisterModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-96">
        <h3 class="text-lg font-medium text-white mb-4">用户注册</h3>
        <div class="space-y-4">
          <div>
            <label class="block text-xs text-slate-400 mb-1">用户名</label>
            <input type="text" v-model="registerForm.username" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="请输入用户名">
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">邮箱</label>
            <input type="email" v-model="registerForm.email" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="请输入邮箱">
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">密码</label>
            <input type="password" v-model="registerForm.password" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="请输入密码">
          </div>
          <div v-if="registerError" class="text-sm text-red-400">{{ registerError }}</div>
          <div class="flex gap-2">
            <button @click="handleRegister" :disabled="isRegisterLoading" class="flex-1 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 transition-colors" :class="{ 'opacity-50 cursor-not-allowed': isRegisterLoading }">
              {{ isRegisterLoading ? '注册中...' : '注册' }}
            </button>
            <button @click="showRegisterModal = false" class="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 账户管理模态框 -->
    <div v-if="showAccountsModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-96">
        <h3 class="text-lg font-medium text-white mb-4">账户管理</h3>
        <div class="space-y-4">
          <div v-for="account in accountsList" :key="account.id" class="p-3 rounded border border-slate-700">
            <div class="text-sm font-medium text-white mb-2">{{ account.name }}</div>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span class="text-slate-400">平台:</span>
                <span class="text-white">{{ account.platform }}</span>
              </div>
              <div>
                <span class="text-slate-400">状态:</span>
                <span :class="account.status === 'active' ? 'text-green-400' : 'text-red-400'">{{ account.status === 'active' ? '已激活' : '未激活' }}</span>
              </div>
              <div>
                <span class="text-slate-400">总资产:</span>
                <span class="text-white">{{ account.total_asset || '0.00' }}</span>
              </div>
              <div>
                <span class="text-slate-400">可用资产:</span>
                <span class="text-white">{{ account.available_asset || '0.00' }}</span>
              </div>
            </div>
            <div class="mt-2 flex gap-2">
              <button @click="editAccount(account.id)" class="px-2 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors">编辑</button>
              <button @click="toggleAccountStatus(account.id)" class="px-2 py-1 bg-yellow-600 text-white text-xs rounded hover:bg-yellow-700 transition-colors">
                {{ account.status === 'active' ? '禁用' : '启用' }}
              </button>
              <button @click="confirmDeleteAccount(account.id)" :disabled="account.status === 'active' || account.is_default" :class="['px-2 py-1 text-white text-xs rounded transition-colors', (account.status === 'active' || account.is_default) ? 'bg-slate-600 opacity-50 cursor-not-allowed' : 'bg-red-600 hover:bg-red-700']">
                删除
              </button>
            </div>
          </div>
          <button @click="addNewAccount" class="w-full py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 transition-colors">添加账户</button>
          <div class="flex gap-2 mt-4">
            <button @click="showAccountsModal = false" class="flex-1 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 策略管理模态框 -->
    <div v-if="showStrategyModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-96">
        <h3 class="text-lg font-medium text-white mb-4">策略管理</h3>
        <div class="space-y-4">
          <div class="p-3 rounded border border-slate-700">
            <div class="flex justify-between items-center mb-2">
              <div class="text-sm font-medium text-white">正向套利</div>
              <div class="flex items-center">
                <span :class="forwardConfig.isOpenEnabled ? 'text-green-400' : 'text-red-400'">
                  {{ forwardConfig.isOpenEnabled ? '启用' : '禁用' }}
                </span>
              </div>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span class="text-slate-400">目标点差:</span>
                <span class="text-white">{{ forwardConfig.threshold }}</span>
              </div>
              <div>
                <span class="text-slate-400">下单数量:</span>
                <span class="text-white">{{ forwardConfig.qtyLimit }}</span>
              </div>
            </div>
            <button @click="toggleForwardStrategy" class="mt-2 w-full py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors">
              {{ forwardConfig.isOpenEnabled ? '禁用策略' : '启用策略' }}
            </button>
          </div>
          <div class="p-3 rounded border border-slate-700">
            <div class="flex justify-between items-center mb-2">
              <div class="text-sm font-medium text-white">反向套利</div>
              <div class="flex items-center">
                <span :class="reverseConfig.isOpenEnabled ? 'text-green-400' : 'text-red-400'">
                  {{ reverseConfig.isOpenEnabled ? '启用' : '禁用' }}
                </span>
              </div>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span class="text-slate-400">目标点差:</span>
                <span class="text-white">{{ reverseConfig.threshold }}</span>
              </div>
              <div>
                <span class="text-slate-400">下单数量:</span>
                <span class="text-white">{{ reverseConfig.qtyLimit }}</span>
              </div>
            </div>
            <button @click="toggleReverseStrategy" class="mt-2 w-full py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors">
              {{ reverseConfig.isOpenEnabled ? '禁用策略' : '启用策略' }}
            </button>
          </div>
          <div class="flex gap-2">
            <button @click="showStrategyModal = false" class="flex-1 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 总盈利模态框 -->
    <div v-if="showProfitModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-96">
        <h3 class="text-lg font-medium text-white mb-4">盈利详情</h3>
        <div class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">今日盈利</div>
              <div class="text-lg font-bold text-green-400">{{ profitDetails.today || '0.00' }}</div>
            </div>
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">本周盈利</div>
              <div class="text-lg font-bold text-green-400">{{ profitDetails.week || '0.00' }}</div>
            </div>
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">本月盈利</div>
              <div class="text-lg font-bold text-green-400">{{ profitDetails.month || '0.00' }}</div>
            </div>
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">总盈利</div>
              <div class="text-lg font-bold text-green-400">{{ profitDetails.total || '0.00' }}</div>
            </div>
          </div>
          <div class="mt-4">
            <h4 class="text-sm font-medium text-white mb-2">最近交易记录</h4>
            <div class="space-y-2 max-h-40 overflow-y-auto">
              <div v-for="(trade, index) in recentTrades" :key="index" class="p-2 rounded border border-slate-700">
                <div class="flex justify-between items-center">
                  <div class="text-xs text-slate-400">{{ trade.time }}</div>
                  <div :class="trade.profit > 0 ? 'text-green-400' : 'text-red-400'">
                    {{ trade.profit > 0 ? '+' : '' }}{{ trade.profit }}
                  </div>
                </div>
                <div class="text-xs text-white mt-1">{{ trade.strategy_type }} - {{ trade.symbol }}</div>
              </div>
            </div>
          </div>
          <div class="flex gap-2 mt-4">
            <button @click="showProfitModal = false" class="flex-1 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据库管理模态框 -->
    <div v-if="showDatabaseModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-3/4 max-w-5xl max-h-[80vh] overflow-y-auto">
        <div class="flex justify-between items-center mb-6">
          <h3 class="text-lg font-medium text-white">数据库管理</h3>
          <button @click="showDatabaseModal = false" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
        </div>
        
        <!-- 标签页导航 -->
        <div class="flex border-b border-slate-700 mb-4">
          <button @click="activeDatabaseTab = 'connection'" :class="['px-4 py-2 text-sm', activeDatabaseTab === 'connection' ? 'text-white border-b-2 border-green-500' : 'text-slate-400 hover:text-white']">连接配置</button>
          <button @click="activeDatabaseTab = 'tables'" :class="['px-4 py-2 text-sm', activeDatabaseTab === 'tables' ? 'text-white border-b-2 border-green-500' : 'text-slate-400 hover:text-white']">数据表</button>
          <button @click="activeDatabaseTab = 'query'" :class="['px-4 py-2 text-sm', activeDatabaseTab === 'query' ? 'text-white border-b-2 border-green-500' : 'text-slate-400 hover:text-white']">数据查询</button>
          <button @click="activeDatabaseTab = 'import'" :class="['px-4 py-2 text-sm', activeDatabaseTab === 'import' ? 'text-white border-b-2 border-green-500' : 'text-slate-400 hover:text-white']">导入导出</button>
          <button @click="activeDatabaseTab = 'monitoring'" :class="['px-4 py-2 text-sm', activeDatabaseTab === 'monitoring' ? 'text-white border-b-2 border-green-500' : 'text-slate-400 hover:text-white']">性能监控</button>
        </div>
        
        <!-- 连接配置标签页 -->
        <div v-if="activeDatabaseTab === 'connection'" class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-slate-400 mb-1">数据库类型</label>
              <select v-model="databaseConfig.type" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white">
                <option value="postgresql">PostgreSQL</option>
                <option value="mysql">MySQL</option>
                <option value="sqlite">SQLite</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">主机地址</label>
              <input type="text" v-model="databaseConfig.host" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="localhost">
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">端口</label>
              <input type="number" v-model="databaseConfig.port" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="5432">
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">数据库名</label>
              <input type="text" v-model="databaseConfig.database" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="example_db">
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">用户名</label>
              <input type="text" v-model="databaseConfig.username" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="admin">
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">密码</label>
              <input type="password" v-model="databaseConfig.password" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="password">
            </div>
          </div>
          <div class="flex gap-2">
            <button @click="testDatabaseConnection" :disabled="isTestingConnection" :class="['px-4 py-2 text-white text-sm rounded transition-colors', isTestingConnection ? 'bg-blue-600 opacity-50 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700']">
              {{ isTestingConnection ? '测试中...' : '测试连接' }}
            </button>
            <button @click="saveDatabaseConfig" :disabled="isSavingConfig" :class="['px-4 py-2 text-white text-sm rounded transition-colors', isSavingConfig ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
              {{ isSavingConfig ? '保存中...' : '保存配置' }}
            </button>
          </div>
          <div v-if="connectionMessage" :class="['mt-2 px-3 py-2 rounded text-sm', connectionMessageType === 'success' ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400']">
            {{ connectionMessage }}
          </div>
        </div>
        
        <!-- 数据表标签页 -->
        <div v-if="activeDatabaseTab === 'tables'" class="space-y-4">
          <div class="flex justify-between items-center">
            <h4 class="text-sm font-medium text-white">数据表列表</h4>
            <div class="flex gap-2">
              <input type="text" v-model="tableSearch" class="px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" placeholder="搜索表名">
              <button @click="refreshTables" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">刷新</button>
            </div>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div v-for="table in filteredTables" :key="table.name" class="p-3 rounded border border-slate-700">
              <div class="text-sm font-medium text-white mb-2">{{ table.name }}</div>
              <div class="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span class="text-slate-400">行数:</span>
                  <span class="text-white">{{ table.rows || '0' }}</span>
                </div>
                <div>
                  <span class="text-slate-400">列数:</span>
                  <span class="text-white">{{ table.columns || '0' }}</span>
                </div>
              </div>
              <div class="mt-2 flex gap-2">
                <button @click="viewTableData(table.name)" class="px-2 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors">查看数据</button>
                <button @click="viewTableStructure(table.name)" class="px-2 py-1 bg-yellow-600 text-white text-xs rounded hover:bg-yellow-700 transition-colors">结构</button>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 数据查询标签页 -->
        <div v-if="activeDatabaseTab === 'query'" class="space-y-4">
          <div>
            <label class="block text-xs text-slate-400 mb-1">SQL查询</label>
            <textarea v-model="sqlQuery" class="w-full h-48 px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white font-mono" placeholder="输入SQL查询语句..."></textarea>
          </div>
          <div class="flex gap-2">
            <button @click="executeQuery" :disabled="isExecutingQuery" :class="['px-4 py-2 text-white text-sm rounded transition-colors', isExecutingQuery ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
              {{ isExecutingQuery ? '执行中...' : '执行查询' }}
            </button>
            <button @click="clearQuery" class="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">清除</button>
          </div>
          <div v-if="queryResult.length > 0" class="mt-4">
            <h4 class="text-sm font-medium text-white mb-2">查询结果</h4>
            <div class="overflow-x-auto">
              <table class="w-full border-collapse">
                <thead>
                  <tr class="bg-slate-700">
                    <th v-for="(column, index) in Object.keys(queryResult[0])" :key="index" class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">
                      {{ column }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in queryResult" :key="rowIndex" class="hover:bg-slate-700">
                    <td v-for="(value, colIndex) in Object.values(row)" :key="colIndex" class="px-3 py-2 text-sm text-white border border-slate-600">
                      {{ value }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-if="queryMessage" :class="['mt-2 px-3 py-2 rounded text-sm', queryMessageType === 'success' ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400']">
            {{ queryMessage }}
          </div>
        </div>
        
        <!-- 导入导出标签页 -->
        <div v-if="activeDatabaseTab === 'import'" class="space-y-4">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h4 class="text-sm font-medium text-white mb-3">数据导入</h4>
              <div class="space-y-3">
                <div>
                  <label class="block text-xs text-slate-400 mb-1">选择表</label>
                  <select v-model="importTable" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white">
                    <option value="">请选择表</option>
                    <option v-for="table in tablesList" :key="table.name" :value="table.name">{{ table.name }}</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs text-slate-400 mb-1">导入文件</label>
                  <input type="file" @change="handleFileUpload" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white">
                </div>
                <button @click="importData" :disabled="isImporting" :class="['w-full py-2 text-white text-sm rounded transition-colors', isImporting ? 'bg-blue-600 opacity-50 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700']">
                  {{ isImporting ? '导入中...' : '导入数据' }}
                </button>
              </div>
            </div>
            <div>
              <h4 class="text-sm font-medium text-white mb-3">数据导出</h4>
              <div class="space-y-3">
                <div>
                  <label class="block text-xs text-slate-400 mb-1">选择表</label>
                  <select v-model="exportTable" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white">
                    <option value="">请选择表</option>
                    <option v-for="table in tablesList" :key="table.name" :value="table.name">{{ table.name }}</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs text-slate-400 mb-1">导出格式</label>
                  <select v-model="exportFormat" class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white">
                    <option value="csv">CSV</option>
                    <option value="json">JSON</option>
                    <option value="sql">SQL</option>
                  </select>
                </div>
                <button @click="exportData" :disabled="isExporting" :class="['w-full py-2 text-white text-sm rounded transition-colors', isExporting ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
                  {{ isExporting ? '导出中...' : '导出数据' }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="importExportMessage" :class="['mt-4 px-3 py-2 rounded text-sm', importExportMessageType === 'success' ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400']">
            {{ importExportMessage }}
          </div>
        </div>
        
        <!-- 性能监控标签页 -->
        <div v-if="activeDatabaseTab === 'monitoring'" class="space-y-4">
          <h4 class="text-sm font-medium text-white mb-3">数据库性能指标</h4>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">连接数</div>
              <div class="text-lg font-bold text-white">{{ performanceMetrics.connections || '0' }}</div>
              <div class="text-xs text-slate-400 mt-1">最大: {{ performanceMetrics.max_connections || '0' }}</div>
            </div>
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">查询执行时间</div>
              <div class="text-lg font-bold text-white">{{ performanceMetrics.query_time || '0' }} ms</div>
              <div class="text-xs text-slate-400 mt-1">平均: {{ performanceMetrics.avg_query_time || '0' }} ms</div>
            </div>
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">缓存命中率</div>
              <div class="text-lg font-bold text-white">{{ performanceMetrics.cache_hit_rate || '0' }}%</div>
              <div class="text-xs text-slate-400 mt-1">缓存大小: {{ performanceMetrics.cache_size || '0' }} MB</div>
            </div>
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">磁盘使用</div>
              <div class="text-lg font-bold text-white">{{ performanceMetrics.disk_usage || '0' }} MB</div>
              <div class="text-xs text-slate-400 mt-1">总空间: {{ performanceMetrics.total_disk || '0' }} MB</div>
            </div>
            <div class="p-3 rounded border border-slate-700">
              <div class="text-xs text-slate-400 mb-1">数据库版本</div>
              <div class="text-lg font-bold text-white">{{ performanceMetrics.version || '未知' }}</div>
              <div class="text-xs text-slate-400 mt-1">类型: {{ databaseConfig.type }}</div>
            </div>
          </div>
          <div class="mt-4">
            <h4 class="text-sm font-medium text-white mb-2">最近查询</h4>
            <div class="space-y-2 max-h-40 overflow-y-auto">
              <div v-for="(query, index) in recentQueries" :key="index" class="p-2 rounded border border-slate-700">
                <div class="text-xs text-slate-400 mb-1">{{ query.time }}</div>
                <div class="text-sm text-white truncate">{{ query.sql }}</div>
                <div class="flex justify-between items-center mt-1">
                  <div class="text-xs text-slate-400">执行时间: {{ query.execution_time }} ms</div>
                  <div :class="query.success ? 'text-green-400' : 'text-red-400'">
                    {{ query.success ? '成功' : '失败' }}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="flex justify-end mt-4">
            <button @click="refreshMetrics" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">刷新指标</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 表数据模态框 -->
    <div v-if="showTableDataModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-3/4 max-w-5xl max-h-[80vh] overflow-y-auto">
        <div class="flex justify-between items-center mb-6">
          <h3 class="text-lg font-medium text-white">{{ currentTable }} 表数据</h3>
          <button @click="showTableDataModal = false" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
        </div>
        
        <div class="space-y-4">
          <!-- 功能描述 -->
          <div class="p-4 bg-slate-700 rounded-lg">
            <h4 class="text-sm font-medium text-white mb-2">功能描述</h4>
            <p class="text-xs text-slate-300">
              本功能允许您查看指定数据表的详细数据，支持表格形式展示所有记录。您可以通过此界面快速了解表中的数据内容，
              验证数据完整性和正确性。系统会根据表类型自动适配显示不同的字段和数据格式。
            </p>
          </div>
          
          <!-- 操作指南 -->
          <div class="p-4 bg-slate-700 rounded-lg">
            <h4 class="text-sm font-medium text-white mb-2">操作指南</h4>
            <ul class="text-xs text-slate-300 space-y-1">
              <li>1. 在数据表列表中点击"查看数据"按钮</li>
              <li>2. 系统会加载并显示该表的所有记录</li>
              <li>3. 您可以通过滚动查看所有数据</li>
              <li>4. 点击"关闭"按钮返回数据表列表</li>
            </ul>
          </div>
          
          <!-- 数据操作按钮 -->
          <div class="flex justify-between items-center mb-3">
            <h4 class="text-sm font-medium text-white">数据记录</h4>
            <div class="flex gap-2">
              <button @click="addTableRow" class="px-3 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700 transition-colors">添加数据</button>
              <button @click="refreshTableData" class="px-3 py-1 bg-slate-700 text-white text-xs rounded hover:bg-slate-600 transition-colors">刷新数据</button>
            </div>
          </div>
          <!-- 数据展示 -->
          <div class="mt-2">
            <div class="overflow-x-auto">
              <table class="w-full border-collapse">
                <thead>
                  <tr class="bg-slate-700">
                    <th class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">操作</th>
                    <th v-for="(column, index) in tableColumns" :key="index" class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">
                      {{ column }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in tableData" :key="rowIndex" class="hover:bg-slate-700">
                    <td class="px-3 py-2 text-sm border border-slate-600">
                      <div class="flex gap-1">
                        <button @click="editTableRow(rowIndex)" class="px-2 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors">编辑</button>
                        <button @click="deleteTableRow(rowIndex)" class="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700 transition-colors">删除</button>
                      </div>
                    </td>
                    <td v-for="(value, colIndex) in row" :key="colIndex" class="px-3 py-2 text-sm text-white border border-slate-600">
                      {{ value }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="tableData.length === 0" class="text-center py-4 text-slate-400 text-sm">
              该表暂无数据
            </div>
          </div>
          
          <!-- 相关示例 -->
          <div class="p-4 bg-slate-700 rounded-lg mt-4">
            <h4 class="text-sm font-medium text-white mb-2">相关示例</h4>
            <div class="text-xs text-slate-300">
              <p class="mb-2">**查看用户表数据示例:**</p>
              <div class="bg-slate-800 p-2 rounded font-mono text-xs">
                SELECT * FROM users;
              </div>
              <p class="mt-2 mb-2">**查看账户表数据示例:**</p>
              <div class="bg-slate-800 p-2 rounded font-mono text-xs">
                SELECT id, name, platform, is_active FROM accounts;
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 账户管理模态框 -->
    <div v-if="showAccountModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-3/4 max-w-3xl max-h-[80vh] overflow-y-auto">
        <div class="flex justify-between items-center mb-6">
          <h3 class="text-lg font-medium text-white">{{ isEditingAccount ? '编辑账户' : '添加新账户' }}</h3>
          <button @click="showAccountModal = false" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
        </div>
        
        <div v-if="accountFormMessage" :class="['mb-4 px-4 py-3 rounded text-sm flex items-start justify-between', accountFormMessageType === 'success' ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400']">
          <div class="flex items-center">
            <svg v-if="accountFormMessageType === 'success'" class="w-5 h-5 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
            </svg>
            <svg v-else class="w-5 h-5 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-.633-1.964-.633-2.732 0L3.34 16c-.77.633.192 3 1.732 3z"></path>
            </svg>
            <span>{{ accountFormMessage }}</span>
          </div>
          <button v-if="accountFormMessageType === 'error'" @click="saveAccount" class="ml-4 px-3 py-1 bg-red-800 hover:bg-red-700 rounded text-xs font-medium transition-colors">
            重试
          </button>
        </div>
        
        <div class="space-y-4">
          <!-- 基本信息 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-slate-400 mb-1">账户名称 <span class="text-red-400">*</span></label>
              <input 
                type="text" 
                v-model="editingAccount.account_name" 
                class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
                placeholder="请输入账户名称"
              >
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">所属平台 <span class="text-red-400">*</span></label>
              <select 
                v-model="editingAccount.platform_id" 
                class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
              >
                <option v-for="platform in platformsList" :key="platform.platform_id" :value="platform.platform_id">
                  {{ platform.platform_name }}
                </option>
              </select>
            </div>
          </div>
          
          <!-- API信息 -->
          <div class="space-y-4">
            <h4 class="text-sm font-medium text-white">API信息</h4>
            <div>
              <label class="block text-xs text-slate-400 mb-1">API密钥 <span class="text-red-400">*</span></label>
              <input 
                type="text" 
                v-model="editingAccount.api_key" 
                class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
                placeholder="请输入API密钥"
              >
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">API秘钥 <span class="text-red-400">*</span></label>
              <input 
                type="text" 
                v-model="editingAccount.api_secret" 
                class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
                placeholder="请输入API秘钥"
              >
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">密码短语（可选）</label>
              <input 
                type="text" 
                v-model="editingAccount.passphrase" 
                class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
                placeholder="请输入密码短语（Bybit V5专属）"
              >
            </div>
          </div>
          
          <!-- MT5相关信息 -->
          <div class="space-y-4">
            <div class="flex items-center">
              <input 
                type="checkbox" 
                v-model="editingAccount.is_mt5_account" 
                class="mr-2"
              >
              <label class="text-sm text-white">是否为MT5关联账户</label>
            </div>
            
            <div v-if="editingAccount.is_mt5_account" class="space-y-4 pl-6 border-l border-slate-700">
              <h4 class="text-sm font-medium text-white">MT5信息</h4>
              <div>
                <label class="block text-xs text-slate-400 mb-1">MT5账号ID <span class="text-red-400">*</span></label>
                <input 
                  type="text" 
                  v-model="editingAccount.mt5_id" 
                  class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
                  placeholder="请输入MT5账号ID"
                >
              </div>
              <div>
                <label class="block text-xs text-slate-400 mb-1">MT5服务器地址 <span class="text-red-400">*</span></label>
                <input 
                  type="text" 
                  v-model="editingAccount.mt5_server" 
                  class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
                  placeholder="请输入MT5服务器地址"
                >
              </div>
              <div>
                <label class="block text-xs text-slate-400 mb-1">MT5主密码 <span class="text-red-400">*</span></label>
                <input 
                  type="text" 
                  v-model="editingAccount.mt5_primary_pwd" 
                  class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white"
                  placeholder="请输入MT5主密码"
                >
              </div>
            </div>
          </div>
          
          <!-- 其他设置 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="flex items-center">
              <input 
                type="checkbox" 
                v-model="editingAccount.is_default" 
                class="mr-2"
              >
              <label class="text-sm text-white">设为默认账户</label>
            </div>
            <div class="flex items-center">
              <input 
                type="checkbox" 
                v-model="editingAccount.is_active" 
                class="mr-2"
              >
              <label class="text-sm text-white">启用账户</label>
            </div>
          </div>
          
          <!-- 操作按钮 -->
          <div class="flex gap-2 mt-6">
            <button @click="saveAccount" :disabled="isSavingAccount" :class="['flex-1 py-2 text-white text-sm rounded transition-colors', isSavingAccount ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
              {{ isSavingAccount ? '保存中...' : (isEditingAccount ? '更新账户' : '添加账户') }}
            </button>
            <button @click="showAccountModal = false" class="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑数据模态框 -->
    <div v-if="showEditModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-3/4 max-w-3xl max-h-[80vh] overflow-y-auto">
        <div class="flex justify-between items-center mb-6">
          <h3 class="text-lg font-medium text-white">编辑 {{ currentTable }} 数据</h3>
          <button @click="showEditModal = false" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
        </div>
        <div class="space-y-4">
          <div v-for="(column, index) in tableColumns" :key="index" class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <label class="block text-xs text-slate-400 mb-1 md:col-span-1">{{ column }}</label>
            <input 
              type="text" 
              v-model="editingRow[column]" 
              class="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-white md:col-span-2"
              :placeholder="column"
            >
          </div>
          <div class="flex gap-2 mt-6">
            <button @click="saveEdit" :disabled="isSavingEdit" :class="['flex-1 py-2 text-white text-sm rounded transition-colors', isSavingEdit ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
              {{ isSavingEdit ? '保存中...' : '保存' }}
            </button>
            <button @click="showEditModal = false" class="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 表结构模态框 -->
    <div v-if="showTableStructureModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-slate-800 rounded-lg border border-slate-700 p-6 w-3/4 max-w-5xl max-h-[80vh] overflow-y-auto">
        <div class="flex justify-between items-center mb-6">
          <h3 class="text-lg font-medium text-white">{{ currentTable }} 表结构</h3>
          <button @click="showTableStructureModal = false" class="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">关闭</button>
        </div>
        
        <div class="space-y-4">
          <!-- 功能描述 -->
          <div class="p-4 bg-slate-700 rounded-lg">
            <h4 class="text-sm font-medium text-white mb-2">功能描述</h4>
            <p class="text-xs text-slate-300">
              本功能允许您查看指定数据表的详细结构信息，包括字段名称、数据类型、约束条件、默认值和字段描述。
              通过此界面，您可以全面了解表的设计结构，验证字段定义是否符合业务需求，以及查看各字段的具体含义。
            </p>
          </div>
          
          <!-- 操作指南 -->
          <div class="p-4 bg-slate-700 rounded-lg">
            <h4 class="text-sm font-medium text-white mb-2">操作指南</h4>
            <ul class="text-xs text-slate-300 space-y-1">
              <li>1. 在数据表列表中点击"结构"按钮</li>
              <li>2. 系统会加载并显示该表的详细结构</li>
              <li>3. 您可以查看每个字段的完整信息</li>
              <li>4. 点击"关闭"按钮返回数据表列表</li>
            </ul>
          </div>
          
          <!-- 结构展示 -->
          <div class="mt-4">
            <h4 class="text-sm font-medium text-white mb-2">字段结构</h4>
            <div class="overflow-x-auto">
              <table class="w-full border-collapse">
                <thead>
                  <tr class="bg-slate-700">
                    <th class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">字段名</th>
                    <th class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">数据类型</th>
                    <th class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">可空</th>
                    <th class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">默认值</th>
                    <th class="px-3 py-2 text-left text-xs text-slate-300 border border-slate-600">描述</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(field, index) in tableStructure" :key="index" class="hover:bg-slate-700">
                    <td class="px-3 py-2 text-sm text-white border border-slate-600">{{ field.column }}</td>
                    <td class="px-3 py-2 text-sm text-white border border-slate-600">{{ field.type }}</td>
                    <td class="px-3 py-2 text-sm text-white border border-slate-600">{{ field.nullable }}</td>
                    <td class="px-3 py-2 text-sm text-white border border-slate-600">{{ field.default }}</td>
                    <td class="px-3 py-2 text-sm text-white border border-slate-600">{{ field.description }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          
          <!-- 参数说明 -->
          <div class="p-4 bg-slate-700 rounded-lg mt-4">
            <h4 class="text-sm font-medium text-white mb-2">参数说明</h4>
            <div class="text-xs text-slate-300 space-y-2">
              <div>
                <strong>字段名:</strong> 表中的列名称，用于标识数据字段
              </div>
              <div>
                <strong>数据类型:</strong> 字段的数据类型，如VARCHAR、INTEGER、TIMESTAMP等
              </div>
              <div>
                <strong>可空:</strong> 表示该字段是否允许为空值
              </div>
              <div>
                <strong>默认值:</strong> 当插入数据时未指定该字段值时的默认值
              </div>
              <div>
                <strong>描述:</strong> 字段的业务含义和用途说明
              </div>
            </div>
          </div>
          
          <!-- 相关示例 -->
          <div class="p-4 bg-slate-700 rounded-lg mt-4">
            <h4 class="text-sm font-medium text-white mb-2">相关示例</h4>
            <div class="text-xs text-slate-300">
              <p class="mb-2">**查看表结构SQL示例:**</p>
              <div class="bg-slate-800 p-2 rounded font-mono text-xs">
                -- PostgreSQL
                \d {{ currentTable }};
                
                -- MySQL
                DESCRIBE {{ currentTable }};
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="container mx-auto px-4 py-6">
      <div class="grid grid-cols-12 gap-4">
        <!-- 左侧边栏 -->
        <aside class="col-span-3 bg-slate-800 rounded-lg border border-slate-700 p-4">
          <div class="space-y-6">
            <!-- 账户列表 -->
            <div>
              <h3 class="text-sm font-medium text-slate-300 mb-3">账户管理</h3>
              <div class="space-y-4">
                <div v-for="account in accountsList" :key="account.id" class="p-3 rounded border border-slate-700 mb-3">
                  <div class="text-sm font-medium text-white mb-2">{{ account.name }}</div>
                  <div class="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span class="text-slate-400">平台:</span>
                      <span class="text-white">{{ account.platform || '未知' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">状态:</span>
                      <span :class="account.status === 'active' ? 'text-green-400' : 'text-red-400'">{{ account.status === 'active' ? '已激活' : '未激活' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">账户总资产:</span>
                      <span class="text-white">{{ account.total_asset || '0.00' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">可用总资产:</span>
                      <span class="text-white">{{ account.available_asset || '0.00' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">净资产:</span>
                      <span class="text-white">{{ account.net_asset || '0.00' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">总持仓:</span>
                      <span class="text-white">{{ account.total_position || '0' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">冻结资产:</span>
                      <span class="text-white">{{ account.frozen_asset || '0.00' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">当日盈亏:</span>
                      <span :class="parseFloat(account.daily_profit || 0) >= 0 ? 'text-green-400' : 'text-red-400'">{{ account.daily_profit || '0.00' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">保证金余额:</span>
                      <span class="text-white">{{ account.margin_balance || '0.00' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">风险率:</span>
                      <span class="text-white">{{ account.risk_ratio || '0.00' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">{{ account.platform === 'Binance' ? '掉期费:' : '资金费:' }}</span>
                      <span :class="parseFloat(account.funding_fee || 0) >= 0 ? 'text-green-400' : 'text-red-400'">{{ account.funding_fee || '0.00' }}</span>
                    </div>
                  </div>
                  <div class="mt-3 flex gap-2">
                    <button @click="connectAccount(account.name)" :disabled="isBindingAccount" :class="['px-2 py-1 text-white text-xs rounded transition-colors', isBindingAccount ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
                      {{ isBindingAccount ? '连接中...' : '连接' }}
                    </button>
                    <button @click="disconnectAccount(account.name)" :disabled="isUnbindingAccount" :class="['px-2 py-1 text-white text-xs rounded transition-colors', isUnbindingAccount ? 'bg-red-600 opacity-50 cursor-not-allowed' : 'bg-red-600 hover:bg-red-700']">
                      {{ isUnbindingAccount ? '断开中...' : '断开' }}
                    </button>
                    <button @click="toggleAccountStatus(account.id)" :disabled="isTogglingStatus" :class="['px-2 py-1 text-white text-xs rounded transition-colors', isTogglingStatus ? 'opacity-50 cursor-not-allowed' : (account.status === 'active' ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700')]">
                      {{ isTogglingStatus ? '处理中...' : (account.status === 'active' ? '禁用' : '激活') }}
                    </button>
                    <button @click="confirmDeleteAccount(account.id)" :disabled="account.status === 'active' || account.is_default" :class="['px-2 py-1 text-white text-xs rounded transition-colors', (account.status === 'active' || account.is_default) ? 'bg-slate-600 opacity-50 cursor-not-allowed' : 'bg-red-600 hover:bg-red-700']">
                      删除
                    </button>
                  </div>
                </div>
                <div v-if="accountsList.length === 0" class="p-6 text-center text-slate-400">
                  暂无账户数据，请先添加账户
                </div>
              </div>
            </div>

            <!-- 风控状态 -->
            <div>
              <h3 class="text-sm font-medium text-slate-300 mb-3">风控状态</h3>
              <div class="space-y-2 text-xs">
                <div class="flex justify-between">
                  <span class="text-slate-400">总风险状态</span>
                  <span class="text-green-400">0</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-slate-400">总发现次数</span>
                  <span class="text-green-400">0</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-slate-400">反向套利</span>
                  <span class="text-green-400">启用</span>
                </div>
                <button @click="resetRiskCounter" :disabled="isResettingCounter" :class="['w-full mt-2 py-1 text-white text-xs rounded transition-colors', isResettingCounter ? 'bg-yellow-600 opacity-50 cursor-not-allowed' : 'bg-yellow-600 hover:bg-yellow-500']">
              {{ isResettingCounter ? '重置中...' : '重置计数' }}
            </button>
              </div>
            </div>

            <!-- 功能菜单 -->
            <div>
              <h3 class="text-sm font-medium text-slate-300 mb-3">功能菜单</h3>
              <div class="space-y-2">
                <button @click="navigateTo('strategy')" class="w-full py-2 text-left text-sm text-white bg-slate-700 rounded hover:bg-slate-600 transition-colors">策略控制</button>
                <button @click="navigateTo('settings')" class="w-full py-2 text-left text-sm text-slate-400 hover:bg-slate-700 rounded transition-colors">参数设置</button>
                <button @click="navigateTo('history')" class="w-full py-2 text-left text-sm text-slate-400 hover:bg-slate-700 rounded transition-colors">历史数据</button>
                <button @click="navigateTo('version')" class="w-full py-2 text-left text-sm text-slate-400 hover:bg-slate-700 rounded transition-colors">版本管理</button>
                <button @click="navigateTo('scripts')" class="w-full py-2 text-left text-sm text-slate-400 hover:bg-slate-700 rounded transition-colors">脚本管理</button>
                <button @click="showDatabaseModal = true" class="w-full py-2 text-left text-sm text-slate-400 hover:bg-slate-700 rounded transition-colors">数据库管理</button>
              </div>
            </div>
          </div>
        </aside>

        <!-- 主内容 -->
        <main class="col-span-9 space-y-4">
          <!-- 价格监控区 -->
          <section class="bg-slate-800 rounded-lg border border-slate-700 p-4">
            <h2 class="text-lg font-medium text-white mb-4">价格监控</h2>
            <div class="grid grid-cols-3 gap-4">
              <!-- Bybit MT5 行情 -->
              <div class="bg-slate-700 rounded-lg p-4">
                <h3 class="text-sm font-medium text-slate-300 mb-2">Bybit MT5 - XAUUSD.s</h3>
                <div class="text-2xl font-bold text-white mb-2">{{ bybitData.last_price || '0.00' }}</div>
                <div class="grid grid-cols-2 gap-2 mb-3">
                  <div>
                    <div class="text-xs text-slate-400">卖一</div>
                    <div class="text-sm text-white">{{ bybitData.ask || '0.00' }}</div>
                  </div>
                  <div>
                    <div class="text-xs text-slate-400">买一</div>
                    <div class="text-sm text-white">{{ bybitData.bid || '0.00' }}</div>
                  </div>
                </div>
                <div class="grid grid-cols-2 gap-2">
                  <div>
                    <div class="text-xs text-slate-400">连接状态</div>
                    <div class="text-xs text-green-400">已连接</div>
                  </div>
                  <div>
                    <div class="text-xs text-slate-400">最后更新</div>
                    <div class="text-xs text-slate-300">{{ bybitData.update_time || '--' }}</div>
                  </div>
                </div>
              </div>

              <!-- 点差数据 -->
              <div class="bg-slate-700 rounded-lg p-4">
                <h3 class="text-sm font-medium text-slate-300 mb-2">点差数据</h3>
                <div class="space-y-1 max-h-40 overflow-y-auto">
                  <div v-for="(item, index) in spreadHistory" :key="index" class="grid grid-cols-3 gap-2 text-xs">
                    <div class="text-slate-300">{{ item.time }}</div>
                    <div class="text-green-400">{{ item.forwardSpread }}</div>
                    <div class="text-red-400">{{ item.reverseSpread }}</div>
                  </div>
                </div>
              </div>

              <!-- Binance 行情 -->
              <div class="bg-slate-700 rounded-lg p-4">
                <h3 class="text-sm font-medium text-slate-300 mb-2">Binance - XAUUSDT</h3>
                <div class="text-2xl font-bold text-white mb-2">{{ binanceData.last_price || '0.00' }}</div>
                <div class="grid grid-cols-2 gap-2 mb-3">
                  <div>
                    <div class="text-xs text-slate-400">卖一</div>
                    <div class="text-sm text-white">{{ binanceData.ask || '0.00' }}</div>
                  </div>
                  <div>
                    <div class="text-xs text-slate-400">买一</div>
                    <div class="text-sm text-white">{{ binanceData.bid || '0.00' }}</div>
                  </div>
                </div>
                <div class="grid grid-cols-2 gap-2">
                  <div>
                    <div class="text-xs text-slate-400">连接状态</div>
                    <div class="text-xs text-green-400">已连接</div>
                  </div>
                  <div>
                    <div class="text-xs text-slate-400">最后更新</div>
                    <div class="text-xs text-slate-300">{{ binanceData.update_time || '--' }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 点差曲线 -->
            <div class="mt-4 h-64">
              <div ref="spreadChart" class="w-full h-full"></div>
            </div>
          </section>

          <!-- 策略控制区 -->
          <section class="bg-slate-800 rounded-lg border border-slate-700 p-4">
            <div class="grid grid-cols-2 gap-6">
              <!-- 反向套利 -->
              <div>
                <div class="flex justify-between items-center mb-4">
                  <h3 class="text-lg font-medium text-white">反向套利 (做多 Bybit)</h3>
                  <div class="flex items-center gap-2">
                    <button @click="toggleReverseOpen" :class="['px-3 py-1 text-white text-sm rounded transition-colors', reverseConfig.isOpenEnabled ? 'bg-green-600 hover:bg-green-700' : 'bg-slate-600 hover:bg-slate-500']">
                      {{ reverseConfig.isOpenEnabled ? '启用开仓' : '禁用开仓' }}
                    </button>
                    <button @click="toggleReverseClose" :class="['px-3 py-1 text-white text-sm rounded transition-colors', reverseConfig.isCloseEnabled ? 'bg-red-600 hover:bg-red-700' : 'bg-slate-600 hover:bg-slate-500']">
                      {{ reverseConfig.isCloseEnabled ? '启用平仓' : '禁用平仓' }}
                    </button>
                  </div>
                </div>
                <div class="space-y-4">
                  <div class="grid grid-cols-3 gap-4">
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">M币设置一次下单数量</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="reverseConfig.qtyLimit">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">开仓数据同步</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="reverseConfig.openSync">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">平仓数据同步</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="reverseConfig.closeSync">
                    </div>
                  </div>
                  <div class="grid grid-cols-3 gap-4">
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">开仓价</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="reverseConfig.openPrice">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">阈值</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="reverseConfig.threshold">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">下单数量限制</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="reverseConfig.qtyLimit">
                    </div>
                  </div>
                  <div class="mt-4">
                    <button @click="saveReverseConfig" :disabled="isSavingConfig" :class="['px-4 py-2 bg-yellow-600 text-white text-sm rounded transition-colors', isSavingConfig ? 'opacity-50 cursor-not-allowed' : 'hover:bg-yellow-500']">
                      {{ isSavingConfig ? '保存中...' : '保存' }}
                    </button>
                  </div>
                </div>

                <!-- 阶梯设置 -->
                <div class="mt-6">
                  <div v-for="(step, index) in reverseSteps" :key="index" class="mb-4">
                    <h4 class="text-sm font-medium text-slate-300 mb-3">阶梯 {{ index + 1 }}</h4>
                    <div class="grid grid-cols-3 gap-4 mb-3">
                      <div>
                        <label class="block text-xs text-slate-400 mb-1">开仓价</label>
                        <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="step.openPrice">
                      </div>
                      <div>
                        <label class="block text-xs text-slate-400 mb-1">阈值</label>
                        <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="step.threshold">
                      </div>
                      <div>
                        <label class="block text-xs text-slate-400 mb-1">下单数量限制</label>
                        <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="step.qtyLimit">
                      </div>
                    </div>
                    <button v-if="reverseSteps.length > 1" @click="removeReverseStep(index)" class="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700 transition-colors">
                      删除阶梯
                    </button>
                  </div>
                  <div class="flex gap-2">
                    <button @click="addReverseStep" :disabled="reverseSteps.length >= 5" :class="['px-3 py-1 text-white text-sm rounded transition-colors', reverseSteps.length >= 5 ? 'bg-slate-600 cursor-not-allowed opacity-50' : 'bg-blue-600 hover:bg-blue-700']">
                      添加阶梯
                    </button>
                    <button @click="saveReverseSteps" :disabled="isSavingSteps" :class="['px-3 py-1 text-white text-sm rounded transition-colors', isSavingSteps ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
                      {{ isSavingSteps ? '保存中...' : '保存阶梯' }}
                    </button>
                  </div>
                </div>
              </div>

              <!-- 正向套利 -->
              <div>
                <div class="flex justify-between items-center mb-4">
                  <h3 class="text-lg font-medium text-white">正向套利 (做多 Binance)</h3>
                  <div class="flex items-center gap-2">
                    <button @click="toggleForwardOpen" :class="['px-3 py-1 text-white text-sm rounded transition-colors', forwardConfig.isOpenEnabled ? 'bg-green-600 hover:bg-green-700' : 'bg-slate-600 hover:bg-slate-500']">
                      {{ forwardConfig.isOpenEnabled ? '启用开仓' : '禁用开仓' }}
                    </button>
                    <button @click="toggleForwardClose" :class="['px-3 py-1 text-white text-sm rounded transition-colors', forwardConfig.isCloseEnabled ? 'bg-red-600 hover:bg-red-700' : 'bg-slate-600 hover:bg-slate-500']">
                      {{ forwardConfig.isCloseEnabled ? '启用平仓' : '禁用平仓' }}
                    </button>
                  </div>
                </div>
                <div class="space-y-4">
                  <div class="grid grid-cols-3 gap-4">
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">M币设置一次下单数量</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="forwardConfig.qtyLimit">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">开仓数据同步</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="forwardConfig.openSync">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">平仓数据同步</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="forwardConfig.closeSync">
                    </div>
                  </div>
                  <div class="grid grid-cols-3 gap-4">
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">开仓价</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="forwardConfig.openPrice">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">阈值</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="forwardConfig.threshold">
                    </div>
                    <div>
                      <label class="block text-xs text-slate-400 mb-1">下单数量限制</label>
                      <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="forwardConfig.qtyLimit">
                    </div>
                  </div>
                  <div class="mt-4">
                    <button @click="stopForwardStrategy" :disabled="isStoppingStrategy" :class="['px-4 py-2 bg-yellow-600 text-white text-sm rounded transition-colors', isStoppingStrategy ? 'opacity-50 cursor-not-allowed' : 'hover:bg-yellow-500']">
                      {{ isStoppingStrategy ? '停止中...' : '停止' }}
                    </button>
                  </div>
                </div>

                <!-- 阶梯设置 -->
                <div class="mt-6">
                  <div v-for="(step, index) in forwardSteps" :key="index" class="mb-4">
                    <h4 class="text-sm font-medium text-slate-300 mb-3">阶梯 {{ index + 1 }}</h4>
                    <div class="grid grid-cols-3 gap-4 mb-3">
                      <div>
                        <label class="block text-xs text-slate-400 mb-1">开仓价</label>
                        <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="step.openPrice">
                      </div>
                      <div>
                        <label class="block text-xs text-slate-400 mb-1">阈值</label>
                        <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="step.threshold">
                      </div>
                      <div>
                        <label class="block text-xs text-slate-400 mb-1">下单数量限制</label>
                        <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" v-model="step.qtyLimit">
                      </div>
                    </div>
                    <button v-if="forwardSteps.length > 1" @click="removeForwardStep(index)" class="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700 transition-colors">
                      删除阶梯
                    </button>
                  </div>
                  <div class="flex gap-2">
                    <button @click="addForwardStep" :disabled="forwardSteps.length >= 5" :class="['px-3 py-1 text-white text-sm rounded transition-colors', forwardSteps.length >= 5 ? 'bg-slate-600 cursor-not-allowed opacity-50' : 'bg-blue-600 hover:bg-blue-700']">
                      添加阶梯
                    </button>
                    <button @click="saveForwardSteps" :disabled="isSavingSteps" :class="['px-3 py-1 text-white text-sm rounded transition-colors', isSavingSteps ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
                      {{ isSavingSteps ? '保存中...' : '保存阶梯' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 数据概览区 -->
          <section class="grid grid-cols-2 gap-4">
            <!-- 数据提醒 -->
            <div class="bg-slate-800 rounded-lg border border-slate-700 p-4">
              <h3 class="text-sm font-medium text-slate-300 mb-3">数据提醒</h3>
              <div class="grid grid-cols-2 gap-4">
                <!-- 正向套利挂单 -->
                <div>
                  <h4 class="text-sm font-medium text-white mb-2">正向套利</h4>
                  <div class="bg-slate-700 rounded-lg p-3">
                    <p class="text-sm text-slate-400">暂无挂单</p>
                  </div>
                </div>
                <!-- 反向套利挂单 -->
                <div>
                  <h4 class="text-sm font-medium text-white mb-2">反向套利</h4>
                  <div class="bg-slate-700 rounded-lg p-3">
                    <p class="text-sm text-slate-400">暂无挂单</p>
                  </div>
                </div>
              </div>
            </div>

            <!-- 保证金率监控 -->
            <div class="bg-slate-800 rounded-lg border border-slate-700 p-4">
              <h3 class="text-sm font-medium text-slate-300 mb-3">保证金率监控</h3>
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <h4 class="text-sm font-medium text-white mb-2">Binance</h4>
                  <div class="bg-slate-700 rounded-lg p-3">
                    <div class="text-xs text-slate-400">保证金率</div>
                    <div class="text-sm text-white">1000.00%</div>
                    <div class="text-xs text-slate-400">风险率</div>
                    <div class="text-sm text-white">100.00%</div>
                    <div class="text-xs text-slate-400">账户权益</div>
                    <div class="text-sm text-white">10000.00</div>
                  </div>
                </div>
                <div>
                  <h4 class="text-sm font-medium text-white mb-2">Bybit</h4>
                  <div class="bg-slate-700 rounded-lg p-3">
                    <div class="text-xs text-slate-400">保证金率</div>
                    <div class="text-sm text-white">2000.00%</div>
                    <div class="text-xs text-slate-400">风险率</div>
                    <div class="text-sm text-white">150.00%</div>
                    <div class="text-xs text-slate-400">账户权益</div>
                    <div class="text-sm text-white">15000.00</div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 紧急处理区 -->
          <section class="bg-slate-800 rounded-lg border border-slate-700 p-4">
            <h3 class="text-sm font-medium text-slate-300 mb-3">紧急处理</h3>
            <div class="grid grid-cols-3 gap-4">
              <div>
                <label class="block text-xs text-slate-400 mb-1">选择账户</label>
                <select class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white">
                  <option>Binance</option>
                  <option>Bybit</option>
                </select>
              </div>
              <div>
                <label class="block text-xs text-slate-400 mb-1">方向</label>
                <select class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white">
                  <option>买入</option>
                  <option>卖出</option>
                </select>
              </div>
              <div>
                <label class="block text-xs text-slate-400 mb-1">买入价</label>
                <input type="number" class="w-full px-3 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-white" value="0.01">
              </div>
            </div>
            <div class="mt-3 flex gap-2">
              <button @click="executeEmergencyTrade" :disabled="isExecutingTrade" :class="['px-4 py-2 text-white text-sm rounded transition-colors', isExecutingTrade ? 'bg-green-600 opacity-50 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700']">
                {{ isExecutingTrade ? '执行中...' : '执行交易' }}
              </button>
              <button @click="executePlatformClose" :disabled="isClosingPosition" :class="['px-4 py-2 text-white text-sm rounded transition-colors', isClosingPosition ? 'bg-red-600 opacity-50 cursor-not-allowed' : 'bg-red-600 hover:bg-red-700']">
                {{ isClosingPosition ? '平仓中...' : '平台平仓' }}
              </button>
            </div>
          </section>
        </main>
      </div>
    </div>

    <!-- 底部 -->
    <footer class="bg-slate-800 border-t border-slate-700 py-3 mt-6">
      <div class="container mx-auto px-4 text-center text-sm text-slate-400">
        <p>© 2026 Hustle XAU搬砖系统 - 基于FastAPI + Redis + PostgreSQL</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'

// 数据状态
const bybitData = ref({})
const binanceData = ref({})
const spreadData = ref({})
const spreadHistory = ref([])
const forwardConfig = ref({
  openPrice: 0,
  threshold: 0.5,
  qtyLimit: 1,
  stuckThreshold: 5,
  openSync: 5,
  closeSync: 5,
  isOpenEnabled: false,
  isCloseEnabled: false
})

// 正向套利阶梯配置
const forwardSteps = ref([
  {
    openPrice: 0,
    threshold: 0.7,
    qtyLimit: 1
  }
])
const reverseConfig = ref({
  openPrice: 0.08,
  threshold: 0.5,
  qtyLimit: 1,
  stuckThreshold: 5,
  openSync: 3,
  closeSync: 3,
  isOpenEnabled: false,
  isCloseEnabled: false
})

// 反向套利阶梯配置
const reverseSteps = ref([
  {
    openPrice: 0.08,
    threshold: 0.5,
    qtyLimit: 1
  }
])

// 登录/注册状态
const isLoggedIn = ref(false)
const userInfo = ref({})
const showLoginModal = ref(false)
const showRegisterModal = ref(false)
const loginForm = ref({
  username: '',
  password: ''
})
const registerForm = ref({
  username: '',
  email: '',
  password: ''
})
const isLoginLoading = ref(false)
const isRegisterLoading = ref(false)
const loginError = ref('')
const registerError = ref('')

// 配置相关状态
const isSavingConfig = ref(false)
const isSavingSteps = ref(false)
const isStoppingStrategy = ref(false)
const isExecutingTrade = ref(false)
const isClosingPosition = ref(false)
const isResettingCounter = ref(false)
const isBindingAccount = ref(false)
const isUnbindingAccount = ref(false)
const accountMessage = ref('')
const emergencyMessage = ref('')
const riskMessage = ref('')
const configMessage = ref('')

// 图表实例
let spreadChartInstance = null

// 模拟数据
const mockSpreadHistory = [
  { time: '23:33:06', bybitPrice: '4858.85', binancePrice: '4863.13', forwardSpread: '4.32', reverseSpread: '-4.11' },
  { time: '23:33:06', bybitPrice: '4858.85', binancePrice: '4863.13', forwardSpread: '4.12', reverseSpread: '-3.91' },
  { time: '23:33:06', bybitPrice: '4858.85', binancePrice: '4863.13', forwardSpread: '4.26', reverseSpread: '-4.05' },
  { time: '23:33:07', bybitPrice: '4858.85', binancePrice: '4863.13', forwardSpread: '4.26', reverseSpread: '-4.05' },
  { time: '23:33:07', bybitPrice: '4858.85', binancePrice: '4863.13', forwardSpread: '4.31', reverseSpread: '-4.10' },
  { time: '23:33:08', bybitPrice: '4858.85', binancePrice: '4863.13', forwardSpread: '4.31', reverseSpread: '-4.10' },
  { time: '23:33:08', bybitPrice: '4858.85', binancePrice: '4863.13', forwardSpread: '4.29', reverseSpread: '-4.08' }
]

// 初始化图表
const initSpreadChart = () => {
  const chartDom = document.querySelector('[ref="spreadChart"]')
  if (chartDom) {
    spreadChartInstance = echarts.init(chartDom)
    const option = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
          label: {
            backgroundColor: '#6a7985'
          }
        }
      },
      legend: {
        data: ['正向点差', '反向点差'],
        bottom: 10,
        textStyle: {
          color: '#94a3b8'
        }
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '15%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: mockSpreadHistory.map(item => item.time),
        axisLine: {
          lineStyle: {
            color: '#475569'
          }
        },
        axisLabel: {
          color: '#94a3b8'
        }
      },
      yAxis: {
        type: 'value',
        name: '点差',
        axisLine: {
          lineStyle: {
            color: '#475569'
          }
        },
        axisLabel: {
          color: '#94a3b8'
        },
        splitLine: {
          lineStyle: {
            color: '#334155'
          }
        }
      },
      series: [
        {
          name: '正向点差',
          type: 'line',
          data: mockSpreadHistory.map(item => parseFloat(item.forwardSpread)),
          smooth: true,
          lineStyle: {
            color: '#22c55e'
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(34, 197, 94, 0.3)' },
              { offset: 1, color: 'rgba(34, 197, 94, 0.1)' }
            ])
          }
        },
        {
          name: '反向点差',
          type: 'line',
          data: mockSpreadHistory.map(item => parseFloat(item.reverseSpread)),
          smooth: true,
          lineStyle: {
            color: '#ef4444'
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(239, 68, 68, 0.3)' },
              { offset: 1, color: 'rgba(239, 68, 68, 0.1)' }
            ])
          }
        }
      ]
    }
    spreadChartInstance.setOption(option)
  }
}

// 获取账户列表数据
const fetchAccountsList = async () => {
  try {
    console.log('正在获取账户列表数据...')
    const response = await axios.get('/api/v1/accounts/list')
    
    console.log('账户列表数据:', response.data)
    
    // 更新账户列表
    if (response.data && Array.isArray(response.data)) {
      // 处理账户数据，确保每个账户都有完整的字段
      accountsList.value = response.data.map(account => {
        // 调用账户详情API获取完整的账户数据
        const fetchAccountDetails = async (accountId) => {
          try {
            const detailResponse = await axios.get(`/api/v1/accounts/${accountId}`)
            return detailResponse.data
          } catch (error) {
            console.error(`获取账户 ${accountId} 详情失败:`, error)
            return {}
          }
        }
        
        // 构建完整的账户对象
        return {
          id: account.account_id || account.id || `account_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
          name: account.name || account.account_name || '未知账户',
          platform: account.platform || platformsList.value.find(p => p.platform_id === account.platform_id)?.platform_name || '未知平台',
          status: account.status || (account.is_active ? 'active' : 'inactive'),
          is_active: account.is_active || false,
          is_default: account.is_default || false,
          total_asset: account.total_asset || account.balance || '0.00',
          available_asset: account.available_asset || account.available_balance || '0.00',
          net_asset: account.net_asset || account.equity || '0.00',
          total_position: account.total_position || account.position || '0',
          frozen_asset: account.frozen_asset || account.frozen_balance || '0.00',
          daily_profit: account.daily_profit || account.profit || '0.00',
          margin_balance: account.margin_balance || '0.00',
          risk_ratio: account.risk_ratio || '0.00',
          funding_fee: account.funding_fee || '0.00',
          create_time: account.create_time || new Date().toISOString(),
          update_time: account.update_time || new Date().toISOString(),
          ...account
        }
      })
    } else {
      console.error('账户列表数据格式错误:', response.data)
      accountsList.value = []
    }
  } catch (error) {
    console.error('获取账户列表数据失败:', error)
    // 如果API调用失败，使用空数组
    accountsList.value = []
  }
}

// 获取账户详情数据
const fetchAccountDetails = async (accountId) => {
  try {
    console.log(`正在获取账户 ${accountId} 详情数据...`)
    const response = await axios.get(`/api/v1/accounts/${accountId}`)
    
    console.log(`账户 ${accountId} 详情数据:`, response.data)
    
    return response.data
  } catch (error) {
    console.error(`获取账户 ${accountId} 详情数据失败:`, error)
    return null
  }
}

// 获取行情数据
const fetchMarketData = async () => {
  try {
    console.log('正在获取行情数据...')
    // 检查是否有激活的账户
    const activeAccounts = accountsList.value.filter(account => account.status === 'active')
    if (activeAccounts.length === 0) {
      console.log('没有激活的账户，跳过行情数据获取')
      return
    }
    
    // 调用真实的行情数据API
    const [bybitRes, binanceRes, spreadRes] = await Promise.all([
      axios.get('/api/v1/market-data/bybit-mt5'),
      axios.get('/api/v1/market-data/binance'),
      axios.get('/api/v1/market-data/spread')
    ])
    
    console.log('Bybit MT5行情数据:', bybitRes.data)
    console.log('Binance行情数据:', binanceRes.data)
    console.log('点差数据:', spreadRes.data)
    
    // 验证数据完整性
    if (!bybitRes.data || !binanceRes.data || !spreadRes.data) {
      throw new Error('行情数据不完整')
    }
    
    // 更新行情数据
    bybitData.value = bybitRes.data
    binanceData.value = binanceRes.data
    spreadData.value = spreadRes.data
    
    // 更新点差历史
    if (spreadRes.data.forward_spread || spreadRes.data.reverse_spread) {
      spreadHistory.value.unshift({
        time: new Date().toLocaleTimeString(),
        forward: parseFloat(spreadRes.data.forward_spread) || 0,
        reverse: parseFloat(spreadRes.data.reverse_spread) || 0
      })
      
      // 限制历史数据长度
      if (spreadHistory.value.length > 100) {
        spreadHistory.value = spreadHistory.value.slice(0, 100)
      }
      
      // 更新图表
      updateSpreadChart()
    }
  } catch (error) {
    console.error('获取行情数据失败:', error)
    // 不再使用模拟数据，而是显示错误信息
    bybitData.value = {
      last_price: '0.00',
      ask: '0.00',
      bid: '0.00',
      update_time: new Date().toLocaleString(),
      error: error.message
    }
    binanceData.value = {
      last_price: '0.00',
      ask: '0.00',
      bid: '0.00',
      update_time: new Date().toLocaleString(),
      error: error.message
    }
    spreadData.value = {
      forward_spread: '0.00',
      reverse_spread: '0.00',
      binance_price: '0.00',
      bybit_mt5_price: '0.00',
      update_time: new Date().toLocaleString(),
      error: error.message
    }
  }
}

// 使用模拟行情数据
const useMockMarketData = () => {
  console.log('使用模拟行情数据')
  
  // 生成随机价格
  const binancePrice = 20000 + Math.random() * 1000
  const bybitPrice = binancePrice + (Math.random() - 0.5) * 2
  
  // 更新行情数据
  bybitData.value = {
    last_price: bybitPrice.toFixed(2),
    ask: (bybitPrice + 0.1).toFixed(2),
    bid: (bybitPrice - 0.1).toFixed(2),
    update_time: new Date().toLocaleString()
  }
  
  binanceData.value = {
    last_price: binancePrice.toFixed(2),
    ask: (binancePrice + 0.1).toFixed(2),
    bid: (binancePrice - 0.1).toFixed(2),
    update_time: new Date().toLocaleString()
  }
  
  // 计算点差
  const forwardSpread = parseFloat(bybitData.value.ask) - parseFloat(binanceData.value.bid)
  const reverseSpread = parseFloat(binanceData.value.ask) - parseFloat(bybitData.value.bid)
  
  spreadData.value = {
    forward_spread: forwardSpread.toFixed(4),
    reverse_spread: reverseSpread.toFixed(4),
    binance_price: binanceData.value.last_price,
    bybit_mt5_price: bybitData.value.last_price,
    update_time: new Date().toLocaleString()
  }
  
  // 更新点差历史
  spreadHistory.value.unshift({
    time: new Date().toLocaleTimeString(),
    forward: forwardSpread,
    reverse: reverseSpread
  })
  
  // 限制历史数据长度
  if (spreadHistory.value.length > 100) {
    spreadHistory.value = spreadHistory.value.slice(0, 100)
  }
  
  // 更新图表
  updateSpreadChart()
}

// 定时获取数据
let dataInterval = null

onMounted(() => {
  console.log('组件挂载，开始获取数据...')
  
  // 检查登录状态
  checkLoginStatus()
  
  // 初始化图表
  initSpreadChart()
  
  // 获取账户列表数据
  fetchAccountsList()
  
  // 开始定时获取数据
  fetchMarketData()
  dataInterval = setInterval(fetchMarketData, 1000)
  
  // 监听窗口 resize
  window.addEventListener('resize', () => {
    if (spreadChartInstance) {
      spreadChartInstance.resize()
    }
  })
  
  console.log('组件挂载完成，数据获取初始化')
})

onUnmounted(() => {
  // 清理定时器
  if (dataInterval) {
    clearInterval(dataInterval)
  }
  
  // 销毁图表实例
  if (spreadChartInstance) {
    spreadChartInstance.dispose()
  }
})

// 登录方法
const handleLogin = async () => {
  if (!loginForm.value.username || !loginForm.value.password) {
    loginError.value = '用户名和密码不能为空'
    return
  }
  
  isLoginLoading.value = true
  loginError.value = ''
  
  try {
    // 调用真实的登录 API
    const response = await axios.post('/api/v1/auth/login', {
      username: loginForm.value.username,
      password: loginForm.value.password
    })
    
    const { access_token, user } = response.data
    
    // 存储token和用户信息
    localStorage.setItem('access_token', access_token)
    localStorage.setItem('user', JSON.stringify(user))
    
    // 设置axios默认headers
    axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
    
    // 更新状态
    isLoggedIn.value = true
    userInfo.value = user
    showLoginModal.value = false
    
    // 重置表单
    loginForm.value = {
      username: '',
      password: ''
    }
    
    console.log('登录成功:', user)
  } catch (error) {
    loginError.value = error.response?.data?.detail || '登录失败，请检查用户名和密码'
    console.error('登录失败:', error)
  } finally {
    isLoginLoading.value = false
  }
}

// 注册方法
const handleRegister = async () => {
  if (!registerForm.value.username || !registerForm.value.email || !registerForm.value.password) {
    registerError.value = '请填写完整的注册信息'
    return
  }
  
  isRegisterLoading.value = true
  registerError.value = ''
  
  try {
    // 调用真实的注册 API
    const response = await axios.post('/api/v1/auth/register', {
      username: registerForm.value.username,
      email: registerForm.value.email,
      password: registerForm.value.password
    })
    
    const { access_token, user } = response.data
    
    // 存储token和用户信息
    localStorage.setItem('access_token', access_token)
    localStorage.setItem('user', JSON.stringify(user))
    
    // 设置axios默认headers
    axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
    
    // 更新状态
    isLoggedIn.value = true
    userInfo.value = user
    showRegisterModal.value = false
    
    // 重置表单
    registerForm.value = {
      username: '',
      email: '',
      password: ''
    }
    
    console.log('注册成功:', user)
  } catch (error) {
    registerError.value = error.response?.data?.detail || '注册失败，请稍后重试'
    console.error('注册失败:', error)
  } finally {
    isRegisterLoading.value = false
  }
}

// 退出登录方法
const logout = () => {
  // 清除本地存储
  localStorage.removeItem('access_token')
  localStorage.removeItem('user')
  
  // 更新状态
  isLoggedIn.value = false
  userInfo.value = {}
  
  console.log('退出登录成功')
}

// 检查登录状态
const checkLoginStatus = () => {
  const token = localStorage.getItem('access_token')
  const userStr = localStorage.getItem('user')
  
  if (token && userStr) {
    try {
      const user = JSON.parse(userStr)
      isLoggedIn.value = true
      userInfo.value = user
      
      // 设置axios默认headers
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
    } catch (error) {
      console.error('解析用户信息失败:', error)
      logout()
    }
  }
}

// 反向套利功能方法
const toggleReverseOpen = () => {
  reverseConfig.value.isOpenEnabled = !reverseConfig.value.isOpenEnabled
  console.log('反向套利开仓状态:', reverseConfig.value.isOpenEnabled)
}

const toggleReverseClose = () => {
  reverseConfig.value.isCloseEnabled = !reverseConfig.value.isCloseEnabled
  console.log('反向套利平仓状态:', reverseConfig.value.isCloseEnabled)
}

const saveReverseConfig = async () => {
  isSavingConfig.value = true
  configMessage.value = ''
  
  try {
    const response = await axios.post('/api/v1/strategy/config', {
      strategy_type: 'reverse',
      ...reverseConfig.value
    })
    
    configMessage.value = '配置保存成功'
    console.log('反向套利配置保存成功:', response.data)
    
    // 3秒后清除消息
    setTimeout(() => {
      configMessage.value = ''
    }, 3000)
  } catch (error) {
    configMessage.value = '配置保存失败'
    console.error('反向套利配置保存失败:', error)
  } finally {
    isSavingConfig.value = false
  }
}

const addReverseStep = () => {
  if (reverseSteps.value.length >= 5) return
  
  reverseSteps.value.push({
    openPrice: 0,
    threshold: 0.5,
    qtyLimit: 1
  })
  console.log('添加反向套利阶梯:', reverseSteps.value.length)
}

const removeReverseStep = (index) => {
  if (reverseSteps.value.length <= 1) return
  
  reverseSteps.value.splice(index, 1)
  console.log('删除反向套利阶梯:', index + 1)
}

const saveReverseSteps = async () => {
  isSavingSteps.value = true
  configMessage.value = ''
  
  try {
    const response = await axios.post('/api/v1/strategy/ladder', {
      strategy_type: 'reverse',
      ladder_steps: reverseSteps.value
    })
    
    configMessage.value = '阶梯配置保存成功'
    console.log('反向套利阶梯保存成功:', response.data)
    
    // 3秒后清除消息
    setTimeout(() => {
      configMessage.value = ''
    }, 3000)
  } catch (error) {
    configMessage.value = '阶梯配置保存失败'
    console.error('反向套利阶梯保存失败:', error)
  } finally {
    isSavingSteps.value = false
  }
}

// 正向套利功能方法
const toggleForwardOpen = () => {
  forwardConfig.value.isOpenEnabled = !forwardConfig.value.isOpenEnabled
  console.log('正向套利开仓状态:', forwardConfig.value.isOpenEnabled)
}

const toggleForwardClose = () => {
  forwardConfig.value.isCloseEnabled = !forwardConfig.value.isCloseEnabled
  console.log('正向套利平仓状态:', forwardConfig.value.isCloseEnabled)
}

const stopForwardStrategy = async () => {
  isStoppingStrategy.value = true
  configMessage.value = ''
  
  try {
    const response = await axios.post('/api/v1/strategy/stop', {
      strategy_type: 'forward'
    })
    
    // 停止策略后禁用开仓和平仓
    forwardConfig.value.isOpenEnabled = false
    forwardConfig.value.isCloseEnabled = false
    
    configMessage.value = '策略已停止'
    console.log('正向套利策略停止成功:', response.data)
    
    // 3秒后清除消息
    setTimeout(() => {
      configMessage.value = ''
    }, 3000)
  } catch (error) {
    configMessage.value = '策略停止失败'
    console.error('正向套利策略停止失败:', error)
  } finally {
    isStoppingStrategy.value = false
  }
}

const addForwardStep = () => {
  if (forwardSteps.value.length >= 5) return
  
  forwardSteps.value.push({
    openPrice: 0,
    threshold: 0.5,
    qtyLimit: 1
  })
  console.log('添加正向套利阶梯:', forwardSteps.value.length)
}

const removeForwardStep = (index) => {
  if (forwardSteps.value.length <= 1) return
  
  forwardSteps.value.splice(index, 1)
  console.log('删除正向套利阶梯:', index + 1)
}

const saveForwardSteps = async () => {
  isSavingSteps.value = true
  configMessage.value = ''
  
  try {
    const response = await axios.post('/api/v1/strategy/ladder', {
      strategy_type: 'forward',
      ladder_steps: forwardSteps.value
    })
    
    configMessage.value = '阶梯配置保存成功'
    console.log('正向套利阶梯保存成功:', response.data)
    
    // 3秒后清除消息
    setTimeout(() => {
      configMessage.value = ''
    }, 3000)
  } catch (error) {
    configMessage.value = '阶梯配置保存失败'
    console.error('正向套利阶梯保存失败:', error)
  } finally {
    isSavingSteps.value = false
  }
}

// 紧急处理功能方法
const executeEmergencyTrade = async () => {
  isExecutingTrade.value = true
  emergencyMessage.value = ''
  
  try {
    const response = await axios.post('/api/v1/emergency/trade', {
      account: 'Binance', // 默认选择第一个账户
      direction: '买入', // 默认选择买入
      price: 0.01 // 默认价格
    })
    
    emergencyMessage.value = '紧急交易执行成功'
    console.log('紧急交易执行成功:', response.data)
    
    // 3秒后清除消息
    setTimeout(() => {
      emergencyMessage.value = ''
    }, 3000)
  } catch (error) {
    emergencyMessage.value = '紧急交易执行失败'
    console.error('紧急交易执行失败:', error)
  } finally {
    isExecutingTrade.value = false
  }
}

const executePlatformClose = async () => {
  isClosingPosition.value = true
  emergencyMessage.value = ''
  
  try {
    const response = await axios.post('/api/v1/emergency/close', {
      account: 'Binance' // 默认选择第一个账户
    })
    
    emergencyMessage.value = '平台平仓成功'
    console.log('平台平仓成功:', response.data)
    
    // 3秒后清除消息
    setTimeout(() => {
      emergencyMessage.value = ''
    }, 3000)
  } catch (error) {
    emergencyMessage.value = '平台平仓失败'
    console.error('平台平仓失败:', error)
  } finally {
    isClosingPosition.value = false
  }
}

// 风控状态功能方法
const resetRiskCounter = async () => {
  isResettingCounter.value = true
  riskMessage.value = ''
  
  try {
    const response = await axios.post('/api/v1/risk/reset')
    
    riskMessage.value = '风控计数重置成功'
    console.log('风控计数重置成功:', response.data)
    
    // 3秒后清除消息
    setTimeout(() => {
      riskMessage.value = ''
    }, 3000)
  } catch (error) {
    riskMessage.value = '风控计数重置失败'
    console.error('风控计数重置失败:', error)
  } finally {
    isResettingCounter.value = false
  }
}

// 功能菜单导航方法
const navigateTo = (page) => {
  console.log('导航到:', page)
  
  // 这里可以实现页面导航逻辑
  // 由于当前是单页应用，我们可以通过状态管理来切换不同的内容区域
  
  switch (page) {
    case 'strategy':
      // 导航到策略控制页面
      console.log('导航到策略控制页面')
      break
    case 'settings':
      // 导航到参数设置页面
      console.log('导航到参数设置页面')
      break
    case 'history':
      // 导航到历史数据页面
      console.log('导航到历史数据页面')
      break
    case 'version':
      // 导航到版本管理页面
      console.log('导航到版本管理页面')
      break
    case 'scripts':
      // 导航到脚本管理页面
      console.log('导航到脚本管理页面')
      break
    default:
      break
  }
}

// 账户管理功能方法
const connectAccount = async (accountName) => {
  isBindingAccount.value = true
  accountMessage.value = ''
  
  try {
    // 找到对应的账户
    const account = accountsList.value.find(a => a.name === accountName)
    if (!account) {
      throw new Error('账户不存在')
    }
    
    // 调用真实的账户连接API
    const response = await axios.post('/api/v1/accounts/connect', {
      account_id: account.id
    })
    
    accountMessage.value = `账户 ${accountName} 连接成功`
    console.log(`账户 ${accountName} 连接成功:`, response.data)
    
    // 更新账户状态为active
    account.status = 'active'
    account.is_active = true
    
    // 连接成功后立即获取账户列表和行情数据
    await fetchAccountsList()
    await fetchMarketData()
    
    // 3秒后清除消息
    setTimeout(() => {
      accountMessage.value = ''
    }, 3000)
  } catch (error) {
    accountMessage.value = `账户 ${accountName} 连接失败: ${error.message}`
    console.error(`账户 ${accountName} 连接失败:`, error)
  } finally {
    isBindingAccount.value = false
  }
}

const disconnectAccount = async (accountName) => {
  isUnbindingAccount.value = true
  accountMessage.value = ''
  
  try {
    // 找到对应的账户
    const account = accountsList.value.find(a => a.name === accountName)
    if (!account) {
      throw new Error('账户不存在')
    }
    
    // 调用真实的账户断开API
    const response = await axios.post('/api/v1/accounts/disconnect', {
      account_id: account.id
    })
    
    accountMessage.value = `账户 ${accountName} 断开成功`
    console.log(`账户 ${accountName} 断开成功:`, response.data)
    
    // 更新账户状态为inactive
    account.status = 'inactive'
    account.is_active = false
    
    // 断开成功后更新账户列表和行情数据
    await fetchAccountsList()
    await fetchMarketData()
    
    // 3秒后清除消息
    setTimeout(() => {
      accountMessage.value = ''
    }, 3000)
  } catch (error) {
    accountMessage.value = `账户 ${accountName} 断开失败: ${error.message}`
    console.error(`账户 ${accountName} 断开失败:`, error)
  } finally {
    isUnbindingAccount.value = false
  }
}

// 顶部导航栏功能方法
const showProfitDetails = () => {
  console.log('显示总盈利详情')
  // 这里应该显示一个模态框或侧边栏，展示详细的盈利数据
  // 为了简化，我们直接在控制台输出信息
  console.log('总盈利详情:', {
    today: '-0.00',
    week: '-0.00',
    month: '-0.00',
    total: '-0.00'
  })
}

// 账户管理相关状态
const showAccountsModal = ref(false)
const showStrategyModal = ref(false)
const showProfitModal = ref(false)
// 账户列表，初始为空，从API获取
const accountsList = ref([])
const profitDetails = ref({
  today: '0.00',
  week: '0.00',
  month: '0.00',
  total: '0.00'
})
const recentTrades = ref([
  {
    time: '2026-02-18 10:00:00',
    strategy_type: '正向套利',
    symbol: 'XAUUSDT',
    profit: 15.50
  },
  {
    time: '2026-02-18 09:30:00',
    strategy_type: '反向套利',
    symbol: 'XAUUSD.s',
    profit: -8.20
  }
])
const totalProfit = ref('-0.00')

// 账户管理相关状态
const showAccountModal = ref(false)
const isEditingAccount = ref(false)
const editingAccount = ref({})
const isSavingAccount = ref(false)
const accountFormMessage = ref('')
const accountFormMessageType = ref('success')
const isTogglingStatus = ref(false)
const platformsList = ref([
  { platform_id: 1, platform_name: 'Binance' },
  { platform_id: 2, platform_name: 'Bybit' }
])

// 账户管理相关方法
const editAccount = (accountId) => {
  console.log('编辑账户:', accountId)
  const account = accountsList.value.find(a => a.id === accountId)
  if (account) {
    editingAccount.value = { ...account }
    isEditingAccount.value = true
    showAccountModal.value = true
  }
}

const toggleAccountStatus = async (accountId) => {
  console.log('切换账户状态:', accountId)
  const account = accountsList.value.find(a => a.id === accountId)
  if (!account) return
  
  isTogglingStatus.value = true
  
  try {
    // 构建更新数据
    const updateData = {
      is_active: account.status !== 'active'
    }
    
    // 调用后端API更新账户状态
    const response = await axios.put(`/api/v1/accounts/${accountId}`, updateData)
    
    if (response.status === 200) {
      // 更新本地账户状态
      account.status = account.status === 'active' ? 'inactive' : 'active'
      account.is_active = account.status === 'active'
      
      console.log('账户状态更新成功:', accountId, account.status)
      
      // 显示成功提示
      accountFormMessage.value = account.status === 'active' ? '账户激活成功' : '账户禁用成功'
      accountFormMessageType.value = 'success'
      
      // 3秒后清除提示
      setTimeout(() => {
        accountFormMessage.value = ''
      }, 3000)
    }
  } catch (error) {
    console.error('账户状态更新失败:', error)
    
    // 显示失败提示
    accountFormMessage.value = `账户状态更新失败: ${error.message}`
    accountFormMessageType.value = 'error'
    
    // 3秒后清除提示
    setTimeout(() => {
      accountFormMessage.value = ''
    }, 5000)
  } finally {
    isTogglingStatus.value = false
  }
}

const addNewAccount = () => {
  console.log('添加新账户')
  editingAccount.value = {
    account_name: '',
    platform_id: 1,
    api_key: '',
    api_secret: '',
    passphrase: '',
    mt5_id: '',
    mt5_server: '',
    mt5_primary_pwd: '',
    is_mt5_account: false,
    is_default: false,
    is_active: true
  }
  isEditingAccount.value = false
  showAccountModal.value = true
}

const saveAccount = async () => {
  // 表单验证
  if (!editingAccount.value.account_name) {
    accountFormMessage.value = '请输入账户名称'
    accountFormMessageType.value = 'error'
    return
  }
  if (!editingAccount.value.api_key) {
    accountFormMessage.value = '请输入API密钥'
    accountFormMessageType.value = 'error'
    return
  }
  if (!editingAccount.value.api_secret) {
    accountFormMessage.value = '请输入API秘钥'
    accountFormMessageType.value = 'error'
    return
  }
  
  // MT5账户验证
  if (editingAccount.value.is_mt5_account) {
    if (!editingAccount.value.mt5_id) {
      accountFormMessage.value = '请输入MT5账号ID'
      accountFormMessageType.value = 'error'
      return
    }
    if (!editingAccount.value.mt5_server) {
      accountFormMessage.value = '请输入MT5服务器地址'
      accountFormMessageType.value = 'error'
      return
    }
    if (!editingAccount.value.mt5_primary_pwd) {
      accountFormMessage.value = '请输入MT5主密码'
      accountFormMessageType.value = 'error'
      return
    }
  }
  
  isSavingAccount.value = true
  accountFormMessage.value = ''
  
  // 超时函数
  const timeoutPromise = new Promise((_, reject) => {
    setTimeout(() => {
      reject(new Error('API调用超时'))
    }, 30000) // 30秒超时
  })
  
  try {
    // 构建完整的账户数据
    const accountData = {
      ...editingAccount.value,
      create_time: new Date().toISOString(),
      update_time: new Date().toISOString()
    }
    
    console.log('保存账户数据:', accountData)
    console.log('API调用开始...')
    
    // 调用API保存账户数据
    let response
    const startTime = Date.now()
    
    // 使用Promise.race实现超时机制
    if (isEditingAccount.value) {
      // 更新账户
      console.log('更新账户API调用:', `/api/v1/accounts/${editingAccount.value.id}`)
      response = await Promise.race([
        axios.put(`/api/v1/accounts/${editingAccount.value.id}`, accountData),
        timeoutPromise
      ])
      accountFormMessage.value = '账户更新成功'
    } else {
      // 添加新账户
      console.log('添加账户API调用:', '/api/v1/accounts')
      response = await Promise.race([
        axios.post('/api/v1/accounts', accountData),
        timeoutPromise
      ])
      accountFormMessage.value = '账户添加成功'
    }
    const endTime = Date.now()
    console.log(`API调用完成，耗时: ${endTime - startTime}ms`)
    
    console.log('账户保存成功:', response.data)
    
    // 重新获取账户列表，确保数据与数据库一致
    await fetchAccountsList()
    
    accountFormMessageType.value = 'success'
    
    // 关闭模态框
    setTimeout(() => {
      showAccountModal.value = false
      editingAccount.value = {}
    }, 1000)
  } catch (error) {
    // 记录错误日志
    const errorLog = {
      timestamp: new Date().toISOString(),
      action: isEditingAccount.value ? '更新账户' : '添加账户',
      accountName: editingAccount.value.account_name,
      error: error.message,
      stack: error.stack,
      userAgent: navigator.userAgent,
      screenSize: `${window.screen.width}x${window.screen.height}`,
      config: error.config,
      response: error.response
    }
    
    console.error('保存账户失败:', errorLog)
    
    // 显示错误提示
    if (error.response) {
      // 服务器返回了错误响应
      accountFormMessage.value = `保存失败: ${error.response.status} ${error.response.statusText}`
    } else if (error.request) {
      // 请求已经发送，但是没有收到响应
      accountFormMessage.value = '保存失败: 服务器无响应，请检查网络连接'
    } else {
      // 请求配置出错
      accountFormMessage.value = `保存失败: ${error.message}`
    }
    accountFormMessageType.value = 'error'
  } finally {
    console.log('执行finally块，重置isSavingAccount状态')
    isSavingAccount.value = false
  }
}

// 策略管理相关方法
const toggleForwardStrategy = () => {
  forwardConfig.value.isOpenEnabled = !forwardConfig.value.isOpenEnabled
  console.log('正向套利策略状态:', forwardConfig.value.isOpenEnabled)
}

const toggleReverseStrategy = () => {
  reverseConfig.value.isOpenEnabled = !reverseConfig.value.isOpenEnabled
  console.log('反向套利策略状态:', reverseConfig.value.isOpenEnabled)
}

// 数据库管理相关状态
const showDatabaseModal = ref(false)
const activeDatabaseTab = ref('connection')
const databaseConfig = ref({
  type: 'postgresql',
  host: 'localhost',
  port: 5432,
  database: 'hustle_db',
  username: 'admin',
  password: 'password'
})
const isTestingConnection = ref(false)
const connectionMessage = ref('')
const connectionMessageType = ref('success')

const tablesList = ref([
  { name: 'users', rows: 0, columns: 7 },
  { name: 'accounts', rows: 2, columns: 15 },
  { name: 'platforms', rows: 2, columns: 6 },
  { name: 'strategy_configs', rows: 2, columns: 8 },
  { name: 'order_records', rows: 0, columns: 12 },
  { name: 'arbitrage_tasks', rows: 0, columns: 8 },
  { name: 'risk_alerts', rows: 0, columns: 6 }
])
const tableSearch = ref('')
const filteredTables = ref(tablesList.value)

const sqlQuery = ref('')
const queryResult = ref([])
const isExecutingQuery = ref(false)
const queryMessage = ref('')
const queryMessageType = ref('success')

const importTable = ref('')
const exportTable = ref('')
const exportFormat = ref('csv')
const isImporting = ref(false)
const isExporting = ref(false)
const importExportMessage = ref('')
const importExportMessageType = ref('success')

const performanceMetrics = ref({
  connections: 1,
  max_connections: 100,
  query_time: 15,
  avg_query_time: 10,
  cache_hit_rate: 85,
  cache_size: 100,
  disk_usage: 500,
  total_disk: 1000,
  version: 'PostgreSQL 15.4'
})

// 表数据和结构相关状态
const showTableDataModal = ref(false)
const showTableStructureModal = ref(false)
const showEditModal = ref(false)
const currentTable = ref('')
const tableData = ref([])
const tableColumns = ref([])
const tableStructure = ref([])
const editingRow = ref({})
const editingIndex = ref(-1)
const isSavingEdit = ref(false)
const recentQueries = ref([
  {
    time: '2026-02-18 10:00:00',
    sql: 'SELECT * FROM accounts WHERE is_active = true',
    execution_time: 10,
    success: true
  },
  {
    time: '2026-02-18 09:30:00',
    sql: 'SELECT * FROM users',
    execution_time: 5,
    success: true
  }
])

// 数据库管理相关方法
const testDatabaseConnection = async () => {
  isTestingConnection.value = true
  connectionMessage.value = ''
  
  try {
    // 调用真实的数据库连接测试 API
    const response = await axios.post('/api/database/test-connection', databaseConfig.value)
    connectionMessage.value = response.data.message || '连接测试成功'
    connectionMessageType.value = 'success'
    console.log('数据库连接测试成功')
  } catch (error) {
    connectionMessage.value = error.response?.data?.detail || '连接测试失败'
    connectionMessageType.value = 'error'
    console.error('数据库连接测试失败:', error)
  } finally {
    isTestingConnection.value = false
  }
}

const saveDatabaseConfig = async () => {
  isSavingConfig.value = true
  connectionMessage.value = ''
  
  try {
    // 调用真实的数据库配置保存 API
    const response = await axios.post('/api/database/save-config', databaseConfig.value)
    connectionMessage.value = response.data.message || '配置保存成功'
    connectionMessageType.value = 'success'
    console.log('数据库配置保存成功:', databaseConfig.value)
  } catch (error) {
    connectionMessage.value = error.response?.data?.detail || '配置保存失败'
    connectionMessageType.value = 'error'
    console.error('数据库配置保存失败:', error)
  } finally {
    isSavingConfig.value = false
  }
}

const refreshTables = async () => {
  console.log('刷新数据表列表')
  try {
    // 调用真实的获取数据表列表 API
    const response = await axios.get('/api/database/tables')
    tablesList.value = response.data
    filteredTables.value = tablesList.value.filter(table => 
      table.name.toLowerCase().includes(tableSearch.value.toLowerCase())
    )
    console.log('数据表列表刷新成功:', tablesList.value)
  } catch (error) {
    console.error('刷新数据表列表失败:', error)
  }
}

const viewTableData = async (tableName) => {
  console.log('查看表数据:', tableName)
  currentTable.value = tableName
  
  // 显示加载状态
  isLoading.value = true
  
  try {
    // 从真实API获取数据
    const response = await axios.get(`/api/database/tables/${tableName}/data`)
    
    const data = response.data
    tableData.value = data.data || []
    tableColumns.value = data.columns || []
    
    console.log('表数据加载成功:', tableName, tableData.value.length, '条记录')
  } catch (error) {
    console.error('加载表数据失败:', error)
    
    // 加载失败时显示错误信息
    tableColumns.value = []
    tableData.value = []
    alert(`加载表数据失败: ${error.response?.data?.detail || error.message}`)
  } finally {
    // 隐藏加载状态
    isLoading.value = false
  }
  
  showTableDataModal.value = true
}

const viewTableStructure = async (tableName) => {
  console.log('查看表结构:', tableName)
  currentTable.value = tableName
  
  try {
    // 从真实API获取表结构
    const response = await axios.get(`/api/database/tables/${tableName}/structure`)
    
    tableStructure.value = response.data || []
    
    console.log('表结构加载成功:', tableName, tableStructure.value.length, '个字段')
  } catch (error) {
    console.error('加载表结构失败:', error)
    
    // 加载失败时显示错误信息
    tableStructure.value = []
    alert(`加载表结构失败: ${error.response?.data?.detail || error.message}`)
  }
  
  showTableStructureModal.value = true
}

// 数据操作相关方法
const addTableRow = async () => {
  console.log('添加数据行:', currentTable.value)
  
  // 创建新数据行
  const newRow = {}
  tableColumns.value.forEach(column => {
    if (column.includes('_id')) {
      newRow[column] = 'new-' + Date.now()
    } else if (column.includes('time')) {
      newRow[column] = new Date().toISOString().slice(0, 19).replace('T', ' ')
    } else if (column === 'is_active' || column === 'is_enabled' || column === 'is_mt5_account' || column === 'is_default') {
      newRow[column] = true
    } else if (column === 'retry_times' || column === 'mt5_stuck_threshold') {
      newRow[column] = 3
    } else if (column === 'target_spread' || column === 'order_qty' || column === 'open_spread' || column === 'close_spread' || column === 'profit') {
      newRow[column] = 0
    } else {
      newRow[column] = ''
    }
  })
  
  // 添加到本地数据
  tableData.value.push(newRow)
  console.log('添加新数据:', newRow)
  
  // 尝试保存到数据库
  try {
    const response = await axios.post(`/api/database/tables/${currentTable.value}/data`, newRow)
    
    const result = response.data
    console.log('数据添加成功:', result)
    
    // 更新为服务器返回的真实数据
    if (result.data) {
      tableData.value[tableData.value.length - 1] = result.data
    }
  } catch (error) {
    console.error('数据添加失败:', error)
    // 从本地数据中移除
    tableData.value.pop()
    alert(`添加数据失败: ${error.response?.data?.detail || error.message}`)
  }
}

const editTableRow = (index) => {
  console.log('编辑数据行:', index)
  editingIndex.value = index
  editingRow.value = { ...tableData.value[index] }
  showEditModal.value = true
}

const saveEdit = async () => {
  if (editingIndex.value === -1) return
  
  isSavingEdit.value = true
  
  try {
    // 保存到数据库
    const primaryKey = editingRow.value[tableColumns.value[0]]
    const response = await axios.put(`/api/database/tables/${currentTable.value}/data/${primaryKey}`, editingRow.value)
    
    const result = response.data
    console.log('数据保存成功:', result)
    
    // 更新本地数据
    tableData.value[editingIndex.value] = { ...editingRow.value }
    
    // 关闭模态框
    showEditModal.value = false
    editingIndex.value = -1
    editingRow.value = {}
  } catch (error) {
    console.error('保存编辑失败:', error)
    alert(`保存失败: ${error.response?.data?.detail || error.message}`)
  } finally {
    isSavingEdit.value = false
  }
}

const deleteTableRow = async (index) => {
  console.log('删除数据行:', index)
  if (!confirm('确定要删除这行数据吗？')) {
    return
  }
  
  const rowToDelete = tableData.value[index]
  const primaryKey = rowToDelete[tableColumns.value[0]]
  
  // 从本地数据中移除
  tableData.value.splice(index, 1)
  
  // 尝试从数据库中删除
  try {
    const response = await axios.delete(`/api/database/tables/${currentTable.value}/data/${primaryKey}`)
    
    const result = response.data
    console.log('数据删除成功:', result)
  } catch (error) {
    console.error('数据删除失败:', error)
    // 恢复本地数据
    tableData.value.splice(index, 0, rowToDelete)
    alert(`删除数据失败: ${error.response?.data?.detail || error.message}`)
  }
}

const refreshTableData = async () => {
  console.log('刷新表数据:', currentTable.value)
  // 重新加载表数据
  await viewTableData(currentTable.value)
}

const executeQuery = async () => {
  if (!sqlQuery.value.trim()) {
    queryMessage.value = '请输入SQL查询语句'
    queryMessageType.value = 'error'
    return
  }
  
  isExecutingQuery.value = true
  queryMessage.value = '正在执行查询...'
  queryMessageType.value = 'info'
  
  try {
    // 执行真实的SQL查询
    const response = await axios.post('/api/database/query', {
      sql: sqlQuery.value
    })
    
    const result = response.data
    queryResult.value = result.data || []
    
    queryMessage.value = '查询执行成功'
    queryMessageType.value = 'success'
    console.log('查询执行成功:', sqlQuery.value, queryResult.value.length, '条记录')
  } catch (error) {
    console.error('查询执行失败:', error)
    queryMessage.value = `查询执行失败: ${error.response?.data?.detail || error.message}`
    queryMessageType.value = 'error'
  } finally {
    isExecutingQuery.value = false
  }
}

const clearQuery = () => {
  sqlQuery.value = ''
  queryResult.value = []
  queryMessage.value = ''
}

const handleFileUpload = (event) => {
  const file = event.target.files[0]
  console.log('文件上传:', file)
  // 这里应该处理文件上传逻辑
}

const importData = async () => {
  if (!importTable.value) {
    importExportMessage.value = '请选择要导入的表'
    importExportMessageType.value = 'error'
    return
  }
  
  // 检查是否有选择文件
  if (!window.importFile) {
    importExportMessage.value = '请选择要导入的文件'
    importExportMessageType.value = 'error'
    return
  }
  
  isImporting.value = true
  importExportMessage.value = ''
  
  try {
    const formData = new FormData()
    formData.append('file', window.importFile)
    formData.append('table', importTable.value)
    
    const response = await axios.post('/api/database/import', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
    
    importExportMessage.value = response.data.message || '数据导入成功'
    importExportMessageType.value = 'success'
    console.log('数据导入成功:', importTable.value)
  } catch (error) {
    importExportMessage.value = error.response?.data?.detail || '数据导入失败'
    importExportMessageType.value = 'error'
    console.error('数据导入失败:', error)
  } finally {
    isImporting.value = false
  }
}

const exportData = async () => {
  if (!exportTable.value) {
    importExportMessage.value = '请选择要导出的表'
    importExportMessageType.value = 'error'
    return
  }
  
  isExporting.value = true
  importExportMessage.value = ''
  
  try {
    // 调用真实的导出 API
    const response = await axios.get('/api/database/export', {
      params: {
        table: exportTable.value,
        format: exportFormat.value
      },
      responseType: 'blob'
    })
    
    // 创建下载链接
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `${exportTable.value}.${exportFormat.value}`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    
    importExportMessage.value = '数据导出成功'
    importExportMessageType.value = 'success'
    console.log('数据导出成功:', exportTable.value, exportFormat.value)
  } catch (error) {
    if (error.name === 'AbortError') {
      importExportMessage.value = '导出操作已取消'
      importExportMessageType.value = 'error'
    } else {
      importExportMessage.value = error.response?.data?.detail || '数据导出失败'
      importExportMessageType.value = 'error'
      console.error('数据导出失败:', error)
    }
  } finally {
    isExporting.value = false
  }
}

const refreshMetrics = async () => {
  console.log('刷新性能指标')
  try {
    // 调用真实的性能指标 API
    const response = await axios.get('/api/database/metrics')
    performanceMetrics.value = response.data
    console.log('性能指标刷新成功:', performanceMetrics.value)
  } catch (error) {
    console.error('刷新性能指标失败:', error)
  }
}

// 监听表搜索变化
watch(tableSearch, (newSearch) => {
  filteredTables.value = tablesList.value.filter(table => 
    table.name.toLowerCase().includes(newSearch.toLowerCase())
  )
})

// 账户删除相关方法
const confirmDeleteAccount = (accountId) => {
  if (confirm('确定要删除这个账户吗？此操作不可撤销。')) {
    deleteAccount(accountId)
  }
}

const deleteAccount = async (accountId) => {
  try {
    // 调用后端API删除账户
    const response = await fetch(`/api/v1/accounts/${accountId}`, {
      method: 'DELETE'
    })
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`)
    }
    
    // 从本地列表中移除账户
    const accountIndex = accountsList.value.findIndex(acc => acc.id === accountId)
    if (accountIndex !== -1) {
      accountsList.value.splice(accountIndex, 1)
      console.log('账户删除成功:', accountId)
      
      // 显示成功提示
      accountMessage.value = '账户删除成功'
      accountMessageType.value = 'success'
      
      // 3秒后清除提示
      setTimeout(() => {
        accountMessage.value = ''
      }, 3000)
    }
  } catch (error) {
    console.error('账户删除失败:', error)
    // 显示失败提示
    accountMessage.value = `账户删除失败: ${error.message}`
    accountMessageType.value = 'error'
    
    // 3秒后清除提示
    setTimeout(() => {
      accountMessage.value = ''
    }, 5000)
  }
}

// 监听配置变化
watch(forwardConfig, (newConfig) => {
  console.log('正向套利配置变化:', newConfig)
}, { deep: true })

watch(reverseConfig, (newConfig) => {
  console.log('反向套利配置变化:', newConfig)
}, { deep: true })
</script>

<style scoped>
/* 组件特定样式 */
</style>
