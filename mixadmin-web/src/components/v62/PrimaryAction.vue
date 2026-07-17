<template>
  <!-- V6.2 PrimaryAction(帧 u9Uw0 五态):可用/禁用/加载/需认证/执行失败。
       禁用=三行式(暂不能X/原因/仍可做),still_allowed 直读契约字段,前端不猜。 -->
  <el-popover v-if="!a.wired" placement="top" width="300" trigger="hover" :teleported="false">
    <template #reference>
      <button class="pa dis" :class="sz" @click.stop>{{ a.label }}</button>
    </template>
    <div class="pa-tip">
      <b>暂不能:{{ a.label }}</b>
      <p>原因:{{ a.reason || blockingReason || '当前状态不允许' }}</p>
      <p v-if="stillAllowed?.length">仍可:{{ stillAllowed.join('、') }}</p>
    </div>
  </el-popover>
  <button v-else-if="state==='loading'" class="pa loading" :class="sz" disabled>
    <span class="spin"><FIcon name="clock" :size="11"/></span>{{ loadingText || '提交中…' }}
  </button>
  <button v-else-if="state==='failed'" class="pa fail" :class="sz" @click.stop="$emit('run', a)">
    重试·{{ a.label }}
  </button>
  <button v-else class="pa" :class="[sz, {gold: a.kind==='primary', red: a.kind==='danger', auth: needAuth}]"
          @click.stop="$emit('run', a)">
    <FIcon v-if="needAuth" name="lock" :size="11"/>{{ a.label }}
  </button>
</template>
<script setup>
defineProps({
  a: { type: Object, required: true },        // allowed_actions 条目 {code,label,kind,wired,reason}
  state: { type: String, default: '' },        // ''|loading|failed(提交三态)
  loadingText: String,
  needAuth: Boolean,                           // 需二次认证(Passkey/TOTP)
  blockingReason: String,                      // 行级 blocking_reason 兜底
  stillAllowed: Array,                         // 契约字段 still_allowed
  sz: { type: String, default: '' },           // ''|sm
})
defineEmits(['run'])
</script>
<style scoped>
.pa{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:700;padding:4px 12px;
  border-radius:5px;cursor:pointer;background:var(--mix-card2,#20242C);color:var(--mix-t1,#EAECEF);
  border:1px solid var(--mix-border,#2B3139);white-space:nowrap;transition:border-color .12s}
.pa.sm{font-size:9.5px;padding:2px 8px}
.pa:hover{border-color:#F0B90B;color:#F0B90B}
.pa.gold{background:#F0B90B1F;border-color:#F0B90B4D;color:#F0B90B}
.pa.red{background:#F6465D14;border-color:#F6465D66;color:#F6465D}
.pa.red:hover{border-color:#F6465D}
.pa.auth{background:#4A9CFF14;border-color:#4A9CFF66;color:#4A9CFF}
.pa.dis{opacity:.45;cursor:not-allowed}
.pa.dis:hover{border-color:var(--mix-border,#2B3139);color:var(--mix-t1,#EAECEF)}
.pa.loading{background:#F0B90B0D;border-color:#F0B90B4D;color:#F0B90B;cursor:wait}
.pa.fail{background:#F6465D14;border-color:#F6465D66;color:#F6465D}
.spin{display:inline-block;animation:sp 1s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.pa-tip b{font-size:11.5px;color:var(--mix-t1,#EAECEF)}
.pa-tip p{font-size:10.5px;color:var(--mix-t2,#848E9C);margin:4px 0 0;line-height:1.5}
</style>
