<template>
  <div class="mixnotify">
    <div class="card">
      <div class="hd"><b>通知设置</b><span class="sub">全局统一：策略只声明事件与级别，间隔/次数/冷却/节流在此配置（已从各策略模板迁出）</span></div>
      <el-form label-width="130" style="max-width:560px">
        <el-form-item label="通知渠道">
          <el-checkbox-group v-model="cfg.channels">
            <el-checkbox value="feishu">飞书</el-checkbox>
            <el-checkbox value="marquee">跑马灯</el-checkbox>
            <el-checkbox value="modal">大红弹框（强平级）</el-checkbox>
            <el-checkbox value="email">邮件</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="提醒间隔 (秒)"><el-input-number v-model="cfg.intervalSec" :min="30" :step="30" /></el-form-item>
        <el-form-item label="每小时上限 (次)"><el-input-number v-model="cfg.maxPerHour" :min="1" :max="60" /></el-form-item>
        <el-form-item label="冷却时间 (秒)"><el-input-number v-model="cfg.cooldownSec" :min="0" :step="60" /></el-form-item>
        <el-form-item label="令牌桶节流">
          <div class="tb">
            <span>速率</span><el-input-number v-model="cfg.tokenBucket.rate" :min="0.1" :step="0.5" :precision="1" size="small" />
            <span>突发</span><el-input-number v-model="cfg.tokenBucket.burst" :min="1" :max="10" size="small" />
            <em>（rate 条/秒 · burst 突发容量；FATAL 级别不受节流）</em>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="warning" :loading="saving" @click="save">保存</el-button>
          <el-button @click="load">还原</el-button>
        </el-form-item>
      </el-form>
    </div>
    <div class="card note">
      <b>分级策略</b>
      <p>FATAL（强平/裸空/借币服务异常）：绕过节流，飞书 + 大红弹框即时；WARN：受令牌桶节流，飞书 + 跑马灯；INFO：仅跑马灯 + 告警时间线落库。</p>
      <p>告警条目统一带策略徽章（S1–S6），路由按事件源 strategy_code 自动归属。</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

const base = import.meta.env.VITE_MIX_API || 'http://localhost:8100/api/v1'
const cfg = ref({ channels: [], intervalSec: 300, maxPerHour: 6, cooldownSec: 600, tokenBucket: { rate: 1, burst: 3 } })
const saving = ref(false)

async function load() { cfg.value = await fetch(`${base}/settings/notifications`).then(r => r.json()) }
async function save() {
  saving.value = true
  try {
    await fetch(`${base}/settings/notifications`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(cfg.value) })
    ElMessage.success('通知设置已保存（全局生效）')
  } finally { saving.value = false }
}
onMounted(load)
</script>

<style scoped lang="scss">
.mixnotify { display: flex; flex-direction: column; gap: 12px; max-width: 760px; }
.card { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 14px 16px;
  .hd { display: flex; gap: 10px; align-items: baseline; margin-bottom: 12px; b { font-size: 13px; } .sub { color: var(--el-text-color-secondary); font-size: 11px; } }
  &.note { font-size: 12px; color: var(--el-text-color-regular); p { margin: 6px 0 0; color: var(--el-text-color-secondary); } } }
.tb { display: flex; gap: 8px; align-items: center; font-size: 12px; em { font-style: normal; color: var(--el-text-color-placeholder); font-size: 11px; } }
</style>
