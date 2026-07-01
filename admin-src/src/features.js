// 权益/功能 语义目录: 业务命名开关 ↔ 技术 feature_key(运营勾选, 不暴露裸 key/JSON)
// type: bool=开关; num=数值(填值, 如 max_pairs=3)
export const FEATURES = [
  { key:'auto_loop',   name:'全自动进出场',   type:'bool', hint:'解锁武装/全量自动交易循环' },
  { key:'max_pairs',   name:'对冲账户对数',   type:'num',  hint:'可挂的主+对冲账户对数(免费1)' },
  { key:'symbols',     name:'多币种',         type:'num',  hint:'可交易品种数(免费仅XAUUSD)' },
  { key:'speed_turbo', name:'极速档',         type:'bool', hint:'解锁 turbo 速度档' },
  { key:'max_clients', name:'多端登录',       type:'num',  hint:'同时在线设备数(免费1)' },
  { key:'ai_arb',      name:'AI套利分析',     type:'bool', hint:'主+对冲全产品对可套利性AI分析·机会挖掘·可视化(最高阶)' },
  { key:'mobile_access',name:'移动端使用权限',type:'bool', hint:'解锁手机/移动端使用(PC-CS客户端默认免费)' },
]
export const FEATURE_MAP = Object.fromEntries(FEATURES.map(f=>[f.key,f]))
// 运行期合入动态权益目录(Iap 页加载 /iap/features 后调用),使新增权益在全站显示中文名。
// type 归一: 后端 ftype(bool/num/json) → 前端 type(bool/num)
export function mergeRuntimeFeatures(list){
  (list||[]).forEach(f=>{
    const type = f.type || (f.ftype==='bool'?'bool':'num')
    FEATURE_MAP[f.key] = { key:f.key, name:f.name||f.key, type, hint:f.hint||'' }
  })
}
// 当前生效的权益项列表(动态优先, 未加载则回落静态 FEATURES)
export function currentFeatures(){ return Object.values(FEATURE_MAP) }
// feature_key → 中文名(未知 key 兜底原样),供权益区/授予区 label 中文化
export function featName(key){ const f=FEATURE_MAP[key]; return f ? f.name : key }
// grants 对象 → 中文标签串。bool 显示名、num 显示"名=值"、未知 key 兜底原样。
// 例 {auto_loop:'true',max_pairs:'3'} → "全自动进出场 · 对冲账户对数=3"
export function grantsToText(grants){
  if(!grants || typeof grants!=='object') return '—'
  const parts=[]
  for(const k of Object.keys(grants)){
    const v=grants[k]; const f=FEATURE_MAP[k]
    if(f){
      if(f.type==='bool'){ if(String(v).toLowerCase()==='true'||v===true) parts.push(f.name) }
      else parts.push(`${f.name}=${v}`)
    } else {
      // 未知/自定义权益:原样 key=值(bool true 只显 key)
      if(String(v).toLowerCase()==='true'||v===true) parts.push(k)
      else parts.push(`${k}=${v}`)
    }
  }
  return parts.length ? parts.join(' · ') : '—'
}
// 权益值中文化展示(bool→开/关、其余原值),供 entitlements 明细
export function entValText(key, v){
  const f=FEATURE_MAP[key]
  if(f && f.type==='bool') return (String(v).toLowerCase()==='true'||v===true) ? '开' : '关'
  return v==null||v==='' ? '—' : String(v)
}
// grants 对象 ↔ 勾选模型: {auto_loop:'true', max_pairs:'3'}
export function grantsToModel(grants){
  const m={}; FEATURES.forEach(f=>{
    const v = grants && grants[f.key]
    if(f.type==='bool') m[f.key] = (String(v).toLowerCase()==='true'||v===true)
    else m[f.key] = (v!=null && v!=='') ? v : ''
  }); return m
}
export function modelToGrants(model){
  const g={}; FEATURES.forEach(f=>{
    if(f.type==='bool'){ if(model[f.key]) g[f.key]='true' }
    else { if(model[f.key]!=='' && model[f.key]!=null) g[f.key]=String(model[f.key]) }
  }); return g
}
