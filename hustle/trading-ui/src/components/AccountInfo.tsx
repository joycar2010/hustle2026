import React from 'react';

interface AccountInfoProps {
  mt5Connected: boolean;
  binanceConnected: boolean;
  mt5Price: number;
  binancePrice: number;
  mt5Spread: number;
  binanceSpread: number;
  totalAssets: number;
  marginLevel: number;
  leverage: number;
  mt5Symbol: string;
  binanceSymbol: string;
  spread: number;
  lastUpdate: string;
}

const AccountInfo: React.FC<AccountInfoProps> = ({
  mt5Connected,
  binanceConnected,
  mt5Price,
  binancePrice,
  mt5Spread,
  binanceSpread,
  totalAssets,
  marginLevel,
  leverage,
  mt5Symbol,
  binanceSymbol,
  spread,
  lastUpdate
}) => {
  return (
    <div className="bg-bg-secondary rounded-lg p-4 border border-border">
      <h3 className="text-text-primary font-semibold mb-3">账户信息</h3>
      
      <div className="grid grid-cols-2 gap-4">
        {/* 交易所连接状态 */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-text-secondary">MT5 ({mt5Symbol})</span>
            <span className={`px-2 py-1 rounded ${mt5Connected ? 'bg-success text-white' : 'bg-danger text-white'}`}>
              {mt5Connected ? '已连接' : '未连接'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-text-secondary">币安 ({binanceSymbol})</span>
            <span className={`px-2 py-1 rounded ${binanceConnected ? 'bg-success text-white' : 'bg-danger text-white'}`}>
              {binanceConnected ? '已连接' : '未连接'}
            </span>
          </div>
        </div>

        {/* 价格信息 */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-text-secondary">MT5价格</span>
            <span className="text-text-primary font-mono">{mt5Price.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-text-secondary">币安价格</span>
            <span className="text-text-primary font-mono">{binancePrice.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-text-secondary">点差</span>
            <span className="text-info font-mono">{mt5Spread.toFixed(2)}/{binanceSpread.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-text-secondary">交易所点差</span>
            <span className="text-warning font-mono">{spread.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-text-secondary">最后更新</span>
            <span className="text-text-secondary text-xs">{lastUpdate ? new Date(lastUpdate).toLocaleString() : '-'}</span>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3">
        <div className="bg-bg-primary p-2 rounded">
          <div className="text-text-secondary text-xs">总资产</div>
          <div className="text-text-primary font-semibold">${totalAssets.toFixed(2)}</div>
        </div>
        <div className="bg-bg-primary p-2 rounded">
          <div className="text-text-secondary text-xs">爆仓率</div>
          <div className={`font-semibold ${marginLevel < 50 ? 'text-danger' : marginLevel < 100 ? 'text-warning' : 'text-success'}`}>
            {marginLevel}%
          </div>
        </div>
        <div className="bg-bg-primary p-2 rounded">
          <div className="text-text-secondary text-xs">杠杆</div>
          <div className="text-text-primary font-semibold">{leverage}x</div>
        </div>
      </div>
    </div>
  );
};

export default AccountInfo;