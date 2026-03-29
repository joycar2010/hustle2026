#!/usr/bin/env python3
"""
修改StrategyPanel.vue的UI部分，将触发频率分为开仓和平仓两个独立的输入框
"""

import re
import os

# 获取脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
# 构建文件路径
file_path = os.path.join(script_dir, 'StrategyPanel.vue')

print(f"File path: {file_path}")
print(f"File exists: {os.path.exists(file_path)}")

# 读取文件
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 定义要替换的旧代码（第268-316行）
old_code = '''        <!-- Data Sync Quantities -->
        <div class="grid grid-cols-3 gap-2">
          <div>
            <label :for="`openingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正开次数' : '反开次数' }}
            </label>
            <input
              :id="`openingSyncQty-${type}`"
              v-model.number="config.openingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`closingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正平次数' : '反平次数' }}
            </label>
            <input
              :id="`closingSyncQty-${type}`"
              v-model.number="config.closingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`triggerCheckInterval-${type}`" class="text-xs text-gray-400 mb-1 block">
              触发频率
              <span class="text-[#0ecb81] ml-1">{{ config.triggerCheckInterval }}ms</span>
            </label>
            <input
              :id="`triggerCheckInterval-${type}`"
              v-model.number="config.triggerCheckInterval"
              type="number"
              step="100"
              min="500"
              max="1000"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
            <div class="text-xs text-gray-500 mt-0.5">
              建议值: 500ms
            </div>
          </div>
        </div>'''

# 定义新代码
new_code = '''        <!-- Data Sync Quantities and Trigger Intervals -->
        <div class="space-y-2">
          <!-- Opening Configuration -->
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label :for="`openingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
                {{ type === 'forward' ? '正开次数' : '反开次数' }}
              </label>
              <input
                :id="`openingSyncQty-${type}`"
                v-model.number="config.openingSyncQty"
                type="number"
                step="1"
                min="1"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>

            <div>
              <label :for="`openingTriggerCheckInterval-${type}`" class="text-xs text-gray-400 mb-1 block">
                开仓触发频率
                <span class="text-[#0ecb81] ml-1">{{ config.openingTriggerCheckInterval }}ms</span>
              </label>
              <input
                :id="`openingTriggerCheckInterval-${type}`"
                v-model.number="config.openingTriggerCheckInterval"
                type="number"
                step="100"
                min="500"
                max="1000"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>
          </div>

          <!-- Closing Configuration -->
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label :for="`closingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
                {{ type === 'forward' ? '正平次数' : '反平次数' }}
              </label>
              <input
                :id="`closingSyncQty-${type}`"
                v-model.number="config.closingSyncQty"
                type="number"
                step="1"
                min="1"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>

            <div>
              <label :for="`closingTriggerCheckInterval-${type}`" class="text-xs text-gray-400 mb-1 block">
                平仓触发频率
                <span class="text-[#f6465d] ml-1">{{ config.closingTriggerCheckInterval }}ms</span>
              </label>
              <input
                :id="`closingTriggerCheckInterval-${type}`"
                v-model.number="config.closingTriggerCheckInterval"
                type="number"
                step="100"
                min="500"
                max="1000"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>
          </div>

          <div class="text-xs text-gray-500 text-center">
            建议值: 500ms
          </div>
        </div>'''

# 替换
if old_code in content:
    content = content.replace(old_code, new_code)
    print("[OK] UI section replaced successfully")
else:
    print("[ERROR] Code to replace not found")
    exit(1)

# 写回文件
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("[OK] File modification completed")
