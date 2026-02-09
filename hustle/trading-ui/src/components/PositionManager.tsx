import React from 'react';

interface Position {
  id: number;
  time: string;
  symbol: string;
  side: 'long' | 'short';
  amount: number;
  price: number;
  pnl: number;
  status: 'open' | 'closed';
}

const PositionManager: React.FC = () => {
  const positions: Position[] = [
    {
      id: 1,
      time: '10:00',
      symbol: 'PAXG',
      side: 'long',
      amount: 0.005,
      price: 5010,
      pnl: 0.12,
      status: 'open'
    },
    {
      id: 2,
      time: '09:30',
      symbol: 'XAU',
      side: 'short',
      amount: 0.01,
      price: 5020,
      pnl: -0.05,
      status: 'open'
    },
    {
      id: 3,
      time: '09:00',
      symbol: 'PAXG',
      side: 'long',
      amount: 0.005,
      price: 5000,
      pnl: 0.08,
      status: 'closed'
    }
  ];

  const inventory = {
    PAXG: 0.005,
    XAU: 0
  };

  const totalPnL = positions.reduce((sum, pos) => sum + pos.pnl, 0);

  return (
    <div className="bg-bg-secondary rounded-lg p-4 border border-border">
      <h3 className="text-text-primary font-semibold mb-3">持仓管理</h3>
      
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="bg-bg-primary rounded p-3">
          <h4 className="text-text-secondary font-medium mb-2">库存</h4>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span>PAXG:</span>
              <span className="font-mono">{inventory.PAXG.toFixed(3)}</span>
            </div>
            <div className="flex justify-between">
              <span>XAU:</span>
              <span className="font-mono">{inventory.XAU.toFixed(3)}</span>
            </div>
          </div>
        </div>
        
        <div className="bg-bg-primary rounded p-3">
          <h4 className="text-text-secondary font-medium mb-2">资产</h4>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span>总盈亏:</span>
              <span className={`font-mono ${totalPnL >= 0 ? 'text-success' : 'text-danger'}`}>
                ${totalPnL.toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between">
              <span>总开仓:</span>
              <span className="font-mono">2</span>
            </div>
          </div>
        </div>
      </div>

      <div className="mb-3">
        <h4 className="text-text-secondary font-medium mb-2">持仓列表</h4>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left text-text-secondary py-2 px-3">时间</th>
                <th className="text-left text-text-secondary py-2 px-3">PAXG</th>
                <th className="text-left text-text-secondary py-2 px-3">XAU</th>
                <th className="text-left text-text-secondary py-2 px-3">变</th>
                <th className="text-left text-text-secondary py-2 px-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr key={position.id} className="border-b border-border">
                  <td className="py-2 px-3 text-text-primary">{position.time}</td>
                  <td className="py-2 px-3 font-mono">{position.amount.toFixed(3)}</td>
                  <td className="py-2 px-3 font-mono">0</td>
                  <td className={`py-2 px-3 font-mono ${position.pnl >= 0 ? 'text-success' : 'text-danger'}`}>
                    {position.pnl.toFixed(2)}
                  </td>
                  <td className="py-2 px-3">
                    <span className={`px-2 py-1 rounded text-xs ${position.status === 'open' ? 'bg-success' : 'bg-gray-500'} text-white`}>
                      {position.status === 'open' ? '开' : '平'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex justify-between items-center">
        <div className="flex space-x-3">
          <span className="text-text-secondary">M币:</span>
          <select className="bg-bg-primary border border-border rounded px-2 py-1 text-text-primary">
            <option>5</option>
            <option>10</option>
            <option>20</option>
          </select>
        </div>
        <div className="flex space-x-3">
          <span className="text-text-secondary">币M:</span>
          <select className="bg-bg-primary border border-border rounded px-2 py-1 text-text-primary">
            <option>10</option>
            <option>20</option>
            <option>50</option>
          </select>
        </div>
      </div>
    </div>
  );
};

export default PositionManager;