import { createRouter, createWebHistory } from 'vue-router'
import Layout from '../layout/Layout.vue'
const routes = [
  { path:'/', component:Layout, redirect:'/dashboard', children:[
    // ===== 分析(总控面板置顶) =====
    { path:'dashboard', name:'dashboard', meta:{title:'总控面板',icon:'Odometer',group:'分析'}, component:()=>import('../views/Dashboard.vue') },
    // ===== 经营 =====
    { path:'bi', name:'bi', meta:{title:'经营分析',icon:'TrendCharts',group:'经营'}, component:()=>import('../views/Bi.vue') },
    { path:'users', name:'users', meta:{title:'用户管理',icon:'User',group:'经营'}, component:()=>import('../views/Users.vue') },
    { path:'leads', name:'leads', meta:{title:'线索中台',icon:'ChatDotRound',group:'经营'}, component:()=>import('../views/Leads.vue') },
    { path:'trials', name:'trials', meta:{title:'试用管理',icon:'Stopwatch',group:'经营'}, component:()=>import('../views/Trials.vue') },
    { path:'orders', name:'orders', meta:{title:'充值订单',icon:'Wallet',group:'经营'}, component:()=>import('../views/Orders.vue') },
    { path:'agents', name:'agents', meta:{title:'三级代理',icon:'Share',group:'经营'}, component:()=>import('../views/Agents.vue') },
    { path:'iap', name:'iap', meta:{title:'内购配置',icon:'Goods',group:'经营'}, component:()=>import('../views/Iap.vue') },
    { path:'chat', name:'chat', meta:{title:'AI客服配置',icon:'Service',group:'经营'}, component:()=>import('../views/Chat.vue') },
    // ===== 运维 =====
    { path:'system', name:'system', meta:{title:'运维监控',icon:'Monitor',group:'运维'}, component:()=>import('../views/System.vue') },
    { path:'params', name:'params', meta:{title:'参数下发',icon:'Setting',group:'运维'}, component:()=>import('../views/Params.vue') },
    { path:'product', name:'product', meta:{title:'产品分析',icon:'PieChart',group:'运维'}, component:()=>import('../views/Product.vue') },
    { path:'notify', name:'notify', meta:{title:'系统通知',icon:'Bell',group:'运维'}, component:()=>import('../views/Notify.vue') },
    { path:'datamgr', name:'datamgr', meta:{title:'系统管理',icon:'Coin',group:'运维'}, component:()=>import('../views/DataMgr.vue') },
    { path:'operators', name:'operators', meta:{title:'操作员',icon:'Avatar',group:'运维'}, component:()=>import('../views/Operators.vue') },
    // 保留(未在新菜单顺序内, 附于运维末尾, 功能不丢)
    { path:'legs', name:'legs', meta:{title:'双腿监控',icon:'Connection',group:'运维'}, component:()=>import('../views/Legs.vue') },
    { path:'recon', name:'recon', meta:{title:'跨用户对账',icon:'Files',group:'运维'}, component:()=>import('../views/Recon.vue') },
    { path:'deals', name:'deals', meta:{title:'成交记录',icon:'List',group:'运维'}, component:()=>import('../views/Deals.vue') },
  ]}
]
export default createRouter({ history:createWebHistory(), routes })
