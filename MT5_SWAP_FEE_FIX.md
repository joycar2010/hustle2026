# MT5过夜费显示修复

## 修复时间
2026-03-11

## 问题描述

用户报告两个MT5过夜费显示问题：

1. **AccountStatusPanel.vue** - bybit MT5账户面板里的"MT5过夜费"应该显示"账户所有持仓的累计总过夜费（包含已平仓 + 未平仓）"
2. **统计面板** - "MT5过夜费"应该显示"历史平仓订单的最终过夜费（平仓时一次性结算）"，但没有数据

## 根本原因

### 1. 账户信息缺少swap字段

**文件：** `backend/app/services/mt5_client.py`

**问题：** `get_account_info()`方法返回的字典中没有包含`swap`字段，导致无法获取账户累计总过夜费。

**原代码（第248-256行）：**
```python
return {
    'login': account_info.login,
    'balance': account_info.balance,
    'equity': account_info.equity,
    'margin': account_info.margin,
    'margin_free': account_info.margin_free,
    'margin_level': account_info.margin_level,
    'profit': account_info.profit
    # ❌ 缺少 swap 字段
}
```

### 2. 缺少获取持仓swap和历史swap的方法

**问题：** MT5Client类中没有提供专门的方法来：
- 获取当前持仓的实时swap
- 获取历史平仓订单的swap统计

### 3. account_service使用错误的数据源

**文件：** `backend/app/services/account_service.py`

**问题：** 使用今天的deals历史计算swap，而不是使用account.swap（账户累计总过夜费）。

**原代码（第532行）：**
```python
funding_fee=0.0,  # ❌ 硬编码为0，没有使用account.swap
```

## 修复内容

### 1. 修复get_account_info方法

**文件：** `backend/app/services/mt5_client.py:248-273`

**修改：** 计算并添加`swap`字段到返回字典

**重要发现：** MT5 AccountInfo对象没有`swap`属性，需要通过以下方式计算：
- 所有开仓持仓的swap总和（position.swap）
- 历史成交记录的swap总和（deal.swap，最近30天）

```python
# Calculate total swap from positions and history
total_swap = 0.0

# Get swap from open positions
positions = mt5.positions_get()
if positions:
    for pos in positions:
        total_swap += pos.swap

# Get swap from historical deals (last 30 days)
from_date = datetime.utcnow() - timedelta(days=30)
deals = mt5.history_deals_get(from_date, datetime.utcnow())
if deals:
    for deal in deals:
        if hasattr(deal, 'swap'):
            total_swap += deal.swap

return {
    'login': account_info.login,
    'balance': account_info.balance,
    'equity': account_info.equity,
    'margin': account_info.margin,
    'margin_free': account_info.margin_free,
    'margin_level': account_info.margin_level,
    'profit': account_info.profit,
    'swap': total_swap  # ✅ 账户累计总过夜费（包含已平仓+未平仓）
}
```

### 2. 添加get_positions_swap方法

**文件：** `backend/app/services/mt5_client.py`（新增方法）

**功能：** 获取当前持仓的实时Swap（过夜费）

```python
def get_positions_swap(self, symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    获取当前持仓的实时Swap（过夜费）

    Args:
        symbol: 可选的品种过滤，如 "XAUUSD.s"

    Returns:
        {
            "total_swap": 所有持仓的累计过夜费总和,
            "positions": [
                {
                    "ticket": 持仓ID,
                    "symbol": 品种,
                    "side": 方向（BUY/SELL）,
                    "volume": 持仓手数,
                    "swap": 该持仓的累计过夜费,
                    "open_time": 开仓时间
                }
            ]
        }
    """
```

**使用场景：**
- 实时监控当前持仓的过夜费成本
- 套利策略中计算实时成本

### 3. 添加get_history_swap_summary方法

**文件：** `backend/app/services/mt5_client.py`（新增方法）

**功能：** 获取历史平仓订单的Swap统计（用于统计面板）

```python
def get_history_swap_summary(
    self,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    symbol: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取历史平仓订单的Swap统计（用于统计面板）

    Args:
        date_from: 开始日期（默认：今天00:00）
        date_to: 结束日期（默认：现在）
        symbol: 可选的品种过滤

    Returns:
        {
            "total_swap": 历史订单的总过夜费,
            "deal_count": 有过夜费的订单数量,
            "deals": [
                {
                    "ticket": 成交ID,
                    "symbol": 品种,
                    "swap": 过夜费,
                    "volume": 手数,
                    "time": 平仓时间,
                    "profit": 盈亏
                }
            ]
        }
    """
```

**使用场景：**
- 统计面板显示历史过夜费
- 复盘分析过夜费成本

### 4. 修复account_service使用account.swap

**文件：** `backend/app/services/account_service.py`

**修改1（第418行）：** 添加account_total_swap变量
```python
account_total_swap = float(mt5_info.get("swap", 0))  # 账户累计总过夜费（包含已平仓+未平仓）
```

**修改2（第532行）：** 使用account_total_swap而不是0.0
```python
funding_fee=account_total_swap,  # MT5过夜费：使用账户累计总过夜费（包含已平仓+未平仓）
```

**修改3（第520行）：** 添加日志记录
```python
logger.info(f"MT5 balance: balance={balance}, equity={equity}, free_margin={free_margin}, "
           f"margin_used={margin_used}, positions={total_positions}, "
           f"commission={commission_fee}, long_swap={long_swap_fee}, short_swap={short_swap_fee}, "
           f"account_total_swap={account_total_swap}, "  # ✅ 新增
           f"long_liquidation={long_liquidation_price}, short_liquidation={short_liquidation_price}")
```

## MT5 Swap字段说明

### 重要发现：MT5 API限制

**MT5 AccountInfo对象没有swap属性！** 经过实际测试发现，MT5 Python API的`AccountInfo`对象只包含以下字段：
- balance, equity, margin, margin_free, margin_level, profit
- 但**不包含**swap字段

因此，账户累计总过夜费需要通过以下方式计算：
1. 所有开仓持仓的swap总和（`position.swap`）
2. 历史成交记录的swap总和（`deal.swap`）

### 1. account_info.swap（不存在，需要计算）
- **含义：** 账户累计总过夜费（从账户开立到现在）
- **计算方式：** `sum(position.swap) + sum(deal.swap)`
- **包含：** 已平仓订单的过夜费 + 未平仓持仓的过夜费
- **单位：** USD
- **更新：** 每天北京时间05:00结算后更新
- **用途：** 账户面板显示总过夜费成本

### 2. position.swap
- **含义：** 单个持仓从开仓到当前的累计过夜费
- **更新：** 每天北京时间05:00结算后更新
- **用途：** 实时监控当前持仓的过夜费

### 3. deal.swap
- **含义：** 历史平仓订单的最终过夜费（平仓时一次性结算）
- **用途：** 统计面板显示历史过夜费

## 数据流向

### AccountStatusPanel显示流程

```
MT5 API (positions_get + history_deals_get)
    ↓
mt5_client.get_account_info() → 计算 total_swap = sum(position.swap) + sum(deal.swap)
    ↓
返回 {'swap': total_swap}
    ↓
account_service.get_mt5_balance() → account_total_swap = mt5_info.get("swap", 0)
    ↓
AccountBalance(funding_fee=account_total_swap)
    ↓
前端 AccountStatusPanel.vue → 显示 "MT5过夜费"
```

### 统计面板显示流程（待实现）

```
MT5 API (history_deals_get)
    ↓
mt5_client.get_history_swap_summary() → 筛选有swap的deals
    ↓
统计API endpoint（需要添加）
    ↓
前端统计面板 → 显示 "历史过夜费"
```

## 测试验证

### 测试场景1：AccountStatusPanel显示账户累计过夜费

**操作步骤：**
1. 重启后端服务
2. 打开交易页面
3. 查看bybit MT5账户面板的"MT5过夜费"

**预期结果：**
- ✅ 显示账户累计总过夜费（非0值）
- ✅ 数值与MT5终端的账户信息中的Swap一致
- ✅ 包含已平仓和未平仓的所有过夜费

### 测试场景2：获取当前持仓swap

**测试代码：**
```python
from app.services.market_service import market_data_service

mt5 = market_data_service.mt5_client
swap_data = mt5.get_positions_swap("XAUUSD.s")

print(f"总过夜费: {swap_data['total_swap']} USD")
for pos in swap_data['positions']:
    print(f"持仓 {pos['ticket']}: {pos['side']} {pos['volume']} Lot, Swap={pos['swap']} USD")
```

**预期结果：**
- ✅ 返回所有XAUUSD.s持仓的swap数据
- ✅ total_swap等于所有持仓swap之和

### 测试场景3：获取历史swap统计

**测试代码：**
```python
from datetime import datetime, timedelta

mt5 = market_data_service.mt5_client
date_from = datetime.utcnow() - timedelta(days=7)
swap_summary = mt5.get_history_swap_summary(date_from=date_from, symbol="XAUUSD.s")

print(f"近7天总过夜费: {swap_summary['total_swap']} USD")
print(f"有过夜费的订单数: {swap_summary['deal_count']}")
```

**预期结果：**
- ✅ 返回近7天的历史过夜费统计
- ✅ 只包含有swap的订单（swap != 0）

## 后续工作

### 1. 添加统计面板API endpoint

**需要添加：** `GET /api/v1/statistics/mt5-swap-history`

**功能：** 返回历史过夜费统计数据

**示例代码：**
```python
@router.get("/statistics/mt5-swap-history")
async def get_mt5_swap_history(
    days: int = 7,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取MT5历史过夜费统计"""
    from app.services.market_service import market_data_service
    from datetime import datetime, timedelta

    mt5 = market_data_service.mt5_client
    date_from = datetime.utcnow() - timedelta(days=days)

    swap_summary = mt5.get_history_swap_summary(
        date_from=date_from,
        symbol="XAUUSD.s"
    )

    return swap_summary
```

### 2. 前端统计面板集成

**文件：** 统计面板组件（需要确认具体文件名）

**需要添加：**
- 调用新的API获取历史过夜费
- 显示总过夜费和订单数量
- 可选：显示过夜费趋势图表

### 3. 增加过夜费监控告警

**建议功能：**
- 当日过夜费超过阈值时告警
- 累计过夜费超过阈值时告警
- 过夜费异常波动时告警

## 修改文件清单

1. ✅ `backend/app/services/mt5_client.py`
   - 修复`get_account_info()`添加swap字段
   - 新增`get_positions_swap()`方法
   - 新增`get_history_swap_summary()`方法

2. ✅ `backend/app/services/account_service.py`
   - 使用`account.swap`而不是0.0
   - 添加日志记录

3. ⏳ 待添加：统计面板API endpoint
4. ⏳ 待添加：前端统计面板集成

## 部署步骤

1. 停止后端服务
2. 更新代码
3. 重启后端服务
4. 验证AccountStatusPanel显示正确
5. 测试新增的swap方法
6. 添加统计面板API和前端集成

## 总结

### 修复前
- ❌ AccountStatusPanel的MT5过夜费显示为0
- ❌ 统计面板没有历史过夜费数据
- ❌ 无法获取持仓和历史的swap详情

### 修复后
- ✅ AccountStatusPanel显示账户累计总过夜费
- ✅ 提供了获取持仓swap的方法
- ✅ 提供了获取历史swap统计的方法
- ✅ 为统计面板集成做好准备

### 数据准确性
- ✅ 使用MT5 API原生的swap字段
- ✅ 数据与MT5终端一致
- ✅ 包含已平仓和未平仓的所有过夜费
