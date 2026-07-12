<template>
  <div class="mixsite">
    <div class="card">
      <div class="chd"><b>官网/品牌管理</b><span class="sub">mixadmin 侧栏与登录门实时消费；保存即热生效（刷新页面可见）</span></div>
      <el-form label-width="110px" size="small">
        <el-form-item label="侧栏标题"><el-input v-model="b.title" placeholder="HustleCoin Mix" /></el-form-item>
        <el-form-item label="登录门大字"><el-input v-model="b.loginTitle" placeholder="HUSTLECOIN MIX" /></el-form-item>
        <el-form-item label="标语"><el-input v-model="b.slogan" placeholder="把复杂的事，交给系统；把结果，交给你" /></el-form-item>
        <el-form-item label="LOGO URL"><el-input v-model="b.logo" placeholder="/logo-white.png（默认画板金柱版）" /></el-form-item>
        <el-form-item label="浏览器标题"><el-input v-model="b.docTitle" placeholder="HustleCoin Mix 管理后台" /></el-form-item>
      </el-form>
      <el-button type="warning" @click="save">保存（需 SUPER_ADMIN）</el-button>
    </div>
    <div class="card">
      <div class="chd"><b>两站资产索引（只读）</b></div>
      <div class="kv"><span>管理端</span><b>mixadmin.hustle2026.xyz · /logo-white.png · /favicon.png · manifest</b></div>
      <div class="kv"><span>用户端</span><b>mix.hustle2026.xyz · /logo.png · /favicon.png</b></div>
      <div class="fnote">LOGO 源=Pencil 画板矢量导出（mix-assets/）；更换资产走发布流程（构建→原子切换→公网 md5）。</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'
const b = ref({})
async function load() { try { b.value = await mixApi.siteBrand() } catch (e) { /* 降级 */ } }
async function save() {
  try {
    await mixApi.siteBrandPut(b.value)
    ElMessage.success('已保存并热生效')
    window.dispatchEvent(new CustomEvent('qha-brand-updated', { detail: b.value }))
  } catch (e) { ElMessage.error(e?.detail || '失败（需 SUPER_ADMIN）') }
}
onMounted(load)
</script>

<style scoped lang="scss">
.mixsite { display: flex; flex-direction: column; gap: 12px; max-width: 720px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 14px 16px; }
.chd { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px;
  b { font-size: 13px; } .sub { font-size: 10.5px; color: var(--mix-t3, #5E6673); } }
.kv { display: flex; gap: 12px; font-size: 12px; color: var(--mix-t2, #848E9C); padding: 3px 0; b { color: var(--mix-t1, #EAECEF); font-weight: 500; } }
.fnote { font-size: 10.5px; color: var(--mix-t3, #5E6673); margin-top: 6px; }
</style>
