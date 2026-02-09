import React, { useState, useEffect } from 'react';
import AccountInfo from './components/AccountInfo';
import TradingControl from './components/TradingControl';
import StrategyConfig from './components/StrategyConfig';
import PositionManager from './components/PositionManager';

function App() {
  // 状态管理
  const [mt5Connected, setMt5Connected] = useState(true);
  const [binanceConnected, setBinanceConnected] = useState(true);
  const [mt5Price, setMt5Price] = useState(5051.74);
  const [binancePrice, setBinancePrice] = useState(5051.73);
  const [mt5Spread, setMt5Spread] = useState(0.1);
  const [binanceSpread, setBinanceSpread] = useState(0.13);
  const [totalAssets, setTotalAssets] = useState(12.49);
  const [marginLevel, setMarginLevel] = useState(99);
  const [leverage, setLeverage] = useState(10);
  const [mt5Position, setMt5Position] = useState(0.02);
  const [binancePosition, setBinancePosition] = useState(0.01);
  const [websocketConnected, setWebsocketConnected] = useState(false);
  const [spread, setSpread] = useState(0);
  const [lastUpdate, setLastUpdate] = useState('');
  const [mt5Symbol, setMt5Symbol] = useState('XAUUSD');
  const [binanceSymbol, setBinanceSymbol] = useState('XAUUSDT');

  // WebSocket连接
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimeout: NodeJS.Timeout | null = null;
    const reconnectInterval = 5000; // 5秒后尝试重新连接
    
    const connectWebSocket = () => {
      console.log('尝试连接WebSocket...');
      ws = new WebSocket('ws://localhost:8000/ws/market-data');
      
      ws.onopen = () => {
        console.log('WebSocket连接成功');
        setWebsocketConnected(true);
        // 清除重新连接超时
        if (reconnectTimeout) {
          clearTimeout(reconnectTimeout);
          reconnectTimeout = null;
        }
      };
      
      ws.onmessage = (event) => {
        try {
          console.log('收到WebSocket消息:', event.data);
          const data = JSON.parse(event.data);
          console.log('解析后的消息:', data);
          if (data.type === 'market_data') {
            console.log('处理市场数据:', data);
            // 更新价格数据
            if (data.binance) {
              console.log('更新币安价格:', data.binance.last);
              setBinancePrice(data.binance.last);
              if (data.binance.ask && data.binance.bid) {
                setBinanceSpread(data.binance.ask - data.binance.bid);
              }
              if (data.binance.symbol) {
                setBinanceSymbol(data.binance.symbol);
              }
            }
            if (data.bybit) {
              console.log('更新MT5价格:', data.bybit.last);
              setMt5Price(data.bybit.last);
              if (data.bybit.ask && data.bybit.bid) {
                setMt5Spread(data.bybit.ask - data.bybit.bid);
              }
              if (data.bybit.symbol) {
                setMt5Symbol(data.bybit.symbol);
              }
            }
            // 更新点差
            if (data.spread !== undefined) {
              console.log('更新点差:', data.spread);
              setSpread(data.spread);
            }
            // 更新最后更新时间
            if (data.timestamp) {
              console.log('更新最后更新时间:', data.timestamp);
              setLastUpdate(data.timestamp);
            }
          }
        } catch (error) {
          console.error('WebSocket消息解析失败:', error);
          console.error('原始消息:', event.data);
        }
      };
      
      ws.onclose = () => {
        console.log('WebSocket连接关闭');
        setWebsocketConnected(false);
        // 尝试重新连接
        reconnectTimeout = setTimeout(connectWebSocket, reconnectInterval);
      };
      
      ws.onerror = (error) => {
        console.error('WebSocket错误:', error);
        setWebsocketConnected(false);
        // 尝试重新连接
        if (!reconnectTimeout) {
          reconnectTimeout = setTimeout(connectWebSocket, reconnectInterval);
        }
      };
    };
    
    // 初始连接
    connectWebSocket();
    
    return () => {
      // 清除WebSocket连接和重新连接超时
      if (ws) {
        ws.close();
      }
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
    };
  }, []);

  // 交易处理函数
  const handleOpenLong = (amount: number) => {
    setMt5Position(prev => prev + amount);
    console.log('开多', amount);
  };

  const handleCloseLong = (amount: number) => {
    setMt5Position(prev => Math.max(0, prev - amount));
    console.log('平多', amount);
  };

  const handleOpenShort = (amount: number) => {
    setMt5Position(prev => prev - amount);
    console.log('开空', amount);
  };

  const handleCloseShort = (amount: number) => {
    setMt5Position(prev => Math.min(0, prev + amount));
    console.log('平空', amount);
  };

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary p-4">
      {/* 顶部导航 */}
      <header className="mb-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold">Hustle 黄金套利系统</h1>
          <div className="flex items-center space-x-4">
            <button className="bg-info hover:bg-opacity-80 text-white px-4 py-2 rounded">
              点差图
            </button>
            <button className="bg-bg-secondary hover:bg-opacity-80 text-text-primary px-4 py-2 rounded border border-border">
              设置
            </button>
          </div>
        </div>
      </header>

      {/* 主要内容 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：账户信息和交易控制 */}
        <div className="space-y-6">
          <AccountInfo
            mt5Connected={mt5Connected}
            binanceConnected={binanceConnected}
            mt5Price={mt5Price}
            binancePrice={binancePrice}
            mt5Spread={mt5Spread}
            binanceSpread={binanceSpread}
            totalAssets={totalAssets}
            marginLevel={marginLevel}
            leverage={leverage}
            mt5Symbol={mt5Symbol}
            binanceSymbol={binanceSymbol}
            spread={spread}
            lastUpdate={lastUpdate}
          />
          <TradingControl
            onOpenLong={handleOpenLong}
            onCloseLong={handleCloseLong}
            onOpenShort={handleOpenShort}
            onCloseShort={handleCloseShort}
            mt5Position={mt5Position}
            binancePosition={binancePosition}
          />
        </div>

        {/* 中间：策略配置 */}
        <div>
          <StrategyConfig />
        </div>

        {/* 右侧：持仓管理 */}
        <div>
          <PositionManager />
        </div>
      </div>

      {/* 底部状态栏 */}
      <footer className="mt-8 pt-4 border-t border-border">
        <div className="flex justify-between text-text-secondary text-sm">
          <div>WebSocket: <span className={websocketConnected ? 'text-success' : 'text-danger'}>{websocketConnected ? '已连接' : '未连接'}</span></div>
          <div>库存在: {totalAssets}</div>
          <div>总资金: ${totalAssets.toFixed(2)}</div>
        </div>
      </footer>
    </div>
  );
}

export default App;
