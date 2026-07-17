<template>
  <!-- V6.2 N4 训练模式(§八):生产同款组件+回放场景;六课目状态机判定;
       通过全部课目→自动签发 training_certification 解锁新增风险命令(减险永远可用)。 -->
  <div class="training">
    <div class="tbanner"><FIcon name="cap" :size="13"/> 训练模式 · 回放数据 · 不产生真实订单 —— 认证只解锁「新增风险」类命令;撤单/减仓/还币等减险动作无论是否通过都可用</div>
    <div class="thead">
      <b>六课目 · 已过 {{ data.passed ?? 0 }}/{{ data.total ?? 6 }}</b>
      <span class="cert" :class="{ok:data.certified}">{{ data.certified ? '已认证('+data.cert_version+') · 生产新增风险命令已解锁' : '未认证 · 完成全部课目自动签发' }}</span>
    </div>
    <div class="courses">
      <!-- 加载失败/空绝不静默(EmptyState规范):给原因+重试,旧bundle场景提示强刷 -->
      <div v-if="loadErr" class="loaderr">
        <b>课目列表加载失败</b>
        <p>{{ loadErr }}</p>
        <p class="lh">若刚更新过系统,请按 Ctrl+Shift+R 强制刷新页面后重试</p>
        <button class="tb1 start" @click="load">↻ 重试</button>
      </div>
      <div v-else-if="!data.courses" class="loaderr"><b>加载中…</b></div>
      <div v-for="c in data.courses" :key="c.course" class="course" :class="{done:c.state==='PASSED', cur:active===c.course}">
        <div class="chd" @click="active = active===c.course ? '' : c.course">
          <span class="ord">{{ c.order }}</span>
          <b>{{ c.title }}</b>
          <span class="brief">{{ c.brief }}</span>
          <span class="fill"></span>
          <span class="st" :class="c.state">{{ {NOT_STARTED:'未开始',IN_PROGRESS:'进行中',PASSED:'通过',FAILED:'重新开始'}[c.state] }}</span>
        </div>
        <div v-if="active===c.course" class="cbody">
          <!-- 场景卡:回放数据渲染(生产同款组件语言);未开始=锁定,先点开始训练 -->
          <div class="scene" :class="{locked:c.state!=='IN_PROGRESS'}">
            <template v-if="c.course==='巡检'">
              <div class="scline ok"><FIcon name="check" :size="12"/> 网站:正常 · 当前允许操作:全部 · 候选2/持有1/异常0</div>
              <button class="tb1" @click="act(c,'ack_status')">我已确认系统状态</button>
            </template>
            <template v-else-if="c.course==='候选审批'">
              <div class="scrow"><b>DEMOUSDT · C2.H</b><span class="up">+18.4 bps/日</span><span class="t3s">bybit↔binance · 风险低</span></div>
              <button class="tb1 gold" @click="act(c,'send_to_workbench')">送入工作台(试算不下单)</button>
            </template>
            <template v-else-if="c.course==='补对冲'">
              <div class="scrow warn2"><b>DEMOUSDT · C3.S</b><span>已卖出 800 · 已对冲 600 · <b class="dn">缺口 200</b></span></div>
              <button class="tb1 gold" @click="act(c,'complete_hedge')">完成对冲(补齐200)</button>
            </template>
            <template v-else-if="c.course==='买回还币'">
              <div class="scrow"><b>DEMOUSDT · C3.S</b><span>借币 3000 · 已买回 3000 · 可还币</span></div>
              <div class="btnrow">
                <button class="tb1" @click="act(c,'buy_back')">① 买回</button>
                <button class="tb1" @click="act(c,'repay')">② 还币</button>
              </div>
              <p class="hint2">顺序不可反:先买回现货,才有币可还</p>
            </template>
            <template v-else-if="c.course==='平台限制'">
              <div class="scrow bad2"><b>demoex</b><span>P1 · 提现连败 → 建议冻结该平台新增</span></div>
              <div class="btnrow">
                <button class="tb1" @click="act(c,'ack_incident')">① 确认事件</button>
                <button class="tb1 red" @click="act(c,'freeze_venue')">② 冻结该平台新增(减险)</button>
              </div>
            </template>
            <template v-else-if="c.course==='人工双永续研判'">
              <div class="scrow"><b>DEMOUSDT · C2.P</b><span class="up">费差 0.42%/日</span><span class="t3s">bitget(空)↔binance(多) · 人工双永续</span></div>
              <div class="btnrow">
                <button class="tb1" @click="act(c,'open_research')">① 打开研判工作区</button>
                <button class="tb1" @click="act(c,'complete_research')">② 完成四步研判(结论=准备计划)</button>
                <button class="tb1 gold" @click="act(c,'create_manual_plan')">③ 生成人工计划(DRY_RUN·不下单)</button>
              </div>
              <p class="hint2">研判只产结论,计划仍走 冷却→二次认证 审批链;AiCoin 仅作证据参考</p>
            </template>
            <template v-else>
              <div class="scline ok">恒等式:净值变化−出入金=各收益之和 · 未归类账目 0 条</div>
              <button class="tb1" @click="act(c,'confirm_recon')">确认账目核对通过</button>
            </template>
          </div>
          <div class="steps">
            <span v-for="(e,i) in c.expect_cn" :key="i" class="step" :class="{done:i<c.steps_done}">{{ i+1 }}. {{ e }}</span>
          </div>
          <button v-if="c.state!=='IN_PROGRESS'" class="tb1 start" @click="start(c)">{{ c.state==='PASSED' ? '重新练习' : '开始训练' }}</button>
          <p v-if="msg[c.course]" class="fb" :class="{err:msgErr[c.course]}">{{ msg[c.course] }}</p>
        </div>
      </div>
    </div>
    <p class="fnote">课目判定=确定性动作序列匹配(非LLM) ｜ 训练命令走独立路由零生产影响 ｜ 现役操作员已按祖父条款预发认证</p>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { mixApi } from '../../api/mix'

const data = ref({})
const active = ref('')
const msg = ref({})
const msgErr = ref({})
const loadErr = ref('')

async function load() {
  loadErr.value = ''
  try {
    if (typeof mixApi.v6Training !== 'function') throw new Error('前端版本过旧(缺训练接口),请强制刷新')
    const d = await mixApi.v6Training()
    if (!d || !Array.isArray(d.courses)) throw new Error('接口返回异常:' + JSON.stringify(d).slice(0, 120))
    data.value = d
  } catch (e) {
    loadErr.value = e?.detail || e?.message || String(e)
  }
}
async function start(c) {
  try {
    await mixApi.v6TrainingStart(c.course)
    msg.value = { ...msg.value, [c.course]: '已开始:' + c.brief }
    msgErr.value = { ...msgErr.value, [c.course]: false }
    load()
  } catch (e) { msg.value = { ...msg.value, [c.course]: e?.detail || '开始失败' }; msgErr.value = { ...msgErr.value, [c.course]: true } }
}
async function act(c, action) {
  try {
    const r = await mixApi.v6TrainingAct(c.course, action)
    msg.value = { ...msg.value, [c.course]: r.wrong ? r.hint : (r.note || '') }
    msgErr.value = { ...msgErr.value, [c.course]: !!r.wrong }
    if (r.state === 'PASSED' || r.cert_granted) load()
    if (r.cert_granted) window.dispatchEvent(new Event('mix-training-cert'))   // 菜单即时收敛,无需重登
  } catch (e) { msg.value = { ...msg.value, [c.course]: e?.detail || '先点开始训练' }; msgErr.value = { ...msgErr.value, [c.course]: true } }
}
onMounted(load)
</script>
<style scoped>
.training{display:flex;flex-direction:column;gap:10px;padding:4px 2px}
.tbanner{background:#4A9CFF14;border:1px solid #4A9CFF66;border-radius:6px;color:var(--mix-blue,#4A9CFF);
  font-size:11.5px;font-weight:700;padding:8px 14px}
.thead{display:flex;justify-content:space-between;align-items:center}
.thead b{font-size:13px;color:var(--mix-t1,#EAECEF)}
.cert{font-size:10.5px;color:var(--mix-t3,#5E6673)}
.cert.ok{color:#0ECB81;font-weight:700}
.courses{display:flex;flex-direction:column;gap:8px}
.course{background:var(--mix-card,#181A20);border:1px solid var(--mix-border,#2B3139);border-radius:8px;overflow:hidden}
.course.done{border-color:#0ECB8144}
.course.cur{border-color:#F0B90B4D}
.chd{display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer}
.ord{width:22px;height:22px;border-radius:50%;background:var(--mix-card2,#20242C);color:var(--mix-t2,#848E9C);
  font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex:none}
.chd b{font-size:12.5px;color:var(--mix-t1,#EAECEF)}
.brief{font-size:10.5px;color:var(--mix-t3,#5E6673)}
.st{font-size:10.5px;font-weight:700;color:var(--mix-t3,#5E6673)}
.st.PASSED{color:#0ECB81}.st.IN_PROGRESS{color:#F0B90B}
.cbody{border-top:1px solid var(--mix-border,#2B3139);padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.scene{background:var(--mix-panel,#12151A);border:1px solid var(--mix-border,#2B3139);border-radius:6px;
  padding:10px 14px;display:flex;flex-direction:column;gap:8px}
.scene.locked{opacity:.45;pointer-events:none}
.scline{font-size:11.5px}.scline.ok{color:#0ECB81;font-weight:700}
.scrow{display:flex;gap:12px;align-items:baseline;font-size:11.5px;color:var(--mix-t2,#848E9C)}
.scrow b{color:var(--mix-t1,#EAECEF)}
.scrow.warn2{color:#F0B90B}.scrow.bad2 b{color:#F6465D}
.up{color:#0ECB81;font-weight:700}.dn{color:#F6465D}
.t3s{font-size:10px;color:var(--mix-t3,#5E6673)}
.btnrow{display:flex;gap:8px}
.tb1{align-self:flex-start;font-size:11px;font-weight:700;padding:6px 14px;border-radius:6px;cursor:pointer;
  background:var(--mix-card2,#20242C);color:var(--mix-t1,#EAECEF);border:1px solid var(--mix-border,#2B3139)}
.tb1:hover{border-color:#F0B90B;color:#F0B90B}
.tb1.gold{background:#F0B90B1F;border-color:#F0B90B4D;color:#F0B90B}
.tb1.red{background:#F6465D14;border-color:#F6465D66;color:#F6465D}
.tb1.start{background:#4A9CFF14;border-color:#4A9CFF66;color:#4A9CFF}
.steps{display:flex;gap:10px;flex-wrap:wrap}
.step{font-size:10px;color:var(--mix-t3,#5E6673)}
.step.done{color:#0ECB81;text-decoration:line-through}
.fb{font-size:11px;color:#0ECB81;margin:0}
.loaderr{background:var(--mix-card,#181A20);border:1px solid #F6465D66;border-radius:8px;padding:20px;
  display:flex;flex-direction:column;align-items:center;gap:6px}
.loaderr b{font-size:13px;color:#F6465D}
.loaderr p{font-size:11px;color:var(--mix-t2,#848E9C);margin:0}
.loaderr .lh{color:var(--mix-t3,#5E6673);font-size:10px}
.fb.err{color:#FF8A3D}
.hint2{font-size:9.5px;color:var(--mix-t3,#5E6673);margin:0}
.fnote{font-size:9.5px;color:var(--mix-t3,#5E6673)}
</style>
