// 飞书云文档小组件 - 策略监控面板
import { bitable } from '@lark-base-open/js-sdk';

// API配置
const API_BASE_URL = 'http://13.115.21.77:8000';
const WS_URL = 'ws://13.115.21.77:8000/ws';

// 全局状态
let marketChart = null;
let profitChart = null;
let wsConnection = null;
let strategies = [];
let marketDataHistory = [];
let profitHistory = [];

// 初始化
async function init() {
  try {
    // 初始化飞书SDK
    await bitable.bridge.getInstanceId();
    console.log('飞书SDK初始化成功');
  } catch (error) {
    console.log('非飞书环境，使用独立模式');
  }

  // 初始化图表
  initCharts();

  // 连接WebSocket
  connectWebSocket();

  // 获取初始数据
  await fetchStrategies();
  await fetchMarketData();

  // 定时刷新数据
  setInterval(fetchStrategies, 10000); // 每10秒刷新策略数据
}

// 初始化图表
function initCharts() {
  // 市场数据图表
  marketChart = echarts.init(document.getElementById('marketChart'));
  const marketOption = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e2329',
      borderColor: '#2b3139',
      textStyle: { color: '#ffffff' }
    },
    legend: {
      data: ['Binance', 'Bybit'],
      textStyle: { color: '#848e9c' },
      top: 0
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: [],
      axisLine: { lineStyle: { color: '#2b3139' } },
      axisLabel: { color: '#848e9c' }
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#2b3139' } },
      axisLabel: { color: '#848e9c' },
      splitLine: { lineStyle: { color: '#2b3139' } }
    },
    series: [
      {
        name: 'Binance',
        type: 'line',
        smooth: true,
        data: [],
        itemStyle: { color: '#f0b90b' },
        lineStyle: { width: 2 }
      },
      {
        name: 'Bybit',
        type: 'line',
        smooth: true,
        data: [],
        itemStyle: { color: '#ff9800' },
        lineStyle: { width: 2 }
      }
    ]
  };
  marketChart.setOption(marketOption);

  // 收益趋势图表
  profitChart = echarts.init(document.getElementById('profitChart'));
  const profitOption = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e2329',
      borderColor: '#2b3139',
      textStyle: { color: '#ffffff' }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: [],
      axisLine: { lineStyle: { color: '#2b3139' } },
      axisLabel: { color: '#848e9c' }
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#2b3139' } },
      axisLabel: { color: '#848e9c', formatter: '{value} USDT' },
      splitLine: { lineStyle: { color: '#2b3139' } }
    },
    series: [
      {
        name: '累计收益',
        type: 'line',
        smooth: true,
        data: [],
        itemStyle: { color: '#0ecb81' },
        lineStyle: { width: 2 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(14, 203, 129, 0.3)' },
              { offset: 1, color: 'rgba(14, 203, 129, 0.05)' }
            ]
          }
        }
      }
    ]
  };
  profitChart.setOption(profitOption);
}

// 连接WebSocket
function connectWebSocket() {
  try {
    wsConnection = new WebSocket(WS_URL);

    wsConnection.onopen = () => {
      console.log('WebSocket连接成功');
      updateConnectionStatus(true);
    };

    wsConnection.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
      } catch (error) {
        console.error('WebSocket消息解析失败:', error);
      }
    };

    wsConnection.onerror = (error) => {
      console.error('WebSocket错误:', error);
      updateConnectionStatus(false);
    };

    wsConnection.onclose = () => {
      console.log('WebSocket连接关闭，5秒后重连');
      updateConnectionStatus(false);
      setTimeout(connectWebSocket, 5000);
    };
  } catch (error) {
    console.error('WebSocket连接失败:', error);
    updateConnectionStatus(false);
  }
}

// 处理WebSocket消息
function handleWebSocketMessage(message) {
  if (message.type === 'market_data' && message.data) {
    updateMarketChart(message.data);
  } else if (message.type === 'account_balance' && message.data) {
    updateSummaryCards(message.data);
  }
}

// 更新连接状态
function updateConnectionStatus(connected) {
  const statusDot = document.getElementById('connectionStatus');
  const statusText = document.getElementById('statusText');

  if (connected) {
    statusDot.classList.add('connected');
    statusText.textContent = '实时连接';
  } else {
    statusDot.classList.remove('connected');
    statusText.textContent = '连接断开';
  }
}

// 获取策略列表
async function fetchStrategies() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/strategies`);
    if (!response.ok) throw new Error('获取策略失败');

    const data = await response.json();
    strategies = data;
    renderStrategies();
    updateSummaryFromStrategies();
  } catch (error) {
    console.error('获取策略失败:', error);
    showError('strategies');
  }
}

// 获取市场数据
async function fetchMarketData() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/market/current`);
    if (!response.ok) throw new Error('获取市场数据失败');

    const data = await response.json();
    updateMarketChart(data);
  } catch (error) {
    console.error('获取市场数据失败:', error);
  }
}

// 更新汇总卡片
function updateSummaryCards(data) {
  if (data.summary) {
    document.getElementById('todayProfit').textContent =
      `${(data.summary.daily_pnl || 0).toFixed(2)} USDT`;
  }
}

// 从策略数据更新汇总
function updateSummaryFromStrategies() {
  const runningCount = strategies.filter(s => s.status === 'running').length;
  const todayProfit = strategies.reduce((sum, s) => sum + (s.today_profit || 0), 0);

  document.getElementById('runningCount').textContent = runningCount;
  document.getElementById('todayProfit').textContent = `${todayProfit.toFixed(2)} USDT`;
  document.getElementById('totalStrategies').textContent = strategies.length;

  // 更新收益图表
  updateProfitChart();
}

// 更新市场数据图表
function updateMarketChart(data) {
  const now = new Date().toLocaleTimeString('zh-CN', { hour12: false });

  marketDataHistory.push({
    time: now,
    binance: data.binance_mid || 0,
    bybit: data.bybit_mid || 0
  });

  // 保留最近100个数据点
  if (marketDataHistory.length > 100) {
    marketDataHistory.shift();
  }

  const times = marketDataHistory.map(d => d.time);
  const binanceData = marketDataHistory.map(d => d.binance.toFixed(2));
  const bybitData = marketDataHistory.map(d => d.bybit.toFixed(2));

  marketChart.setOption({
    xAxis: { data: times },
    series: [
      { data: binanceData },
      { data: bybitData }
    ]
  });
}

// 更新收益图表
function updateProfitChart() {
  const now = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const totalProfit = strategies.reduce((sum, s) => sum + (s.total_profit || 0), 0);

  profitHistory.push({
    time: now,
    profit: totalProfit
  });

  // 保留最近50个数据点
  if (profitHistory.length > 50) {
    profitHistory.shift();
  }

  const times = profitHistory.map(d => d.time);
  const profits = profitHistory.map(d => d.profit.toFixed(2));

  profitChart.setOption({
    xAxis: { data: times },
    series: [{ data: profits }]
  });
}

// 渲染策略列表
function renderStrategies() {
  const container = document.getElementById('strategiesList');

  if (strategies.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
        <p>暂无策略数据</p>
      </div>
    `;
    return;
  }

  container.innerHTML = strategies.map(strategy => `
    <div class="strategy-item">
      <div class="strategy-header">
        <div class="strategy-name">${strategy.name || '未命名策略'}</div>
        <div class="strategy-status ${strategy.status || 'stopped'}">
          ${getStatusText(strategy.status)}
        </div>
      </div>
      <div class="strategy-details">
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">类型:</span>
          <span class="strategy-detail-value">${strategy.type === 'reverse' ? '反向套利' : '正向套利'}</span>
        </div>
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">M币:</span>
          <span class="strategy-detail-value">${strategy.m_coin || 0}</span>
        </div>
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">开仓:</span>
          <span class="strategy-detail-value ${strategy.opening_enabled ? 'success' : 'danger'}">
            ${strategy.opening_enabled ? '启用' : '禁用'}
          </span>
        </div>
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">平仓:</span>
          <span class="strategy-detail-value ${strategy.closing_enabled ? 'success' : 'danger'}">
            ${strategy.closing_enabled ? '启用' : '禁用'}
          </span>
        </div>
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">今日交易:</span>
          <span class="strategy-detail-value">${strategy.today_trades || 0}</span>
        </div>
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">今日收益:</span>
          <span class="strategy-detail-value ${(strategy.today_profit || 0) >= 0 ? 'success' : 'danger'}">
            ${(strategy.today_profit || 0).toFixed(2)} USDT
          </span>
        </div>
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">总收益:</span>
          <span class="strategy-detail-value ${(strategy.total_profit || 0) >= 0 ? 'success' : 'danger'}">
            ${(strategy.total_profit || 0).toFixed(2)} USDT
          </span>
        </div>
        <div class="strategy-detail-item">
          <span class="strategy-detail-label">梯度数:</span>
          <span class="strategy-detail-value">${strategy.ladders?.length || 0}</span>
        </div>
      </div>
    </div>
  `).join('');
}

// 获取状态文本
function getStatusText(status) {
  const statusMap = {
    'running': '运行中',
    'stopped': '已停止',
    'paused': '已暂停'
  };
  return statusMap[status] || '未知';
}

// 显示错误
function showError(type) {
  const container = document.getElementById(`${type}List`);
  if (container) {
    container.innerHTML = `
      <div class="empty-state">
        <p>加载失败，请稍后重试</p>
      </div>
    `;
  }
}

// 页面加载完成后初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// 窗口大小改变时重绘图表
window.addEventListener('resize', () => {
  if (marketChart) marketChart.resize();
  if (profitChart) profitChart.resize();
});
