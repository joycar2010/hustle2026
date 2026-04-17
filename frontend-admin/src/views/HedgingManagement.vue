<template>
  <div class="min-h-screen bg-dark-300 text-text-primary p-4 md:p-6">
    <h1 class="text-xl font-bold mb-6">对冲平台管理</h1>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 bg-dark-200 rounded-lg p-1 w-fit">
      <button v-for="t in tabs" :key="t.key" @click="activeTab = t.key"
        class="px-4 py-1.5 text-xs rounded-md transition-colors"
        :class="activeTab === t.key ? 'bg-primary text-dark-300 font-medium' : 'text-text-secondary hover:text-text-primary'">
        {{ t.label }}
      </button>
    </div>

    <!-- ═══════ 对冲产品对 ═══════ -->
    <div v-if="activeTab === 'pairs'" class="space-y-4">
      <div class="flex justify-end mb-2">
        <button @click="createPair" class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 text-xs font-medium rounded-lg">+ 新增对冲对</button>
      </div>
      <div v-for="pair in pairs" :key="pair.id"
        class="bg-dark-100 rounded-xl border border-border-primary p-5">
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-3">
            <span class="text-lg font-bold">{{ pair.pair_name }}</span>
            <span class="px-2 py-0.5 rounded text-xs bg-primary/20 text-primary font-mono">{{ pair.pair_code }}</span>
            <button @click="togglePairActive(pair)" :class="pair.is_active ? 'text-success hover:text-red-400' : 'text-text-tertiary hover:text-success'" class="text-xs cursor-pointer">{{ pair.is_active ? '● 启用' : '○ 禁用' }}</button>
          </div>
          <div class="flex gap-2">
            <button @click="editPair(pair)" class="text-xs px-3 py-1 bg-dark-200 hover:bg-dark-50 rounded-lg">编辑</button>
            <button @click="deletePair(pair)" class="text-xs px-3 py-1 bg-red-900/30 hover:bg-red-900/50 text-red-300 rounded-lg">删除</button>
          </div>
        </div>

        <!-- Two-side layout -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- Side A -->
          <div class="bg-dark-200 rounded-lg p-3 border border-border-primary">
            <div class="text-xs text-text-tertiary mb-2 font-medium">主账号 (A侧)</div>
            <div v-if="pair.platform_a" class="space-y-1">
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">平台</span><span class="text-xs font-medium">{{ pair.platform_a.display_name }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">产品</span><span class="text-xs font-mono text-primary">{{ pair.symbol_a?.symbol }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">合约面值</span><span class="text-xs font-mono">{{ pair.symbol_a?.contract_unit }} {{ pair.symbol_a?.qty_unit }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">数量精度</span><span class="text-xs font-mono">{{ pair.symbol_a?.qty_precision }}位 / 步长{{ pair.symbol_a?.qty_step }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">价格精度</span><span class="text-xs font-mono">{{ pair.symbol_a?.price_precision }}位 / tick {{ pair.symbol_a?.price_step }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">Maker/Taker</span><span class="text-xs font-mono">{{ (pair.symbol_a?.maker_fee_rate*100).toFixed(2) }}% / {{ (pair.symbol_a?.taker_fee_rate*100).toFixed(2) }}%</span></div>
            </div>
          </div>
          <!-- Side B -->
          <div class="bg-dark-200 rounded-lg p-3 border border-border-primary">
            <div class="text-xs text-text-tertiary mb-2 font-medium">对冲账号 (B侧)</div>
            <div v-if="pair.platform_b" class="space-y-1">
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">平台</span><span class="text-xs font-medium">{{ pair.platform_b.display_name }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">产品</span><span class="text-xs font-mono text-primary">{{ pair.symbol_b?.symbol }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">合约面值</span><span class="text-xs font-mono">{{ pair.symbol_b?.contract_unit }} {{ pair.symbol_b?.qty_unit }}/手</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">数量精度</span><span class="text-xs font-mono">{{ pair.symbol_b?.qty_precision }}位 / 步长{{ pair.symbol_b?.qty_step }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">价格精度</span><span class="text-xs font-mono">{{ pair.symbol_b?.price_precision }}位 / tick {{ pair.symbol_b?.price_step }}</span></div>
              <div class="flex justify-between"><span class="text-xs text-text-tertiary">保证金率</span><span class="text-xs font-mono">{{ (pair.symbol_b?.margin_rate_initial*100).toFixed(1) }}%</span></div>
            </div>
          </div>
        </div>

        <!-- Conversion & spread info -->
        <div class="mt-3 flex flex-wrap gap-4 text-xs text-text-tertiary">
          <span>换算因子: <span class="text-text-secondary font-mono">1 {{ pair.symbol_b?.qty_unit }} = {{ pair.conversion_factor }} {{ pair.symbol_a?.qty_unit }}</span></span>
          <span>点差模式: <span class="text-text-secondary">{{ pair.spread_mode }}</span></span>
          <span>点差精度: <span class="text-text-secondary font-mono">{{ pair.spread_precision }}位</span></span>
          <span v-if="pair.default_spread_target">参考点差: <span class="text-text-secondary font-mono">{{ pair.default_spread_target }}</span></span>
          <span>USD/USDT: <span class="text-text-secondary font-mono">{{ pair.usd_usdt_rate }}</span></span>
        </div>
      </div>

      <div v-if="!pairs.length" class="text-center py-12 text-text-tertiary text-sm">暂无对冲产品对配置</div>
    </div>

    <!-- ═══════ 平台品种 ═══════ -->
    <div v-if="activeTab === 'symbols'" class="space-y-3">
      <div class="flex justify-between items-center mb-2">
        <div class="flex gap-2">
          <button v-for="p in platforms" :key="p.platform_id" @click="symbolFilter = p.platform_id"
            class="px-3 py-1 text-xs rounded-lg transition-colors"
            :class="symbolFilter === p.platform_id ? 'bg-primary text-dark-300' : 'bg-dark-200 text-text-secondary hover:text-text-primary'">
            {{ p.display_name || p.platform_name }}
          </button>
          <button @click="symbolFilter = null"
            class="px-3 py-1 text-xs rounded-lg transition-colors"
            :class="symbolFilter === null ? 'bg-primary text-dark-300' : 'bg-dark-200 text-text-secondary'">全部</button>
        </div>
        <button @click="editingSymbol = { platform_id: platforms[0]?.platform_id || 1, symbol: '', base_asset: '', quote_asset: 'USD', contract_unit: 1, qty_unit: '', qty_precision: 2, qty_step: 0.01, min_qty: 0.01, price_precision: 2, price_step: 0.01, maker_fee_rate: 0, taker_fee_rate: 0, margin_rate_initial: 0, product_type: 'perpetual' }" class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 text-xs font-medium rounded-lg">+ 新增品种</button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
            <th class="text-left py-2 px-3">平台</th>
            <th class="text-left py-2 px-3">符号</th>
            <th class="text-left py-2 px-3">资产</th>
            <th class="text-right py-2 px-3">合约面值</th>
            <th class="text-right py-2 px-3">数量精度</th>
            <th class="text-right py-2 px-3">最小量</th>
            <th class="text-right py-2 px-3">价格精度</th>
            <th class="text-right py-2 px-3">Maker/Taker</th>
            <th class="text-center py-2 px-3">类型</th>
            <th class="text-right py-2 px-3">保证金率</th>
            <th class="text-center py-2 px-3">状态</th>
            <th class="text-center py-2 px-3">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in filteredSymbols" :key="s.id" class="border-b border-border-primary/50 hover:bg-dark-200/50">
              <td class="py-2 px-3 text-xs">{{ platformName(s.platform_id) }}</td>
              <td class="py-2 px-3 font-mono text-primary text-xs">{{ s.symbol }}</td>
              <td class="py-2 px-3 text-xs">{{ s.base_asset }}/{{ s.quote_asset }}</td>
              <td class="py-2 px-3 text-right font-mono text-xs">{{ s.contract_unit }} {{ s.qty_unit }}</td>
              <td class="py-2 px-3 text-right font-mono text-xs">{{ s.qty_precision }}位 步长{{ s.qty_step }}</td>
              <td class="py-2 px-3 text-right font-mono text-xs">{{ s.min_qty }}</td>
              <td class="py-2 px-3 text-right font-mono text-xs">{{ s.price_precision }}位</td>
              <td class="py-2 px-3 text-right font-mono text-xs">{{ (s.maker_fee_rate*100).toFixed(2) }}%/{{ (s.taker_fee_rate*100).toFixed(2) }}%</td>
              <td class="py-2 px-3 text-center"><span class="px-1.5 py-0.5 rounded text-xs" :class="s.product_type === 'perpetual' ? 'bg-blue-900/40 text-blue-300' : s.product_type === 'mt5' ? 'bg-purple-900/40 text-purple-300' : 'bg-gray-900/40 text-gray-300'">{{ {perpetual: '永续', mt5: 'MT5', spot: '现货'}[s.product_type] || s.product_type || '--' }}</span></td>
              <td class="py-2 px-3 text-right font-mono text-xs">{{ (s.margin_rate_initial*100).toFixed(1) }}%</td>
              <td class="py-2 px-3 text-center">
                <button @click="toggleSymbolActive(s)" :class="s.is_active ? 'text-success hover:text-red-400' : 'text-text-tertiary hover:text-success'" class="text-xs">{{ s.is_active ? '● 启用' : '○ 禁用' }}</button>
              </td>
              <td class="py-2 px-3 text-center">
                <button @click="editSymbol(s)" class="text-xs text-text-secondary hover:text-primary mr-2">编辑</button>
                <button @click="deleteSymbol(s)" class="text-xs text-red-400 hover:text-red-300">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ═══════ 平台列表 ═══════ -->
    <div v-if="activeTab === 'platforms'" class="space-y-3">
      <div class="flex justify-end mb-2">
        <button @click="createPlatform" class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 text-xs font-medium rounded-lg">+ 新增平台</button>
      </div>
      <div v-for="p in platforms" :key="p.platform_id"
        class="bg-dark-100 rounded-xl border border-border-primary p-4 flex items-center justify-between">
        <div class="flex-1 min-w-0">
          <div class="flex items-center flex-wrap gap-2">
            <span class="font-bold">{{ p.display_name || p.platform_name }}</span>
            <span class="px-2 py-0.5 rounded text-xs" :class="p.platform_type === 'cex' ? 'bg-blue-900/40 text-blue-300' : p.platform_type === 'mt5' ? 'bg-purple-900/40 text-purple-300' : 'bg-gray-900/40 text-gray-300'">{{ p.platform_type.toUpperCase() }}</span>
            <button @click="togglePlatformActive(p)" :class="p.is_active ? 'text-success hover:text-red-400' : 'text-text-tertiary hover:text-success'" class="text-xs cursor-pointer">{{ p.is_active ? '● 启用' : '○ 禁用' }}</button>
          </div>
          <div class="text-xs text-text-tertiary mt-1 space-x-4">
            <span>认证: {{ p.auth_type }}</span>
            <span>持仓模式: {{ p.position_mode }}</span>
            <span>Maker: {{ p.maker_mechanism }}</span>
            <span>币种: {{ p.base_currency }}</span>
            <span>代理: {{ p.requires_proxy ? '需要' : '不需要' }}</span>
          </div>
          <!-- MT5 系统服务客户端状态 -->
          <div v-if="p.platform_type === 'mt5'" class="mt-2 flex items-center gap-2">
            <span class="text-xs text-text-tertiary">MT5系统服务:</span>
            <template v-if="p.system_mt5_client">
              <span class="flex items-center gap-1">
                <span :class="p.system_mt5_client.connection_status === 'connected' ? 'bg-green-400' : 'bg-red-400'"
                  class="inline-block w-2 h-2 rounded-full"></span>
                <span class="text-xs font-semibold text-text-primary">{{ p.system_mt5_client.client_name }}</span>
              </span>
              <span class="text-xs text-text-tertiary font-mono">:{{ p.system_mt5_client.bridge_service_port }}</span>
              <span class="text-xs px-1.5 py-0.5 rounded"
                :class="p.system_mt5_client.connection_status === 'connected' ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
                {{ p.system_mt5_client.connection_status === 'connected' ? '在线' : (p.system_mt5_client.connection_status || '离线') }}
              </span>
            </template>
            <span v-else class="text-xs text-yellow-500 flex items-center gap-1">
              <span>⚠</span> 未配置系统服务客户端
            </span>
          </div>
        </div>
        <div class="flex gap-2 ml-4 flex-shrink-0">
          <button @click="editPlatform(p)" class="text-xs px-3 py-1 bg-dark-200 hover:bg-dark-50 rounded-lg">编辑</button>
          <button @click="deletePlatform(p)" class="text-xs px-3 py-1 bg-red-900/30 hover:bg-red-900/50 text-red-300 rounded-lg">删除</button>
        </div>
      </div>
    </div>

    <!-- ═══════ 编辑品种模态框 ═══════ -->
    <div v-if="editingSymbol" class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" @click.self="editingSymbol = null">
      <div class="bg-dark-100 rounded-xl border border-border-primary p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto">
        <h3 class="font-bold mb-4">{{ editingSymbol.id ? '编辑品种' : '新增品种' }}</h3>
        <div class="grid grid-cols-2 gap-3">
          <div><label class="text-xs text-text-tertiary">平台</label>
            <select v-model="editingSymbol.platform_id" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm">
              <option v-for="p in platforms" :key="p.platform_id" :value="p.platform_id">{{ p.display_name || p.platform_name }}</option>
            </select></div>
          <div><label class="text-xs text-text-tertiary">符号</label><input v-model="editingSymbol.symbol" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">基础资产</label><input v-model="editingSymbol.base_asset" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">计价币</label><input v-model="editingSymbol.quote_asset" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">合约面值</label><input v-model.number="editingSymbol.contract_unit" type="number" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">单位名称</label><input v-model="editingSymbol.qty_unit" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">数量精度</label><input v-model.number="editingSymbol.qty_precision" type="number" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">数量步长</label><input v-model.number="editingSymbol.qty_step" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">最小数量</label><input v-model.number="editingSymbol.min_qty" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">价格精度</label><input v-model.number="editingSymbol.price_precision" type="number" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">价格步长</label><input v-model.number="editingSymbol.price_step" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">Maker费率</label><input v-model.number="editingSymbol.maker_fee_rate" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">Taker费率</label><input v-model.number="editingSymbol.taker_fee_rate" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">初始保证金率</label><input v-model.number="editingSymbol.margin_rate_initial" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">产品类型</label>
            <select v-model="editingSymbol.product_type" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm">
              <option value="perpetual">永续合约</option>
              <option value="mt5">MT5</option>
              <option value="spot">现货</option>
            </select></div>
        </div>
        <div class="flex justify-end gap-2 mt-4">
          <button @click="editingSymbol = null" class="px-4 py-1.5 bg-dark-200 rounded-lg text-sm">取消</button>
          <button @click="saveSymbol" class="px-4 py-1.5 bg-primary text-dark-300 rounded-lg text-sm font-medium">保存</button>
        </div>
      </div>
    </div>

    <!-- ═══════ 编辑产品对模态框 ═══════ -->
    <div v-if="editingPair" class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" @click.self="editingPair = null">
      <div class="bg-dark-100 rounded-xl border border-border-primary p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto">
        <h3 class="font-bold mb-4">{{ editingPair.id ? '编辑对冲对' : '新增对冲对' }}</h3>
        <div class="grid grid-cols-2 gap-3">
          <div><label class="text-xs text-text-tertiary">名称</label><input v-model="editingPair.pair_name" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">编码</label><input v-model="editingPair.pair_code" :disabled="!!editingPair.id" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm disabled:opacity-50" /></div>
          <div><label class="text-xs text-text-tertiary">A侧品种</label>
            <select v-model="editingPair.symbol_a_id" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm">
              <option value="">请选择</option>
              <option v-for="s in symbols" :key="s.id" :value="s.id">{{ platformName(s.platform_id) }} - {{ s.symbol }}</option>
            </select></div>
          <div><label class="text-xs text-text-tertiary">B侧品种</label>
            <select v-model="editingPair.symbol_b_id" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm">
              <option value="">请选择</option>
              <option v-for="s in symbols" :key="s.id" :value="s.id">{{ platformName(s.platform_id) }} - {{ s.symbol }}</option>
            </select></div>
          <div><label class="text-xs text-text-tertiary">换算因子</label><input v-model.number="editingPair.conversion_factor" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">USD/USDT 汇率</label><input v-model.number="editingPair.usd_usdt_rate" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">点差模式</label>
            <select v-model="editingPair.spread_mode" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm">
              <option value="absolute">绝对值</option>
              <option value="percentage">百分比</option>
            </select></div>
          <div><label class="text-xs text-text-tertiary">点差精度</label><input v-model.number="editingPair.spread_precision" type="number" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">参考点差</label><input v-model.number="editingPair.default_spread_target" type="number" step="any" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">排序</label><input v-model.number="editingPair.sort_order" type="number" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div class="col-span-2 flex items-center gap-2">
            <label class="text-xs text-text-tertiary">启用</label>
            <button @click="editingPair.is_active = !editingPair.is_active" :class="editingPair.is_active ? 'bg-success' : 'bg-dark-300'" class="relative w-10 h-5 rounded-full transition-colors">
              <span :class="editingPair.is_active ? 'translate-x-5' : 'translate-x-0.5'" class="absolute top-0.5 left-0 w-4 h-4 bg-white rounded-full transition-transform"></span>
            </button>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-4">
          <button @click="editingPair = null" class="px-4 py-1.5 bg-dark-200 rounded-lg text-sm">取消</button>
          <button @click="savePair" class="px-4 py-1.5 bg-primary text-dark-300 rounded-lg text-sm font-medium">保存</button>
        </div>
      </div>
    </div>

    <!-- ═══════ 编辑平台模态框 ═══════ -->
    <div v-if="editingPlatform" class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" @click.self="editingPlatform = null">
      <div class="bg-dark-100 rounded-xl border border-border-primary p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto">
        <h3 class="font-bold mb-4">{{ editingPlatform._isNew ? '新增平台' : '编辑平台' }}</h3>
        <div class="grid grid-cols-2 gap-3">
          <div><label class="text-xs text-text-tertiary">平台ID</label><input v-model.number="editingPlatform.platform_id" type="number" :disabled="!editingPlatform._isNew" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm disabled:opacity-50" /></div>
          <div><label class="text-xs text-text-tertiary">平台名称</label><input v-model="editingPlatform.platform_name" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">显示名称</label><input v-model="editingPlatform.display_name" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">类型</label>
            <select v-model="editingPlatform.platform_type" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm">
              <option value="cex">CEX</option>
              <option value="mt5">MT5</option>
              <option value="dex">DEX</option>
            </select></div>
          <div class="col-span-2"><label class="text-xs text-text-tertiary">API Base URL</label><input v-model="editingPlatform.api_base_url" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div class="col-span-2"><label class="text-xs text-text-tertiary">WebSocket URL</label><input v-model="editingPlatform.ws_base_url" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div class="col-span-2">
            <label class="text-xs text-text-tertiary">MT5 模板目录</label>
            <input v-model="editingPlatform.mt5_template_path"
              class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm font-mono"
              placeholder="例如: D:\MetaTrader 5-template\terminal64.exe（仅 MT5 平台填写）" />
            <p class="text-xs text-text-tertiary mt-0.5">MT5 客户端部署时使用此模板路径作为运行目录，保留已配置的产品信息</p>
          </div>
          <!-- MT5 系统服务账号绑定（仅 MT5 类型平台显示） -->
          <div v-if="editingPlatform.platform_type === 'mt5'" class="col-span-2">
            <label class="text-xs text-text-tertiary">MT5 系统服务账号</label>
            <select v-model="editingPlatform._system_mt5_account_id"
              class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm mt-0.5">
              <option value="">-- 不绑定 --</option>
              <option v-for="acc in systemMt5Accounts" :key="acc.account_id" :value="acc.account_id">
                {{ acc.account_name }} ({{ acc.platform_name }}) — {{ acc.mt5_client_name || '未部署Bridge' }}
              </option>
            </select>
            <p class="text-xs text-text-tertiary mt-0.5">选择已设为系统服务的 MT5 账户作为此平台的行情数据源（Bybit→MT5 BYSYS，IC Markets→MT5 ICSYS）</p>
          </div>
          <div><label class="text-xs text-text-tertiary">认证方式</label><input v-model="editingPlatform.auth_type" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">持仓模式</label><input v-model="editingPlatform.position_mode" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">Maker机制</label><input v-model="editingPlatform.maker_mechanism" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div><label class="text-xs text-text-tertiary">基础币种</label><input v-model="editingPlatform.base_currency" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-sm" /></div>
          <div class="flex items-center gap-2">
            <label class="text-xs text-text-tertiary">需要代理</label>
            <button @click="editingPlatform.requires_proxy = !editingPlatform.requires_proxy" :class="editingPlatform.requires_proxy ? 'bg-success' : 'bg-dark-300'" class="relative w-10 h-5 rounded-full transition-colors">
              <span :class="editingPlatform.requires_proxy ? 'translate-x-5' : 'translate-x-0.5'" class="absolute top-0.5 left-0 w-4 h-4 bg-white rounded-full transition-transform"></span>
            </button>
          </div>
          <div class="flex items-center gap-2">
            <label class="text-xs text-text-tertiary">启用</label>
            <button @click="editingPlatform.is_active = !editingPlatform.is_active" :class="editingPlatform.is_active ? 'bg-success' : 'bg-dark-300'" class="relative w-10 h-5 rounded-full transition-colors">
              <span :class="editingPlatform.is_active ? 'translate-x-5' : 'translate-x-0.5'" class="absolute top-0.5 left-0 w-4 h-4 bg-white rounded-full transition-transform"></span>
            </button>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-4">
          <button @click="editingPlatform = null" class="px-4 py-1.5 bg-dark-200 rounded-lg text-sm">取消</button>
          <button @click="savePlatform" class="px-4 py-1.5 bg-primary text-dark-300 rounded-lg text-sm font-medium">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api.js'

const activeTab = ref('pairs')
const tabs = [
  { key: 'pairs', label: '对冲产品对' },
  { key: 'symbols', label: '平台品种配置' },
  { key: 'platforms', label: '平台列表' },
]

const platforms = ref([])
const symbols = ref([])
const pairs = ref([])
const symbolFilter = ref(null)
const editingSymbol = ref(null)
const editingPair = ref(null)
const editingPlatform = ref(null)
// systemMt5Accounts: 所有已设为系统服务的 MT5 账户（编辑平台时显示）
const systemMt5Accounts = ref([])

const filteredSymbols = computed(() =>
  symbolFilter.value ? symbols.value.filter(s => s.platform_id === symbolFilter.value) : symbols.value
)

function platformName(pid) {
  const p = platforms.value.find(x => x.platform_id === pid)
  return p ? (p.display_name || p.platform_name) : pid
}

function toast(msg, type = 'success') {
  const el = document.createElement('div')
  el.className = `fixed top-4 right-4 z-[9999] px-4 py-2 rounded-lg text-sm ${type === 'error' ? 'bg-red-900/90 text-red-200' : 'bg-green-900/90 text-green-200'}`
  el.textContent = msg
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 3000)
}

async function loadAll() {
  try {
    const [pRes, sRes, prRes] = await Promise.all([
      api.get('/api/v1/hedging/pairs'),
      api.get('/api/v1/hedging/symbols'),
      api.get('/api/v1/hedging/platforms'),
    ])
    pairs.value = pRes.data || []
    symbols.value = sRes.data || []
    platforms.value = prRes.data || []
  } catch (e) {
    toast('加载失败: ' + (e.response?.data?.detail || e.message), 'error')
  }
}

async function loadSystemMt5Accounts() {
  // Load all accounts that have an active system-service MT5 client
  // Used by the platform edit modal to let admin bind a system MT5 account to a platform
  try {
    const r = await api.get('/api/v1/accounts', { params: { all: 'true' } })
    const allAccounts = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    // Get all system-service MT5 client info
    const mc = await api.get('/api/v1/mt5-clients/all')
    const sysClients = (Array.isArray(mc.data) ? mc.data : [])
      .filter(c => c.is_system_service)
    const sysAccountIds = new Set(sysClients.map(c => c.account_id))
    // Match accounts that have system service MT5 clients
    const result = []
    for (const acc of allAccounts) {
      if (sysAccountIds.has(acc.account_id)) {
        const client = sysClients.find(c => c.account_id === acc.account_id)
        const plat = platforms.value.find(p => p.platform_id === acc.platform_id)
        result.push({
          account_id: acc.account_id,
          account_name: acc.account_name,
          platform_id: acc.platform_id,
          platform_name: plat?.display_name || plat?.platform_name || acc.platform_id,
          mt5_client_name: client?.client_name || null,
          bridge_url: client?.bridge_url || null,
          bridge_port: client?.bridge_service_port || null,
          connection_status: client?.connection_status || null,
        })
      }
    }
    systemMt5Accounts.value = result
  } catch (e) {
    console.warn('Failed to load system MT5 accounts:', e)
  }
}

// ── Symbol CRUD ──────────────────────────────────────────────────
function editSymbol(s) {
  editingSymbol.value = { ...s }
}

async function saveSymbol() {
  try {
    const s = editingSymbol.value
    if (s.id) {
      await api.put(`/api/v1/hedging/symbols/${s.id}`, s)
      toast('品种已更新')
    } else {
      await api.post('/api/v1/hedging/symbols', s)
      toast('品种已创建')
    }
    editingSymbol.value = null
    await loadAll()
  } catch (e) {
    toast('保存失败: ' + (e.response?.data?.detail || e.message), 'error')
  }
}

async function deleteSymbol(s) {
  if (!confirm(`确认删除品种 ${s.symbol}？`)) return
  try {
    await api.delete(`/api/v1/hedging/symbols/${s.id}`)
    toast('品种已删除')
    await loadAll()
  } catch (e) { toast('删除失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

async function toggleSymbolActive(s) {
  try {
    await api.put(`/api/v1/hedging/symbols/${s.id}`, { is_active: !s.is_active })
    toast(s.is_active ? '品种已禁用' : '品种已启用')
    await loadAll()
  } catch (e) { toast('操作失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

// ── Pair CRUD ────────────────────────────────────────────────────
function createPair() {
  editingPair.value = {
    pair_name: '', pair_code: '', symbol_a_id: '', symbol_b_id: '',
    conversion_factor: 100, usd_usdt_rate: 1.0, spread_mode: 'absolute',
    spread_precision: 2, default_spread_target: null, sort_order: 0, is_active: true,
  }
}

function editPair(p) {
  editingPair.value = { ...p, symbol_a_id: p.symbol_a_id || '', symbol_b_id: p.symbol_b_id || '' }
}

async function savePair() {
  try {
    const p = editingPair.value
    if (p.id) {
      await api.put(`/api/v1/hedging/pairs/${p.id}`, p)
      toast('对冲对已更新')
    } else {
      await api.post('/api/v1/hedging/pairs', p)
      toast('对冲对已创建')
    }
    editingPair.value = null
    await loadAll()
  } catch (e) {
    toast('保存失败: ' + (e.response?.data?.detail || e.message), 'error')
  }
}

async function deletePair(p) {
  if (!confirm(`确认删除对冲对「${p.pair_name}」？`)) return
  try {
    await api.delete(`/api/v1/hedging/pairs/${p.id}`)
    toast('对冲对已删除')
    await loadAll()
  } catch (e) { toast('删除失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

async function togglePairActive(p) {
  try {
    await api.put(`/api/v1/hedging/pairs/${p.id}`, { is_active: !p.is_active })
    toast(p.is_active ? '对冲对已禁用' : '对冲对已启用')
    await loadAll()
  } catch (e) { toast('操作失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

// ── Platform CRUD ────────────────────────────────────────────────
function createPlatform() {
  loadSystemMt5Accounts()
  editingPlatform.value = {
    _isNew: true, platform_id: '', platform_name: '', display_name: '',
    platform_type: 'cex', api_base_url: '', ws_base_url: '', mt5_template_path: '',
    auth_type: 'hmac_sha256', position_mode: 'hedging', maker_mechanism: 'none',
    base_currency: 'USDT', requires_proxy: false, is_active: true,
    _system_mt5_account_id: '',
  }
}

function editPlatform(p) {
  loadSystemMt5Accounts()
  // Find current system MT5 account for this platform (if any)
  const current = p.system_mt5_client ? p.system_mt5_client.account_id : ''
  editingPlatform.value = { ...p, _isNew: false, _system_mt5_account_id: current }
}

async function savePlatform() {
  try {
    const p = { ...editingPlatform.value }
    const isNew = p._isNew
    delete p._isNew
    delete p._system_mt5_account_id  // not a platform field — handled separately via mt5_clients
    delete p.system_mt5_client        // API response field, not writable
    if (isNew) {
      await api.post('/api/v1/hedging/platforms', p)
      toast('平台已创建')
    } else {
      await api.put(`/api/v1/hedging/platforms/${p.platform_id}`, p)
      toast('平台已更新')
    }
    editingPlatform.value = null
    await loadAll()
  } catch (e) {
    toast('保存失败: ' + (e.response?.data?.detail || e.message), 'error')
  }
}

async function deletePlatform(p) {
  if (!confirm(`确认删除平台「${p.display_name || p.platform_name}」？`)) return
  try {
    await api.delete(`/api/v1/hedging/platforms/${p.platform_id}`)
    toast('平台已删除')
    await loadAll()
  } catch (e) { toast('删除失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

async function togglePlatformActive(p) {
  try {
    await api.put(`/api/v1/hedging/platforms/${p.platform_id}`, { is_active: !p.is_active })
    toast(p.is_active ? '平台已禁用' : '平台已启用')
    await loadAll()
  } catch (e) { toast('操作失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

onMounted(async () => {
  await loadAll()
  loadSystemMt5Accounts()
})
</script>
