type AiState = 'pending' | 'stale' | 'error' | 'veto' | 'approved';

type ModelCall = {
  model?: string | null; status?: string | null; allow?: boolean | null;
  confidence?: number | null; reason?: string | null; latency_sec?: number | null; latency_ms?: number | null;
  usage?: { total_tokens?: number | null; input_tokens?: number | null; output_tokens?: number | null;
    prompt_tokens?: number | null; completion_tokens?: number | null } | null;
};
type ModelDecision = {
  purpose?: string | null;
  status?: string | null; allow?: boolean | null; reasons?: string[] | null; decision_id?: string | null;
  created_at?: number | null; requested_at?: number | null; completed_at?: number | null; expires_at?: number | null;
  models?: { primary?: ModelCall | null; secondary?: ModelCall | null } | null;
};
export type PaperAiShadow = {
  enabled?: boolean | null; enforced?: boolean | null;
  roles?: Partial<Record<'scout' | 'trader' | 'auditor' | 'mechanic', { ok?: boolean | null } | null>> | null;
  last_gate_model_decision?: ModelDecision | null;
  runtime?: { status?: string | null; requests?: number | null; completed?: number | null; errors?: number | null;
    last_decision?: ModelDecision | null } | null;
};

const labels: Record<AiState, string> = {
  pending: '等待响应', stale: '已过期', error: '调用异常', veto: '已否决', approved: '已通过',
};
const reasonLabels: Record<string, string> = {
  AI_MODEL_APPROVED: '模型通过', AI_MODEL_DENIED: '模型否决', AI_DUAL_MODEL_APPROVED: '双模型一致通过',
  AI_MODEL_LOW_CONFIDENCE: '模型置信度不足', AI_MODEL_INVALID_RESPONSE: '模型响应无效', AI_MODEL_UNAVAILABLE: '模型暂不可用',
  AI_MODEL_TIMEOUT: '模型调用超时', AI_MODEL_CALL_FAILED: '模型调用失败', AI_DISTINCT_MODELS_REQUIRED: '需要两个不同模型复核',
  AI_REVIEW_PENDING: '等待模型评估', AI_REVIEW_COOLDOWN: '等待请求冷却', AI_REVIEW_QUEUE_FULL: '模型评估队列繁忙',
  AI_CONTEXT_STALE: '评估依据已过期', AI_CONTEXT_INVALID: '评估依据无效', AI_CONTEXT_MISMATCH: '模型判定与当前候选不匹配',
  AI_DECISION_EXPIRED: '模型判定已过期', AI_DECISION_UNKNOWN: '尚无对应模型判定', AI_AUDIT_UNAVAILABLE: '模型调用记录不可用',
  AI_ADVISOR_CLOSED: '模型调用器已停止', AI_DIAGNOSTIC_ONLY: '启动连接自检，不允许交易',
};
export const paperAiReason = (reason: string) => reasonLabels[reason] ?? reason;
const roles = [['scout', 'Scout · 侦察'], ['trader', 'Trader · 交易评估'],
  ['auditor', 'Auditor · 审计'], ['mechanic', 'Mechanic · 运行检查']] as const;
const numeric = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value);
const count = (value: number | null | undefined) => numeric(value) ? value!.toLocaleString('zh-CN') : '—';
const dateTime = (value: number | null | undefined) => numeric(value)
  ? new Date(value! * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—';

function stateOf(value?: { status?: string | null; allow?: boolean | null } | null, stale = false): AiState {
  const status = typeof value?.status === 'string' ? value.status.toLowerCase() : '';
  if (stale || ['stale', 'expired'].includes(status)) return 'stale';
  if (['error', 'failed', 'timeout', 'unavailable', 'invalid'].includes(status)) return 'error';
  if (['pending', 'running', 'queued', 'cooldown', 'busy', 'closed', 'idle', 'waiting', 'disabled', 'unconfigured'].includes(status)) return 'pending';
  if (value?.allow === false || ['veto', 'rejected', 'denied', 'blocked', 'hold'].includes(status)) return 'veto';
  if (value?.allow === true || ['approved', 'ok', 'success', 'succeeded'].includes(status)) return 'approved';
  return 'pending';
}

function StateBadge({ state }: { state: AiState }) {
  return <span className={`paper-ai-state paper-ai-${state}`} data-ai-state={state}>{labels[state]}</span>;
}

function tokens(call?: ModelCall | null) {
  const usage = call?.usage;
  if (numeric(usage?.total_tokens)) return usage!.total_tokens;
  const input = usage?.input_tokens ?? usage?.prompt_tokens;
  const output = usage?.output_tokens ?? usage?.completion_tokens;
  return numeric(input) && numeric(output) ? input! + output! : null;
}

export default function PaperAiStatus({ shadow, stale, now }: {
  shadow?: PaperAiShadow | null; stale: boolean; now: number;
}) {
  const runtime = shadow?.runtime;
  const decision = runtime?.last_decision;
  const runtimeIdle = runtime?.status?.toLowerCase() === 'idle';
  const historical = runtimeIdle && !!decision && !['pending', 'ready'].includes((decision.status ?? '').toLowerCase());
  const expired = stale || (numeric(decision?.expires_at) && now >= decision!.expires_at!);
  const gate = shadow?.last_gate_model_decision;
  const gateExpired = stale || (numeric(gate?.expires_at) && now >= gate!.expires_at!);
  const runtimeState = stateOf({ status: runtime?.status,
    allow: runtime?.status?.toLowerCase() === 'ready' ? decision?.allow : undefined },
  stale || (runtime?.status?.toLowerCase() === 'ready' && expired));
  const runtimeNote = runtime?.status?.toLowerCase() === 'cooldown' ? '请求冷却中'
    : runtime?.status?.toLowerCase() === 'busy' ? '请求处理中' : runtime?.status?.toLowerCase() === 'closed' ? '调用器已停止' : null;
  const decisionReasons = Array.isArray(decision?.reasons) ? decision.reasons.filter((reason) => typeof reason === 'string') : [];
  return <section className="paper-ai" aria-label="B 组 AI 假设层">
    <div className="paper-ai-heading"><b>AI 假设层 · B 组</b><span>{shadow?.enabled === false ? '未启用' : shadow?.enforced === true ? '模型判定参与准入' : '等待准入配置'}</span></div>
    <div className="paper-ai-role-heading">四角色规则检查</div>
    <div className="paper-ai-roles">
      {roles.map(([id, label]) => {
        const ok = shadow?.roles?.[id]?.ok;
        const state: AiState = stale ? 'stale' : ok === true ? 'approved' : ok === false ? 'veto' : 'pending';
        return <div className="paper-ai-role" key={id} data-ai-role={id}><span>{label}</span><StateBadge state={state} /></div>;
      })}
    </div>
    <div className="paper-ai-heading paper-ai-call-heading"><b>真实双模型调用</b>{runtimeIdle ? <span className="paper-ai-state paper-ai-pending">等待新候选</span> : <StateBadge state={runtimeState} />}</div>
    <div className="paper-ai-counts">请求 {count(runtime?.requests)} · 完成 {count(runtime?.completed)} · 异常 {count(runtime?.errors)}</div>
    {runtimeNote && <p className="paper-ai-note">{runtimeNote}</p>}
    {!decision && <p className="paper-ai-note">等待首次实际调用记录。</p>}
    {(['primary', 'secondary'] as const).map((slot) => {
      const call = decision?.models?.[slot];
      const totalTokens = tokens(call);
      const latency = call?.latency_sec ?? (numeric(call?.latency_ms) ? call!.latency_ms! / 1000 : null);
      return <div className="paper-ai-model" key={slot} data-ai-model={slot}>
        <div><span>{slot === 'primary' ? '主模型' : '复核模型'}</span><b>{call?.model || '等待实际模型信息'}</b><StateBadge state={stateOf(call, runtimeIdle ? false : expired)} /></div>
        <small>{numeric(latency) ? `耗时 ${latency!.toFixed(2)}s` : '耗时 —'}
          {numeric(call?.confidence) && call!.confidence! >= 0 && call!.confidence! <= 1 ? ` · 置信度 ${(call!.confidence! * 100).toFixed(0)}%` : ''}
          {totalTokens != null ? ` · ${count(totalTokens)} tokens` : ''}</small>
        {call?.reason && <p title={call.reason}>{paperAiReason(call.reason)}</p>}
      </div>;
    })}
    {decision?.purpose === 'STARTUP_READINESS' && <p className="paper-ai-note">启动连接自检 · {decision.reasons?.includes('AI_DIAGNOSTIC_ONLY') ? '双模型连接正常，自检拒绝交易。' : '仅验证模型连接。'}不计入策略候选、成交或收益。</p>}
    {runtimeIdle && decision && <p className="paper-ai-note">暂无新的 Paper 候选；上次模型判定仅作历史记录，不会用于当前开仓。</p>}
    {decision && <div className="paper-ai-result"><span>{historical ? '最近记录' : decision.purpose === 'STARTUP_READINESS' ? '最近自检' : '最近调用'}</span><StateBadge state={historical ? 'pending' : stateOf(decision, expired)} />
      {decisionReasons.length > 0 && !historical && <small title={decisionReasons.join(' · ')}>{decisionReasons.map(paperAiReason).join(' · ')}</small>}
      {historical && <small>历史记录，不用于当前开仓</small>}</div>}
    {gate && <div className="paper-ai-result"><span>当前入场判定</span><StateBadge state={stateOf(gate, gateExpired)} /></div>}
    {decision && <details><summary>查看模型调用时间与记录</summary><div className="paper-comparison-detail">
      <span>记录 {decision.decision_id || '—'}</span>
      <span>请求 {dateTime(decision.created_at ?? decision.requested_at)} · 完成 {dateTime(decision.completed_at)}</span>
      <span>有效期至 {dateTime(decision.expires_at)}</span>
    </div></details>}
  </section>;
}
