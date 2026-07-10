<template>
  <div>
    <el-alert v-if="a.status === 'unconfigured'" type="info" :closable="false" style="margin-bottom:12px"
      title="LLM 顾问未配置" description="llm-advisor 服务已上线但未填 API Key,当前为降级态(不调用大模型)。填 DCM_LLM_KEY 并重启服务即武装。" />
    <el-alert v-else-if="a.status === 'missing'" type="warning" :closable="false" style="margin-bottom:12px"
      :title="a.note || 'llm-advisor 未产出'" />
    <el-alert v-else-if="a.status === 'bad_round'" type="warning" :closable="false" style="margin-bottom:12px"
      title="上一轮 LLM 输出未过校验(展示的是更早的有效结果)" />

    <div class="card">
      <h3>LLM 市场评审
        <el-tag v-if="a.model" size="small" style="margin-left:8px">{{ a.model }}</el-tag>
        <span class="dim" style="font-size:12px;margin-left:8px">{{ age }}</span>
        <span class="dim" style="font-size:12px;margin-left:8px" v-if="a.usage && a.usage.total_tokens">{{ a.usage.total_tokens }} tokens · {{ a.latency_ms }}ms</span>
      </h3>
      <div v-if="a.commentary" style="line-height:1.7;color:#c9d1d9">{{ a.commentary }}</div>
      <div v-else class="dim">暂无评审(顾问未产出或未配置)</div>
    </div>

    <div class="card"><h3>建议(仅供参考 · 顾问无下单权)</h3>
      <el-table :data="a.recommendations || []" size="small" empty-text="暂无建议">
        <el-table-column prop="symbol" label="币" width="110" />
        <el-table-column label="判断" width="90">
          <template #default="s"><el-tag size="small" :type="tagType(s.row.action)">{{ actionCn(s.row.action) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="信心" width="90">
          <template #default="s"><span :class="s.row.confidence >= 0.6 ? 'pos' : (s.row.confidence < 0.4 ? 'neg' : '')">{{ (s.row.confidence * 100).toFixed(0) }}%</span></template>
        </el-table-column>
        <el-table-column prop="reason" label="理由" />
        <el-table-column label="风险标注" width="220">
          <template #default="s"><el-tag v-for="f in s.row.risk_flags" :key="f" size="small" type="info" style="margin:1px">{{ f }}</el-tag></template>
        </el-table-column>
      </el-table>
    </div>
    <div class="dim" style="font-size:12px;margin-top:8px">
      LLM 顾问是只读评审层——不写路由、不下单、不改任何配置。建议仅供人类操作员参考,采纳与否由规则引擎与人工决定。
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
const a = ref({}); let timer
const age = computed(() => {
  if (!a.value.ts) return ''
  const s = Math.floor(Date.now() / 1000 - a.value.ts)
  return s < 90 ? `${s}s 前` : `${Math.floor(s / 60)}min 前`
})
function actionCn(x) { return { endorse: '看好', caution: '谨慎', avoid: '避开', watch: '观察' }[x] || x }
function tagType(x) { return { endorse: 'success', caution: 'warning', avoid: 'danger', watch: 'info' }[x] || 'info' }
async function load() { try { a.value = await api.advisorLlm() } catch (e) {} }
onMounted(() => { load(); timer = setInterval(load, 30000) })
onUnmounted(() => clearInterval(timer))
</script>
