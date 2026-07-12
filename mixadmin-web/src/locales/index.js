import { createI18n } from 'vue-i18n'
const messages = {
  zh: { dashboard:'仪表盘', legs:'双腿监控', recon:'跨用户对账', deals:'成交记录', params:'参数下发', alerts:'告警中心',
        engine:'引擎状态', market:'市场', spread:'入场点差', single:'单腿状态', status:'配对状态', main:'主腿', hedge:'对冲腿',
        balance:'余额', equity:'净值', server:'服务器', account:'账户', refresh:'刷新', sync:'同步成交', light:'明亮', dark:'暗色' },
  en: { dashboard:'Dashboard', legs:'Legs', recon:'Reconcile', deals:'Deals', params:'Params', alerts:'Alerts',
        engine:'Engine', market:'Market', spread:'Entry Spread', single:'Single-leg', status:'Pair', main:'Main', hedge:'Hedge',
        balance:'Balance', equity:'Equity', server:'Server', account:'Account', refresh:'Refresh', sync:'Sync', light:'Light', dark:'Dark' }
}
export default createI18n({ legacy:false, locale:'zh', fallbackLocale:'en', messages })
