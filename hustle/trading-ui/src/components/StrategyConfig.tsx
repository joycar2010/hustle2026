import React, { useState } from 'react';

interface GridLevel {
  id: number;
  enabled: boolean;
  price: number;
  amount: number;
}

const StrategyConfig: React.FC = () => {
  const [gridLevels, setGridLevels] = useState<GridLevel[]>([
    { id: 1, enabled: true, price: 5000, amount: 0.01 },
    { id: 2, enabled: true, price: 5050, amount: 0.01 },
    { id: 3, enabled: false, price: 4950, amount: 0.01 },
  ]);
  
  const [mt5Enabled, setMt5Enabled] = useState(true);
  const [binanceEnabled, setBinanceEnabled] = useState(true);
  const [mt5OpenCount, setMt5OpenCount] = useState(0);
  const [mt5CloseCount, setMt5CloseCount] = useState(0);
  const [binanceOpenCount, setBinanceOpenCount] = useState(0);
  const [binanceCloseCount, setBinanceCloseCount] = useState(0);

  const handleAddLevel = () => {
    setGridLevels([...gridLevels, {
      id: gridLevels.length + 1,
      enabled: false,
      price: 5000,
      amount: 0.01
    }]);
  };

  const handleUpdateLevel = (id: number, field: keyof GridLevel, value: any) => {
    setGridLevels(gridLevels.map(level => 
      level.id === id ? { ...level, [field]: value } : level
    ));
  };

  const handleRemoveLevel = (id: number) => {
    setGridLevels(gridLevels.filter(level => level.id !== id));
  };

  return (
    <div className="bg-bg-secondary rounded-lg p-4 border border-border">
      <h3 className="text-text-primary font-semibold mb-3">策略配置</h3>
      
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <h4 className="text-text-secondary font-medium mb-2">自动交易控制</h4>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={mt5Enabled}
                  onChange={(e) => setMt5Enabled(e.target.checked)}
                  className="mr-2"
                />
                MT5 开仓(停)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="number"
                  value={mt5OpenCount}
                  onChange={(e) => setMt5OpenCount(parseInt(e.target.value) || 0)}
                  className="bg-bg-primary border border-border rounded px-2 py-1 text-text-primary w-16"
                />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={mt5Enabled}
                  onChange={(e) => setMt5Enabled(e.target.checked)}
                  className="mr-2"
                />
                MT5 平仓(停)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="number"
                  value={mt5CloseCount}
                  onChange={(e) => setMt5CloseCount(parseInt(e.target.value) || 0)}
                  className="bg-bg-primary border border-border rounded px-2 py-1 text-text-primary w-16"
                />
              </div>
            </div>
          </div>
        </div>
        
        <div>
          <h4 className="text-text-secondary font-medium mb-2">币安自动交易</h4>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={binanceEnabled}
                  onChange={(e) => setBinanceEnabled(e.target.checked)}
                  className="mr-2"
                />
                币安 开仓(停)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="number"
                  value={binanceOpenCount}
                  onChange={(e) => setBinanceOpenCount(parseInt(e.target.value) || 0)}
                  className="bg-bg-primary border border-border rounded px-2 py-1 text-text-primary w-16"
                />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={binanceEnabled}
                  onChange={(e) => setBinanceEnabled(e.target.checked)}
                  className="mr-2"
                />
                币安 平仓(停)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="number"
                  value={binanceCloseCount}
                  onChange={(e) => setBinanceCloseCount(parseInt(e.target.value) || 0)}
                  className="bg-bg-primary border border-border rounded px-2 py-1 text-text-primary w-16"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mb-4">
        <div className="flex justify-between items-center mb-2">
          <h4 className="text-text-secondary font-medium">网格交易设置</h4>
          <button
            onClick={handleAddLevel}
            className="bg-info hover:bg-opacity-80 text-white px-3 py-1 rounded text-sm"
          >
            添加档位
          </button>
        </div>
        
        <div className="space-y-2">
          {gridLevels.map((level) => (
            <div key={level.id} className="bg-bg-primary rounded p-3 border border-border">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={level.enabled}
                    onChange={(e) => handleUpdateLevel(level.id, 'enabled', e.target.checked)}
                  />
                  <input
                    type="number"
                    value={level.price}
                    onChange={(e) => handleUpdateLevel(level.id, 'price', parseFloat(e.target.value) || 0)}
                    className="w-20 bg-bg-secondary border border-border rounded px-2 py-1 text-text-primary"
                  />
                  <input
                    type="number"
                    value={level.amount}
                    onChange={(e) => handleUpdateLevel(level.id, 'amount', parseFloat(e.target.value) || 0)}
                    className="w-20 bg-bg-secondary border border-border rounded px-2 py-1 text-text-primary"
                  />
                </div>
                <button
                  onClick={() => handleRemoveLevel(level.id)}
                  className="text-danger hover:text-opacity-80"
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex justify-end space-x-2">
        <button className="bg-info hover:bg-opacity-80 text-white px-4 py-2 rounded font-medium">
          保存
        </button>
      </div>
    </div>
  );
};

export default StrategyConfig;