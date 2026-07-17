<template>
  <!-- V6.2 EmptyState(帧 u9Uw0 四态):空态必须回答『下一步做什么』 -->
  <div class="es">
    <span class="ei"><FIcon :name="ICON[kind]" :size="22" :sw="1.6"/></span>
    <b>{{ title || T[kind] }}</b>
    <p v-if="hint || H[kind]">{{ hint || H[kind] }}</p>
  </div>
</template>
<script setup>
defineProps({
  kind: { type: String, default: 'none' },   // none|not_connected|waiting|no_perm
  title: String, hint: String,
})
const ICON = { none: 'check', not_connected: 'block', waiting: 'clock', no_perm: 'lock' }
const T = { none: '无待办', not_connected: '该数据源未接入', waiting: '等待数据…', no_perm: '当前角色不可见' }
const H = { none: '系统自动运行中', not_connected: '不显示假数据·接入排期见系统状态',
            waiting: '数据产生后自动出现', no_perm: '权限由服务端校验' }
</script>
<style scoped>
.es{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:28px 16px}
.ei{font-size:22px;color:var(--mix-t3,#5E6673)}
.es b{font-size:12.5px;color:var(--mix-t2,#848E9C)}
.es p{font-size:10.5px;color:var(--mix-t3,#5E6673);margin:0;text-align:center;line-height:1.5}
</style>
