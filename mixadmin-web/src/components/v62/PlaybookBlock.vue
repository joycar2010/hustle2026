<template>
  <!-- V6.2 R3 套利原理三层(§6):白话常显,专业层折叠;当前实例数字由抽屉其它段承担,本块只讲机制。 -->
  <div v-if="pb" class="pbk">
    <i class="hd">套利原理 · {{ pb.name }} <span class="ver">{{ pb.version }}</span></i>
    <p class="plain">{{ pb.plain }}</p>
    <div class="tri">
      <p><b class="up">钱从哪赚</b>{{ pb.earn_from }}</p>
      <p><b class="dn">最容易哪亏</b>{{ pb.lose_from }}</p>
      <p><b>什么时候退</b>{{ pb.exit_rule }}</p>
    </div>
    <div class="pro" @click="proOpen = !proOpen">专业层(公式与机制){{ proOpen ? '▲' : '▼' }}</div>
    <p v-if="proOpen" class="prob">{{ pb.pro }}</p>
    <p class="disc">{{ pb.disclaimer }}</p>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { mixApi } from '../../api/mix'

const props = defineProps({ code: { type: String, default: '' } })
const pb = ref(null)
const proOpen = ref(false)
const cache = (window.__mixPbCache = window.__mixPbCache || {})

async function load (code) {
  pb.value = null; proOpen.value = false
  if (!code) return
  // phase 码归并到产品 playbook:C3.S.V6→C3.S 等
  const key = code.replace(/\.V6$/, '')
  if (cache[key] !== undefined) { pb.value = cache[key]; return }
  try {
    cache[key] = await mixApi.playbook(key)
    pb.value = cache[key]
  } catch (e) {
    cache[key] = null // 404=该码无 playbook,静默不占位;不编内容
  }
}
watch(() => props.code, load, { immediate: true })
</script>

<style scoped>
.pbk{margin-top:8px;padding:8px 10px;background:#181A20;border:1px solid #2B3139;border-radius:4px;font-size:12px;color:#B7BDC6}
.hd{color:#848E9C;font-style:normal;display:block;margin-bottom:4px}
.ver{color:#5E6673;font-size:11px;margin-left:6px}
.plain{color:#EAECEF;margin:0 0 6px;line-height:1.6}
.tri p{margin:2px 0;line-height:1.55}
.tri b{display:inline-block;min-width:74px;color:#EAECEF;font-weight:600;margin-right:4px}
.tri b.up{color:#0ECB81}.tri b.dn{color:#F6465D}
.pro{color:#F0B90B;cursor:pointer;margin-top:5px;font-size:11px}
.prob{color:#848E9C;margin:4px 0 0;line-height:1.55}
.disc{color:#5E6673;margin:6px 0 0;font-size:11px}
</style>
