import{d as X,cX as ot,X as at,h as a,j as i,A as $,w as t,b as e,bk as tt,e as d,m as s,c as f,a as r,a1 as W,F as x,k as O,t as g,M as rt,N as dt,aK as it,x as et,r as P,G as st}from"./index-e3346b9c.js";import{S as ut}from"./SettingItem-1ca4ad00.js";import{S as J}from"./SettingItemBox-89085063.js";import{g as pt}from"./plugin-625ea31a.js";import{i as nt}from"./icon-e7bb1467.js";import{i as ct,d as _t,f as R,B as I}from"./chartEditStore-4ab4ed53.js";/* empty css                                                                      */import{n as mt}from"./noData-e5cefb25.js";import{u as Q}from"./useTargetData.hook-495cf7e9.js";import{M as lt}from"./EditorWorker-413d4d3c.js";import"./editorWorker-259d4dbf.js";import{n as ft}from"./useLifeHandler.hook-25ff05ad.js";const vt={key:0,class:"no-data go-flex-center"},gt=["src"],yt=X({__name:"index",setup(Y){const{CloseIcon:w,AddIcon:H,HelpOutlineIcon:F}=nt.ionicons5,{targetData:C,chartEditStore:D}=Q(),V=[ot.PARAMS,ot.HEADER],S=at(()=>{const m=C.value.interactActions;return m?m.map(n=>({label:n.interactName,value:n.interactType})):[]}),N=at(()=>C.value.option),k=(m,n)=>{if(!m)return{};const o=D.requestGlobalConfig.requestDataPond.find(h=>h.dataPondId===m)?.dataPondRequestConfig.requestParams;return o?o[n]:D.componentList[D.fetchTargetIndex(m)]?.request.requestParams[n]},T=m=>!m||!C.value.interactActions?[]:C.value.interactActions.find(o=>o.interactType===m)?.componentEmitEvents[N.value[ct]]||[],G=()=>{const m=p=>p.reduce((_,u)=>(!u.groupList&&u.request.requestDataType===it.AJAX&&u.request.requestUrl&&_.push(u),u.groupList&&u.groupList.length>0?[..._,...m(u.groupList)]:_),[]),o=m(D.componentList).filter(p=>{const _=p.id!==C.value.id,u=p.chartConfig.chartFrame!==_t.STATIC,v=!p.isGroup;return _&&u&&v}).map(p=>({id:p.id,title:p.chartConfig.title,disabled:!1,type:"componentList"})),b=D.requestGlobalConfig.requestDataPond.map(p=>({id:p.dataPondId,title:p.dataPondName,disabled:!1,type:"requestDataPond"})).concat(o);return C.value.events.interactEvents?.forEach(p=>{b.forEach(_=>{_.id===p.interactComponentId&&(_.disabled=!0)})}),b},q=()=>{C.value.events.interactEvents.push({interactOn:void 0,interactComponentId:void 0,interactFn:{}})},K=m=>{pt({message:"是否删除此关联交互模块?",onPositiveCallback:()=>{C.value.events.interactEvents.splice(m,1)}})};return(m,n)=>{const o=a("n-icon"),h=a("n-button"),b=a("n-text"),p=a("n-space"),_=a("n-divider"),u=a("n-tag"),v=a("n-select"),M=a("n-input-group"),L=a("n-tooltip"),z=a("n-table"),B=a("n-card"),j=a("n-collapse-item");return S.value.length?(i(),$(j,{key:0,title:"组件交互",name:"1"},{"header-extra":t(()=>[e(h,{type:"primary",tertiary:"",size:"small",onClick:tt(q,["stop"])},{icon:t(()=>[e(o,null,{default:t(()=>[e(d(H))]),_:1})]),default:t(()=>[n[0]||(n[0]=s(" 新增 ",-1))]),_:1})]),default:t(()=>[d(C).events.interactEvents.length?W("",!0):(i(),f("div",vt,[r("img",{src:d(mt),alt:"暂无数据"},null,8,gt),e(b,{depth:3},{default:t(()=>[...n[1]||(n[1]=[s("暂无内容",-1)])]),_:1})])),(i(!0),f(x,null,O(d(C).events.interactEvents,(E,A)=>(i(),$(B,{key:A,class:"n-card-shallow",size:"small"},{default:t(()=>[e(p,{justify:"space-between"},{default:t(()=>[e(b,null,{default:t(()=>[s("关联组件 - "+g(A+1),1)]),_:2},1024),e(h,{type:"error",text:"",size:"small",onClick:y=>K(A)},{icon:t(()=>[e(o,null,{default:t(()=>[e(d(w))]),_:1})]),_:1},8,["onClick"])]),_:2},1024),e(_,{style:{margin:"10px 0"}}),e(u,{bordered:!1,type:"primary"},{default:t(()=>[...n[2]||(n[2]=[s(" 选择目标组件 ",-1)])]),_:1}),e(d(J),{name:"触发事件",alone:!0},{default:t(()=>[S.value?(i(),$(M,{key:0},{default:t(()=>[e(v,{class:"select-type-options",value:E.interactOn,"onUpdate:value":y=>E.interactOn=y,size:"tiny",options:S.value},null,8,["value","onUpdate:value","options"])]),_:2},1024)):W("",!0)]),_:2},1024),e(d(J),{alone:!0},{name:t(()=>[e(b,null,{default:t(()=>[...n[3]||(n[3]=[s("绑定",-1)])]),_:1}),e(L,{trigger:"hover"},{trigger:t(()=>[e(o,{size:"21",depth:3},{default:t(()=>[e(d(F))]),_:1})]),default:t(()=>[e(b,null,{default:t(()=>[...n[4]||(n[4]=[s("不支持「静态组件」支持「组件」「公共APi」",-1)])]),_:1})]),_:1})]),default:t(()=>[e(v,{class:"select-type-options","value-field":"id","label-field":"title",size:"tiny",filterable:"",placeholder:"仅展示符合条件的组件",value:E.interactComponentId,"onUpdate:value":y=>E.interactComponentId=y,options:G()},null,8,["value","onUpdate:value","options"])]),_:2},1024),T(E.interactOn).length?(i(),$(d(J),{key:0,name:"查询结果",alone:!0},{default:t(()=>[e(z,{size:"small",striped:""},{default:t(()=>[r("thead",null,[r("tr",null,[(i(),f(x,null,O(["参数","说明"],y=>r("th",{key:y},g(y),1)),64))])]),r("tbody",null,[(i(!0),f(x,null,O(T(E.interactOn),(y,c)=>(i(),f("tr",{key:c},[r("td",null,g(y.value),1),r("td",null,g(y.label),1)]))),128))])]),_:2},1024)]),_:2},1024)):W("",!0),e(u,{bordered:!1,type:"primary"},{default:t(()=>[...n[5]||(n[5]=[s(" 关联目标请求参数 ",-1)])]),_:1}),(i(),f(x,null,O(V,y=>e(d(J),{name:y,key:y},{default:t(()=>[(i(!0),f(x,null,O(k(E.interactComponentId,y),(c,l,U)=>(i(),$(d(ut),{key:U,name:`${l}`},{default:t(()=>[e(v,{size:"tiny",value:E.interactFn[l],"onUpdate:value":Z=>E.interactFn[l]=Z,options:T(E.interactOn),clearable:""},null,8,["value","onUpdate:value","options"])]),_:2},1032,["name"]))),128)),rt(e(b,{class:"go-pt-1",depth:"3"},{default:t(()=>[...n[6]||(n[6]=[s(" 暂无数据 ",-1)])]),_:1},512),[[dt,JSON.stringify(k(E.interactComponentId,y))==="{}"]])]),_:2},1032,["name"])),64))]),_:2},1024))),128))]),_:1})):W("",!0)}}});const bt=et(yt,[["__scopeId","data-v-80f27dfa"]]),xt=`
console.log(e)
`,ht=`
console.log(echarts)
`,Et=`
console.log(components)
`,wt=`
console.log(node_modules)
`,Ct=`
// 在渲染之后才能获取 dom 实例
e.el.addEventListener('click', () => {
  alert('我触发拉~');
}, false)
`,Ot=`
await import('https://lf3-cdn-tos.bytecdntp.com/cdn/expire-1-M/lodash.js/4.17.21/lodash.js')

// lodash 默认赋值给 "_"
console.log('isEqual', _.isEqual(['1'], ['1']))
`,kt=`
// 获取echart实例
const chart = this.refs.vChartRef.chart

// 图表设置tooltip
chart.setOption({
  tooltip: {
    trigger: 'axis', //item
    enterable: true, 
    formatter (params) {
      return\`
        <div>
          <img src="https://portrait.gitee.com/uploads/avatars/user/1654/4964818_MTrun_1653229420.png!avatar30">
          <b><a href="https://gitee.com/dromara/go-view">《这是一个自定义的tooltip》</a></b>
        <div>
        <div style='border-radius:35px;color:#666'>
        \${Object.entries(params[0].value).map(kv => \`<div>\${kv[0]}:\${kv[1]}</div>\`).join('')}
        </div>
      \`;
    },
  }
})
`,Tt=`
// 组件样式作用域标识
const scoped = this.subTree.scopeId
function loadStyleString(css){
	let style = document.createElement('style')
	style.type = 'text/css'
	style.appendChild(document.createTextNode(css))
	let head = document.getElementsByTagName('head')[0]
	head.appendChild(style)
}
loadStyleString(\`
.dv-scroll-board[\${scoped}] {
  position: relative;
  overflow: hidden;
}
.dv-scroll-board[\${scoped}]::before {
  content: '';
  display: block;
  position: absolute;
  top: -20%;
  left: -100%;
  width: 550px;
  height: 60px;
  transform: rotate(-45deg);
  background-image: linear-gradient(rgba(0, 0, 0, 0), rgba(255, 255, 255, 0.3), rgba(0, 0, 0, 0));
  animation: cross 2s infinite;
}
@keyframes cross{
  to{
    top: 80%;
    left: 100%;
    transform: rotate(-45deg);
  }
}
\`)
`,Dt=`
const chart = this.refs.vChartRef.chart
// 定义地图原点大小 同理可自定义标签等等内容
this.props.chartConfig.option.series[0].symbolSize = (val) => {
  return Math.sqrt(val[2]) / 3;
}
this.setupState.vEchartsSetOption();
let i = 0; // 当前轮播索引
const len = 3; // 轮播部分提示
(function showTips() {
  const action = (type, dataIndex) => {
    chart.dispatchAction({
      type,
      dataIndex,
      seriesIndex: 0,
    });
  }
  setInterval(() => {
    action("downplay", i);
    action("hideTip", i);
    if (i === len) i = 0;
    i++;
    action("highlight", i);
    action("showTip", i);
  }, 2000);
})()
`,St=[{description:"获取当前组件实例",code:xt},{description:"获取全局 echarts 实例",code:ht},{description:"获取组件图表集合",code:Et},{description:"获取 nodeModules 实例",code:wt},{description:"获取远程 CDN 库",code:Ot},{description:"设置文字组件点击事件",code:Ct},{description:"修改图表 tooltip",code:kt},{description:"添加【轮播列表】样式",code:Tt},{description:"修改【地图】圆点，新增提示自动轮播",code:Dt}],It={class:"func-annotate"},Nt={class:"func-keyword"},$t={class:"go-ml-4"},Mt={class:"go-pl-3"},Lt={class:"func-keyNameWord"},At={class:"go-flex-items-center"},Ut=X({__name:"index",setup(Y){const{targetData:w,chartEditStore:H}=Q(),{DocumentTextIcon:F,ChevronDownIcon:C,PencilIcon:D}=nt.ionicons5,V={[R.VNODE_BEFORE_MOUNT]:"渲染之前",[R.VNODE_MOUNTED]:"渲染之后"},S={[R.VNODE_BEFORE_MOUNT]:"此时组件 DOM 还未存在",[R.VNODE_MOUNTED]:"此时组件 DOM 已经存在"},N=P(!1),k=P(R.VNODE_MOUNTED);let T=P({...w.value.events.advancedEvents});const G=P(!1),q=()=>{let n="",o="",h="";return G.value=Object.entries(T.value).every(([b,p])=>{try{const _=Object.getPrototypeOf(async function(){}).constructor;return new _(p),!0}catch(_){return o=_.message,h=_.name,n=b,!1}}),{errorFn:n,message:o,name:h}},K=()=>{N.value=!1},m=()=>{if(q().errorFn){window.$message.error("事件函数错误，无法进行保存");return}Object.values(T.value).join("").trim()===""?w.value.events.advancedEvents={vnodeBeforeMount:void 0,vnodeMounted:void 0}:w.value.events.advancedEvents={...T.value},K()};return st(()=>N.value,n=>{n&&(T.value={...w.value.events.advancedEvents})}),(n,o)=>{const h=a("n-icon"),b=a("n-button"),p=a("n-code"),_=a("n-card"),u=a("n-collapse-item"),v=a("n-text"),M=a("n-space"),L=a("n-tab-pane"),z=a("n-tabs"),B=a("n-layout"),j=a("n-collapse"),E=a("n-scrollbar"),A=a("n-tag"),y=a("n-layout-sider"),c=a("n-modal");return i(),f(x,null,[e(u,{title:"高级事件配置",name:"3"},{"header-extra":t(()=>[e(b,{type:"primary",tertiary:"",size:"small",onClick:o[0]||(o[0]=tt(l=>N.value=!0,["stop"]))},{icon:t(()=>[e(h,null,{default:t(()=>[e(d(D))]),_:1})]),default:t(()=>[o[3]||(o[3]=s(" 编辑 ",-1))]),_:1})]),default:t(()=>[e(_,{class:"collapse-show-box"},{default:t(()=>[(i(!0),f(x,null,O(d(R),l=>(i(),f("div",{key:l},[r("p",null,[r("span",It,"// "+g(V[l]),1),o[4]||(o[4]=r("br",null,null,-1)),r("span",Nt,"async "+g(l),1),o[5]||(o[5]=s(" (e, components, echarts, node_modules) { ",-1))]),r("p",$t,[e(p,{code:(d(w).events.advancedEvents||{})[l]||"",language:"typescript"},null,8,["code"])]),o[6]||(o[6]=r("p",null,[s("}"),r("span",null,",")],-1))]))),128))]),_:1})]),_:1}),e(c,{class:"go-chart-data-monaco-editor",show:N.value,"onUpdate:show":o[2]||(o[2]=l=>N.value=l),"mask-closable":!1},{default:t(()=>[e(_,{bordered:!1,role:"dialog",size:"small","aria-modal":"true",style:{width:"1200px",height:"700px"}},{header:t(()=>[e(M,null,{default:t(()=>[e(v,null,{default:t(()=>[...o[7]||(o[7]=[s("高级事件编辑器（配合源码使用）",-1)])]),_:1})]),_:1})]),"header-extra":t(()=>[...o[8]||(o[8]=[])]),action:t(()=>[e(M,{justify:"space-between"},{default:t(()=>[r("div",At,[e(A,{bordered:!1,type:"primary"},{icon:t(()=>[e(h,{component:d(F)},null,8,["component"])]),default:t(()=>[o[17]||(o[17]=s(" 说明 ",-1))]),_:1}),e(v,{class:"go-ml-2",depth:"2"},{default:t(()=>[...o[18]||(o[18]=[s("通过提供的参数可为图表增加定制化的tooltip、交互事件等等",-1)])]),_:1})]),e(M,null,{default:t(()=>[e(b,{size:"medium",onClick:K},{default:t(()=>[...o[19]||(o[19]=[s("取消",-1)])]),_:1}),e(b,{size:"medium",type:"primary",onClick:m},{default:t(()=>[...o[20]||(o[20]=[s("保存",-1)])]),_:1})]),_:1})]),_:1})]),default:t(()=>[e(B,{"has-sider":"","sider-placement":"right"},{default:t(()=>[e(B,{style:{height:"580px","padding-right":"20px"}},{default:t(()=>[e(z,{value:k.value,"onUpdate:value":o[1]||(o[1]=l=>k.value=l),type:"card","tab-style":"min-width: 100px;"},{suffix:t(()=>[e(v,{class:"tab-tip",type:"warning"},{default:t(()=>[s("提示: "+g(S[k.value]),1)]),_:1})]),default:t(()=>[(i(!0),f(x,null,O(d(R),(l,U)=>(i(),$(L,{key:U,tab:`${V[l]}-${l}`,name:l},{default:t(()=>[r("p",Mt,[o[9]||(o[9]=r("span",{class:"func-keyword"},"async function   ",-1)),r("span",Lt,g(l)+"(e, components, echarts, node_modules)  {",1)]),e(d(lt),{modelValue:d(T)[l],"onUpdate:modelValue":Z=>d(T)[l]=Z,height:"480px",language:"javascript"},null,8,["modelValue","onUpdate:modelValue"]),o[10]||(o[10]=r("p",{class:"go-pl-3 func-keyNameWord"},"}",-1))]),_:2},1032,["tab","name"]))),128))]),_:1},8,["value"])]),_:1}),e(y,{"collapsed-width":14,width:340,"show-trigger":"bar","collapse-mode":"transform","content-style":"padding: 12px 12px 0px 12px;margin-left: 3px;"},{default:t(()=>[e(z,{"default-value":"1","justify-content":"space-evenly",type:"segment"},{default:t(()=>[e(L,{tab:"验证结果",name:"1",size:"small"},{default:t(()=>[e(E,{trigger:"none",style:{"max-height":"505px"}},{default:t(()=>[e(j,{class:"go-px-3","arrow-placement":"right","default-expanded-names":[1,2,3]},{default:t(()=>[(i(!0),f(x,null,O([q()],l=>(i(),f(x,{key:l},[e(u,{title:"错误函数",name:1},{default:t(()=>[e(v,{depth:"3"},{default:t(()=>[s(g(l.errorFn||"暂无"),1)]),_:2},1024)]),_:2},1024),e(u,{title:"错误信息",name:2},{default:t(()=>[e(v,{depth:"3"},{default:t(()=>[s(g(l.name||"暂无"),1)]),_:2},1024)]),_:2},1024),e(u,{title:"堆栈信息",name:3},{default:t(()=>[e(v,{depth:"3"},{default:t(()=>[s(g(l.message||"暂无"),1)]),_:2},1024)]),_:2},1024)],64))),128))]),_:1})]),_:1})]),_:1}),e(L,{tab:"变量说明",name:"2"},{default:t(()=>[e(E,{trigger:"none",style:{"max-height":"505px"}},{default:t(()=>[e(j,{class:"go-px-3","arrow-placement":"right","default-expanded-names":[1,2,3,4]},{default:t(()=>[e(u,{title:"e",name:1},{default:t(()=>[e(v,{depth:"3"},{default:t(()=>[...o[11]||(o[11]=[s("触发对应生命周期事件时接收的参数",-1)])]),_:1})]),_:1}),e(u,{title:"this",name:2},{default:t(()=>[e(v,{depth:"3"},{default:t(()=>[...o[12]||(o[12]=[s("图表组件实例",-1)])]),_:1}),o[13]||(o[13]=r("br",null,null,-1)),(i(),f(x,null,O(["refs","setupState","ctx","props","..."],l=>e(A,{class:"go-m-1",key:l},{default:t(()=>[s(g(l),1)]),_:2},1024)),64))]),_:1}),e(u,{title:"components",name:3},{default:t(()=>[e(v,{depth:"3"},{default:t(()=>[...o[14]||(o[14]=[s("当前大屏内所有组件的集合id 图表组件中的配置id，可以获取其他图表组件进行控制",-1)])]),_:1}),e(p,{code:`{
  [id]: component
}`,language:"typescript"})]),_:1}),e(u,{title:"node_modules",name:4},{default:t(()=>[e(v,{depth:"3"},{default:t(()=>[...o[15]||(o[15]=[s("以下是内置在代码环境中可用的包变量",-1)])]),_:1}),o[16]||(o[16]=r("br",null,null,-1)),(i(!0),f(x,null,O(Object.keys(d(ft)||{}),l=>(i(),$(A,{class:"go-m-1",key:l},{default:t(()=>[s(g(l),1)]),_:2},1024))),128))]),_:1})]),_:1})]),_:1})]),_:1}),e(L,{tab:"介绍案例",name:"3"},{default:t(()=>[e(E,{trigger:"none",style:{"max-height":"505px"}},{default:t(()=>[e(j,{"arrow-placement":"right"},{default:t(()=>[(i(!0),f(x,null,O(d(St),(l,U)=>(i(),$(u,{key:U,title:`案例${U+1}：${l.description}`,name:U},{default:t(()=>[e(p,{code:l.code,language:"typescript"},null,8,["code"])]),_:2},1032,["title","name"]))),128))]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1},8,["show"])],64)}}});const Ft=et(Ut,[["__scopeId","data-v-d73dd522"]]),jt={class:"func-annotate"},Pt={class:"func-keyword"},Vt={class:"go-ml-4"},qt={class:"go-pl-3"},zt={class:"func-keyNameWord"},Bt={class:"go-flex-items-center"},Rt=X({__name:"index",setup(Y){const{targetData:w,chartEditStore:H}=Q(),{DocumentTextIcon:F,ChevronDownIcon:C,PencilIcon:D}=nt.ionicons5,V={[I.ON_CLICK]:"单击",[I.ON_DBL_CLICK]:"双击",[I.ON_MOUSE_ENTER]:"鼠标进入",[I.ON_MOUSE_LEAVE]:"鼠标移出"},S=P(!1),N=P(I.ON_CLICK);let k=P({...w.value.events.baseEvent});const T=P(!1),G=()=>{let m="",n="",o="";return T.value=Object.entries(k.value).every(([h,b])=>{try{const p=Object.getPrototypeOf(async function(){}).constructor;return new p(b),!0}catch(p){return n=p.message,o=p.name,m=h,!1}}),{errorFn:m,message:n,name:o}},q=()=>{S.value=!1},K=()=>{if(G().errorFn){window.$message.error("事件函数错误，无法进行保存");return}Object.values(k.value).join("").trim()===""?w.value.events.baseEvent={[I.ON_CLICK]:void 0,[I.ON_DBL_CLICK]:void 0,[I.ON_MOUSE_ENTER]:void 0,[I.ON_MOUSE_LEAVE]:void 0}:w.value.events.baseEvent={...k.value},q()};return st(()=>S.value,m=>{m&&(k.value={...w.value.events.baseEvent})}),(m,n)=>{const o=a("n-icon"),h=a("n-button"),b=a("n-code"),p=a("n-card"),_=a("n-collapse-item"),u=a("n-text"),v=a("n-space"),M=a("n-tab-pane"),L=a("n-tabs"),z=a("n-layout"),B=a("n-collapse"),j=a("n-scrollbar"),E=a("n-layout-sider"),A=a("n-tag"),y=a("n-modal");return i(),f(x,null,[e(_,{title:"基础事件配置",name:"2"},{"header-extra":t(()=>[e(h,{type:"primary",tertiary:"",size:"small",onClick:n[0]||(n[0]=tt(c=>S.value=!0,["stop"]))},{icon:t(()=>[e(o,null,{default:t(()=>[e(d(D))]),_:1})]),default:t(()=>[n[3]||(n[3]=s(" 编辑 ",-1))]),_:1})]),default:t(()=>[e(p,{class:"collapse-show-box"},{default:t(()=>[(i(!0),f(x,null,O(d(I),c=>(i(),f("div",{key:c},[r("p",null,[r("span",jt,"// "+g(V[c]),1),n[4]||(n[4]=r("br",null,null,-1)),r("span",Pt,"async "+g(c),1),n[5]||(n[5]=s(" (mouseEvent,components) { ",-1))]),r("p",Vt,[e(b,{code:(d(w).events.baseEvent||{})[c]||"",language:"typescript"},null,8,["code"])]),n[6]||(n[6]=r("p",null,[s("}"),r("span",null,",")],-1))]))),128))]),_:1})]),_:1}),e(y,{class:"go-chart-data-monaco-editor",show:S.value,"onUpdate:show":n[2]||(n[2]=c=>S.value=c),"mask-closable":!1},{default:t(()=>[e(p,{bordered:!1,role:"dialog",size:"small","aria-modal":"true",style:{width:"1200px",height:"700px"}},{header:t(()=>[e(v,null,{default:t(()=>[e(u,null,{default:t(()=>[...n[7]||(n[7]=[s("基础事件编辑器",-1)])]),_:1})]),_:1})]),"header-extra":t(()=>[...n[8]||(n[8]=[])]),action:t(()=>[e(v,{justify:"space-between"},{default:t(()=>[r("div",Bt,[e(A,{bordered:!1,type:"primary"},{icon:t(()=>[e(o,{component:d(F)},null,8,["component"])]),default:t(()=>[n[13]||(n[13]=s(" 说明 ",-1))]),_:1}),e(u,{class:"go-ml-2",depth:"2"},{default:t(()=>[...n[14]||(n[14]=[s("编写方式同正常 JavaScript 写法",-1)])]),_:1})]),e(v,null,{default:t(()=>[e(h,{size:"medium",onClick:q},{default:t(()=>[...n[15]||(n[15]=[s("取消",-1)])]),_:1}),e(h,{size:"medium",type:"primary",onClick:K},{default:t(()=>[...n[16]||(n[16]=[s("保存",-1)])]),_:1})]),_:1})]),_:1})]),default:t(()=>[e(z,{"has-sider":"","sider-placement":"right"},{default:t(()=>[e(z,{style:{height:"580px","padding-right":"20px"}},{default:t(()=>[e(L,{value:N.value,"onUpdate:value":n[1]||(n[1]=c=>N.value=c),type:"card","tab-style":"min-width: 100px;"},{suffix:t(()=>[e(u,{class:"tab-tip",type:"warning"},{default:t(()=>[...n[9]||(n[9]=[s("提示: ECharts 组件会拦截鼠标事件",-1)])]),_:1})]),default:t(()=>[(i(!0),f(x,null,O(d(I),(c,l)=>(i(),$(M,{key:l,tab:`${V[c]}-${c}`,name:c},{default:t(()=>[r("p",qt,[n[10]||(n[10]=r("span",{class:"func-keyword"},"async function   ",-1)),r("span",zt,g(c)+"(mouseEvent,components)  {",1)]),e(d(lt),{modelValue:d(k)[c],"onUpdate:modelValue":U=>d(k)[c]=U,height:"480px",language:"javascript"},null,8,["modelValue","onUpdate:modelValue"]),n[11]||(n[11]=r("p",{class:"go-pl-3 func-keyNameWord"},"}",-1))]),_:2},1032,["tab","name"]))),128))]),_:1},8,["value"])]),_:1}),e(E,{"collapsed-width":14,width:340,"show-trigger":"bar","collapse-mode":"transform","content-style":"padding: 12px 12px 0px 12px;margin-left: 3px;"},{default:t(()=>[e(L,{"default-value":"1","justify-content":"space-evenly",type:"segment"},{default:t(()=>[e(M,{tab:"验证结果",name:"1",size:"small"},{default:t(()=>[e(j,{trigger:"none",style:{"max-height":"505px"}},{default:t(()=>[e(B,{class:"go-px-3","arrow-placement":"right","default-expanded-names":[1,2,3]},{default:t(()=>[(i(!0),f(x,null,O([G()],c=>(i(),f(x,{key:c},[e(_,{title:"错误函数",name:1},{default:t(()=>[e(u,{depth:"3"},{default:t(()=>[s(g(c.errorFn||"暂无"),1)]),_:2},1024)]),_:2},1024),e(_,{title:"错误信息",name:2},{default:t(()=>[e(u,{depth:"3"},{default:t(()=>[s(g(c.name||"暂无"),1)]),_:2},1024)]),_:2},1024),e(_,{title:"堆栈信息",name:3},{default:t(()=>[e(u,{depth:"3"},{default:t(()=>[s(g(c.message||"暂无"),1)]),_:2},1024)]),_:2},1024)],64))),128))]),_:1})]),_:1})]),_:1}),e(M,{tab:"变量说明",name:"2"},{default:t(()=>[e(j,{trigger:"none",style:{"max-height":"505px"}},{default:t(()=>[e(B,{class:"go-px-3","arrow-placement":"right","default-expanded-names":[1,2]},{default:t(()=>[e(_,{title:"mouseEvent",name:1},{default:t(()=>[e(u,{depth:"3"},{default:t(()=>[...n[12]||(n[12]=[s("鼠标事件对象",-1)])]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1},8,["show"])],64)}}});const Gt=et(Rt,[["__scopeId","data-v-258b0391"]]),ae=X({__name:"index",setup(Y){const{targetData:w}=Q();return(H,F)=>{const C=a("n-text"),D=a("n-collapse");return i(),$(D,{class:"go-mt-3","arrow-placement":"right","default-expanded-names":["1","2"]},{default:t(()=>[e(C,{depth:"3"},{default:t(()=>[F[0]||(F[0]=s(" 组件 id： ",-1)),e(C,null,{default:t(()=>[s(g(d(w).id),1)]),_:1})]),_:1}),e(d(bt)),e(d(Gt)),e(d(Ft))]),_:1})}}});export{ae as default};
