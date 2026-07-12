<template>
  <div class="mixllm">
    <div class="card">
      <div class="chd"><b>LLM 评审层（dcm llm-advisor）</b>
        <el-tag size="small" :type="d.status==='ok'?'success':'info'" effect="dark">{{ d.status }}</el-tag>
      </div>
      <div class="kv"><span>模型</span><b>{{ d.model || '—' }}</b></div>
      <div class="kv"><span>最近一轮延迟</span><b>{{ d.latency_ms ? d.latency_ms + ' ms' : '—' }}</b></div>
      <div class="kv"><span>快照时间</span><b>{{ ts }}</b></div>
      <div class="kv" v-if="d.usage"><span>tokens（prompt/completion）</span>
        <b>{{ d.usage.prompt_tokens }} / {{ d.usage.completion_tokens }}</b></div>
      <div class="fnote">{{ d.note }}</div>
    </div>
    <div class="card">
      <div class="chd"><b>最近评审意见（commentary）</b></div>
      <pre class="cmt">{{ d.commentary || '（暂无）' }}</pre>
    </div>
    <div class="card">
      <div class="chd"><b>治理链路（只读声明）</b></div>
      <div class="fnote">读总线全景 → LLM → schema 硬校验（action 越界丢弃/坏响应整轮弃用）→ 只写建议键 dcm:advisor:llm。
        永不能下单；摘除=只持有不新增。模型/Key 变更：C 机 dcm-llm-advisor EnvironmentFile 修改后重启。</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { mixApi } from '../../api/mix'
const d = ref({})
const ts = computed(() => d.value.ts ? new Date(d.value.ts * 1000).toLocaleString() : '—')
let t
async function load() { try { d.value = await mixApi.system.llm() } catch (e) { /* 降级 */ } }
onMounted(() => { load(); t = setInterval(load, 30000) })
onUnmounted(() => clearInterval(t))
</script>

<style scoped lang="scss">
.mixllm { display: flex; flex-direction: column; gap: 12px; max-width: 900px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 12px 14px; }
.chd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; b { font-size: 13px; } }
.kv { display: flex; justify-content: space-between; font-size: 12px; color: var(--mix-t2, #848E9C); padding: 2px 0; b { color: var(--mix-t1, #EAECEF); } }
.fnote { font-size: 11px; color: var(--mix-t3, #5E6673); line-height: 1.6; }
.cmt { font-size: 12px; color: var(--mix-t1, #EAECEF); white-space: pre-wrap; max-height: 320px; overflow: auto; margin: 0; }
</style>
