import React, { useState } from 'react';

interface TradingControlProps {
  onOpenLong: (amount: number) => void;
  onOpenShort: (amount: number) => void;
  onCloseLong: (amount: number) => void;
  onCloseShort: (amount: number) => void;
  mt5Position: number;
  binancePosition: number;
}

const TradingControl: React.FC<TradingControlProps> = ({
  onOpenLong,
  onOpenShort,
  onCloseLong,
  onCloseShort,
  mt5Position,
  binancePosition
}) => {
  const [amount, setAmount] = useState<number>(0.01);

  return (
    <div className="bg-bg-secondary rounded-lg p-4 border border-border">
      <h3 className="text-text-primary font-semibold mb-3">交易控制</h3>
      
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-text-secondary text-sm mb-1">MT5持仓</label>
          <div className={`text-xl font-mono ${mt5Position > 0 ? 'text-success' : mt5Position < 0 ? 'text-danger' : 'text-text-primary'}`}>
            {mt5Position.toFixed(2)}
          </div>
        </div>
        <div>
          <label className="block text-text-secondary text-sm mb-1">币安持仓</label>
          <div className={`text-xl font-mono ${binancePosition > 0 ? 'text-success' : binancePosition < 0 ? 'text-danger' : 'text-text-primary'}`}>
            {binancePosition.toFixed(2)}
          </div>
        </div>
      </div>

      <div className="mb-4">
        <label className="block text-text-secondary text-sm mb-1">交易数量</label>
        <div className="flex items-center">
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(parseFloat(e.target.value) || 0)}
            min="0.01"
            step="0.01"
            className="flex-1 bg-bg-primary border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:ring-1 focus:ring-info"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <button
            onClick={() => onOpenLong(amount)}
            className="w-full bg-success hover:bg-opacity-80 text-white py-2 rounded font-medium transition"
          >
            开多
          </button>
          <button
            onClick={() => onCloseLong(amount)}
            className="w-full bg-info hover:bg-opacity-80 text-white py-2 rounded font-medium transition"
          >
            平多
          </button>
        </div>
        <div className="space-y-2">
          <button
            onClick={() => onOpenShort(amount)}
            className="w-full bg-danger hover:bg-opacity-80 text-white py-2 rounded font-medium transition"
          >
            开空
          </button>
          <button
            onClick={() => onCloseShort(amount)}
            className="w-full bg-warning hover:bg-opacity-80 text-white py-2 rounded font-medium transition"
          >
            平空
          </button>
        </div>
      </div>
    </div>
  );
};

export default TradingControl;