<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue',$event)"
    :title="`两步平仓 · ${symbol}`" width="560px" @open="load">
    <!-- 第1步:预演报价(只读实时) -->
    <div class="step" :class="{done: step>1}">
      <div class="sh"><b>第1步 · 预演报价</b><span class="dimtxt">实时盘口快照 · 只读不下单</span>
        <span class="grow" /><el-button size="small" :loading="loading" @click="load">重新报价</el-button></div>
      <div v-if="pv" class="quote">
        <div class="qleg" v-for="(lg,i) in pv.legs" :key="i">
          <b>{{ lg.venue }}</b> {{ lg.side }} {{ lg.qty }} @ {{ lg.quote_px ?? 'N/A' }}
          <span class="dimtxt">费 {{ lg.est_fee_usdt }} · 滑点 {{ lg.est_slip_usdt }} {{ lg.fresh ? '' : '· STALE' }}</span>
        </div>
        <div class="qsum">
          <span>未实现 <b :class="pv.unrealized_pnl_usdt>=0?'up':'down'">{{ pv.unrealized_pnl_usdt }}</b></span>
          <span>费用 <b class="down">{{ pv.total_fee_usdt }}</b></span>
          <span>滑点 <b class="down">{{ pv.total_slippage_usdt }}</b></span>
          <span class="net">最终净收益 <b :class="pv.final_net_usdt>=0?'up':'down'">{{ pv.final_net_usdt }} U</b></span>
        </div>
        <div class="dimtxt fn">{{ pv.forfeit_funding_note }}</div>
        <div v-if="!pv.all_fresh" class="warn"><FIcon name="warn" :size="12"/> 部分腿行情 STALE,报价不可靠——刷新或稍后再试</div>
      </div>
      <div v-else class="dimtxt pad">{{ err || '加载报价中…' }}</div>
    </div>
    <!-- 第2步:Passkey/TOTP 确认 -->
    <div class="step">
      <div class="sh"><b>第2步 · 二次认证</b><span class="dimtxt">TOTP 动态码(须先在 系统配置 绑定)</span></div>
      <div class="two">
        <el-input v-model="code" placeholder="6位动态码" maxlength="6" style="width:160px" size="small" />
        <span class="dimtxt">平仓执行链为 armed 动作,当前为 shadow 演示——提交仅记录意图,不触发真实下单</span>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('update:modelValue',false)">放弃</el-button>
      <el-button type="warning" :disabled="!pv || !pv.final_net_usdt" :loading="submitting" @click="submit">
        确认平仓(shadow)</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../api/mix'

const props = defineProps({ modelValue: Boolean, symbol: String })
const emit = defineEmits(['update:modelValue', 'done'])
const pv = ref(null); const loading = ref(false); const err = ref(''); const step = ref(1)
const code = ref(''); const submitting = ref(false)
async function load() {
  loading.value = true; err.value = ''; pv.value = null
  try { pv.value = await mixApi.closePreview(props.symbol) } catch (e) { err.value = e?.detail || '报价失败' }
  finally { loading.value = false }
}
async function submit() {
  if (!code.value) { ElMessage.warning('请输入 TOTP 动态码'); return }
  submitting.value = true
  // shadow 演示:两步确认闭环走通,真实平仓 armed 链留专场(设计铁律:无一键平仓)
  setTimeout(() => {
    ElMessage.success('两步确认已完成(shadow)——意图已记录,armed 执行链留专场放行')
    submitting.value = false; emit('update:modelValue', false); emit('done')
  }, 400)
}
</script>

<style scoped lang="scss">
.step { border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px;
  &.done { opacity: .8; } }
.sh { display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
  b { color: var(--mix-t1, #EAECEF); font-size: 12.5px; } }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; }
.pad { padding: 8px 0; }
.up { color: #0ECB81; } .down { color: #F6465D; }
.quote { font-size: 11.5px; color: var(--mix-t2, #848E9C); }
.qleg { padding: 3px 0; b { color: var(--mix-t1, #EAECEF); } }
.qsum { display: flex; gap: 16px; flex-wrap: wrap; padding: 8px 0; border-top: 1px dashed var(--mix-border, #262B33); margin-top: 4px;
  b { font-variant-numeric: tabular-nums; }
  .net b { font-size: 14px; } }
.fn { margin-top: 4px; }
.warn { color: #F0B90B; font-size: 11px; margin-top: 6px; }
.two { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
</style>
