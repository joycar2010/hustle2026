# 正向+反向开仓套利策略优化实施计划

## 一、核心改动概述

### 1.1 文件结构调整
需要修改的核心文件：
- `backend/app/services/strategy_executor_v2.py` - 策略执行器主逻辑
- `backend/app/services/order_executor_v2.py` - 订单执行器
- `backend/app/services/trigger_manager.py` - 触发计数管理器
- `backend/app/services/position_manager.py` - 持仓管理器
- `backend/app/api/v1/trading.py` - API接口层

### 1.2 核心优化点
1. **开仓策略前置规则优化**
   - 正向开仓：Binance bid价开多 + Bybit开空
   - 反向开仓：Binance ask价开空 + Bybit开多
   - 单次下单限制、触发计数、挂单触发三个条件

2. **通用优化规则**
   - 手数精度：四舍五入至两位小数
   - 检测间隔：0.01秒，Bybit挂单后延迟0.1秒
   - 持仓校验：开仓前后二次校验
   - 阶梯切换：新增持仓校验

3. **场景处理优化**
   - 场景1：Binance未成交+点差不满足→立即撤单，计数归0
   - 场景2：Binance完全成交→Bybit立即挂单，重试4次
   - 场景3：Binance部分成交+点差不满足→撤单，按实际成交手数挂Bybit

4. **实盘开发优化**
   - 手动停止按钮
   - 最大运行时长限制
   - API调用失败重试3次
   - 价差判定优化
   - 日志记录优化

## 二、详细实施步骤

### 2.1 阶段一：基础配置和数据结构优化

#### 2.1.1 StrategyConfig 扩展
```python
@dataclass
class LadderConfig:
    enabled: bool
    opening_spread: float  # 开仓点差值
    closing_spread: float  # 平仓点差值（本次不涉及）
    total_qty: float  # 阶梯总手数
    opening_trigger_count: int  # 开仓触发计数阈值
    closing_trigger_count: int  # 平仓触发计数阈值（本次不涉及）
    single_order_qty: float  # 新增：单次下单手数

@dataclass
class StrategyConfig:
    strategy_id: int
    symbol: str
    strategy_type: str  # 'reverse' or 'forward'
    opening_m_coin: float  # 单次开仓最大手数
    closing_m_coin: float  # 单次平仓最大手数（本次不涉及）
    ladders: List[LadderConfig]
    max_runtime_hours: float = 24.0  # 新增：最大运行时长
    max_spread_threshold: float = 0.02  # 新增：价差过大阈值
    price_deviation_threshold: float = 0.01  # 新增：价格偏差阈值
```

#### 2.1.2 执行状态跟踪
```python
@dataclass
class ExecutionState:
    is_running: bool = False
    current_ladder_index: int = 0
    ladder_accumulated_qty: float = 0.0  # 当前阶梯累计成交手数
    start_time: datetime = None
    stop_requested: bool = False  # 新增：手动停止标志
```

### 2.2 阶段二：核心逻辑优化

#### 2.2.1 手数精度处理
```python
def round_quantity(qty: float) -> float:
    """四舍五入至两位小数"""
    return round(qty, 2)

def validate_quantity(qty: float, min_qty: float = 0.01) -> bool:
    """校验手数是否满足最小交易单位"""
    return qty >= min_qty
```

#### 2.2.2 持仓校验优化
```python
async def validate_position_before_opening(
    self,
    ladder_config: LadderConfig,
    current_position: float
) -> tuple[bool, str]:
    """
    开仓前持仓校验
    Returns: (is_valid, error_message)
    """
    if current_position > ladder_config.total_qty:
        return False, f"当前持仓{current_position}超过阶梯总手数{ladder_config.total_qty}"
    return True, ""

async def validate_position_after_opening(
    self,
    expected_qty: float,
    actual_position: float,
    tolerance: float = 0.01
) -> tuple[bool, str]:
    """
    开仓后持仓校验
    Returns: (is_valid, error_message)
    """
    deviation = abs(actual_position - expected_qty)
    if deviation > tolerance:
        return False, f"开仓持仓异常：预期{expected_qty}，实际{actual_position}"
    return True, ""
```

#### 2.2.3 阶梯切换优化
```python
async def can_switch_to_next_ladder(
    self,
    current_ladder_index: int,
    current_position: float
) -> tuple[bool, str]:
    """
    阶梯切换前校验
    Returns: (can_switch, error_message)
    """
    if current_ladder_index + 1 >= len(self.config.ladders):
        return False, "已是最后一个阶梯"

    next_ladder = self.config.ladders[current_ladder_index + 1]
    if current_position > next_ladder.total_qty:
        return False, f"仓位超限，阶梯切换失败：当前持仓{current_position}超过下阶梯总手数{next_ladder.total_qty}"

    return True, ""
```

### 2.3 阶段三：正向开仓策略实现

#### 2.3.1 正向开仓主流程
```python
async def execute_forward_opening(self) -> Dict:
    """
    正向开仓主流程

    流程：
    1. 初始化状态
    2. 循环检测条件2（触发计数）
    3. 满足条件后执行条件3（挂单）
    4. 处理成交场景
    5. 累计成交达标后切换阶梯或停止
    """
    self.execution_state.is_running = True
    self.execution_state.start_time = datetime.now()

    while self.execution_state.is_running:
        # 检查停止条件
        if await self._should_stop():
            break

        # 获取当前阶梯配置
        ladder = self.config.ladders[self.execution_state.current_ladder_index]

        # 检查阶梯是否完成
        if self.execution_state.ladder_accumulated_qty >= ladder.total_qty:
            # 尝试切换到下一阶梯
            can_switch, error_msg = await self.can_switch_to_next_ladder(
                self.execution_state.current_ladder_index,
                await self._get_current_position()
            )
            if not can_switch:
                logger.warning(f"阶梯切换失败: {error_msg}")
                break

            self.execution_state.current_ladder_index += 1
            self.execution_state.ladder_accumulated_qty = 0.0
            continue

        # 执行开仓逻辑
        await self._forward_opening_cycle(ladder)

        # 短暂延迟
        await asyncio.sleep(0.01)

    self.execution_state.is_running = False
    return {"status": "completed", "message": "正向开仓策略执行完成"}
```

#### 2.3.2 正向开仓单次循环
```python
async def _forward_opening_cycle(self, ladder: LadderConfig):
    """
    正向开仓单次循环

    步骤：
    1. 检测条件2（触发计数）
    2. 满足后执行条件3（挂单）
    3. 处理成交场景
    """
    # 步骤1：检测条件2 - 触发计数
    binance_long_spread = await self._get_binance_long_spread()

    if binance_long_spread >= ladder.opening_spread:
        # 触发计数+1
        self.trigger_manager.increment("forward_opening")

        # 检查是否达到触发阈值
        if self.trigger_manager.get_count("forward_opening") >= ladder.opening_trigger_count:
            # 重置计数
            self.trigger_manager.reset("forward_opening")

            # 步骤2：执行条件3 - 挂单
            await self._forward_opening_place_orders(ladder, binance_long_spread)
```

#### 2.3.3 正向开仓挂单处理
```python
async def _forward_opening_place_orders(
    self,
    ladder: LadderConfig,
    current_spread: float
):
    """
    正向开仓挂单处理

    流程：
    1. 计算下单手数
    2. Binance bid价挂多
    3. 监控成交状态
    4. 处理三种场景
    """
    # 计算下单手数
    remaining_qty = ladder.total_qty - self.execution_state.ladder_accumulated_qty
    order_qty = min(ladder.single_order_qty, remaining_qty)
    order_qty = round_quantity(order_qty)

    # 校验手数
    if not validate_quantity(order_qty):
        logger.warning(f"手数不足最小交易单位: {order_qty}")
        return

    # 持仓前校验
    current_position = await self._get_current_position()
    is_valid, error_msg = await self.validate_position_before_opening(
        ladder, current_position
    )
    if not is_valid:
        logger.error(f"持仓校验失败: {error_msg}")
        await self._push_status_update("error", error_msg)
        self.execution_state.stop_requested = True
        return

    # Binance bid价挂多
    binance_order = await self._place_binance_long_order(order_qty)
    if not binance_order:
        logger.error("Binance挂单失败")
        return

    # 监控成交状态
    await self._monitor_forward_opening_execution(
        binance_order, order_qty, ladder, current_spread
    )
```

#### 2.3.4 正向开仓成交监控
```python
async def _monitor_forward_opening_execution(
    self,
    binance_order: Dict,
    order_qty: float,
    ladder: LadderConfig,
    initial_spread: float
):
    """
    正向开仓成交监控

    处理三种场景：
    1. Binance未成交+点差不满足
    2. Binance完全成交
    3. Binance部分成交+点差不满足
    """
    check_interval = 0.01  # 检测间隔0.01秒
    max_wait_time = 10.0  # 最大等待时间10秒
    elapsed_time = 0.0

    while elapsed_time < max_wait_time:
        # 获取Binance订单状态
        binance_status = await self._get_order_status(
            "binance", binance_order["order_id"]
        )

        # 获取当前点差
        current_spread = await self._get_binance_long_spread()

        # 场景1：Binance未成交+点差不满足
        if binance_status["filled_qty"] == 0 and current_spread < ladder.opening_spread:
            logger.info("场景1：Binance未成交且点差不满足，立即撤单")
            await self._cancel_order("binance", binance_order["order_id"])
            self.trigger_manager.reset("forward_opening")
            return

        # 场景2：Binance完全成交
        if binance_status["filled_qty"] >= order_qty:
            logger.info(f"场景2：Binance完全成交 {binance_status['filled_qty']}手")
            await self._handle_binance_filled(
                binance_status["filled_qty"], ladder, current_spread
            )
            return

        # 场景3：Binance部分成交+点差不满足
        if binance_status["filled_qty"] > 0 and current_spread < ladder.opening_spread:
            logger.info(f"场景3：Binance部分成交 {binance_status['filled_qty']}手且点差不满足")
            await self._cancel_order("binance", binance_order["order_id"])

            # 累计已成交手数
            self.execution_state.ladder_accumulated_qty += binance_status["filled_qty"]

            # Bybit按实际成交手数挂单
            await self._handle_binance_filled(
                binance_status["filled_qty"], ladder, current_spread
            )
            return

        await asyncio.sleep(check_interval)
        elapsed_time += check_interval
```

#### 2.3.5 Binance成交后Bybit挂单
```python
async def _handle_binance_filled(
    self,
    filled_qty: float,
    ladder: LadderConfig,
    current_spread: float
):
    """
    Binance成交后Bybit挂单处理

    流程：
    1. Bybit立即以bid价挂空
    2. 重试逻辑：前3次直接重试，第4次校验价差
    """
    filled_qty = round_quantity(filled_qty)

    # Bybit挂空（bid价）
    retry_count = 0
    max_retries = 4

    while retry_count < max_retries:
        # 延迟0.1秒后检测
        await asyncio.sleep(0.1)

        # Bybit挂单
        bybit_order = await self._place_bybit_short_order(filled_qty)
        if not bybit_order:
            logger.error(f"Bybit挂单失败，重试 {retry_count + 1}/{max_retries}")
            retry_count += 1
            continue

        # 检测成交
        bybit_status = await self._get_order_status(
            "bybit", bybit_order["order_id"]
        )

        if bybit_status["filled_qty"] >= filled_qty:
            logger.info(f"Bybit成交成功 {bybit_status['filled_qty']}手")

            # 累计成交手数
            self.execution_state.ladder_accumulated_qty += filled_qty

            # 持仓后校验
            current_position = await self._get_current_position()
            is_valid, error_msg = await self.validate_position_after_opening(
                self.execution_state.ladder_accumulated_qty,
                current_position
            )
            if not is_valid:
                logger.error(f"持仓校验失败: {error_msg}")
                await self._push_status_update("error", error_msg)
                self.execution_state.stop_requested = True

            return

        # 未成交，撤单重试
        await self._cancel_order("bybit", bybit_order["order_id"])
        retry_count += 1

        # 第4次重试前校验价差
        if retry_count == 3:
            current_spread = await self._get_binance_long_spread()
            if abs(current_spread - ladder.opening_spread) > self.config.max_spread_threshold:
                logger.warning(f"价差超限，开仓重试失败: 当前价差{current_spread}")
                await self._push_status_update("warning", "价差超限，开仓重试失败")
                return

    logger.error(f"Bybit挂单重试{max_retries}次后仍失败")
    await self._push_status_update("error", "Bybit挂单重试失败")
```

### 2.4 阶段四：反向开仓策略实现

反向开仓策略与正向开仓逻辑类似，主要区别：
1. Binance使用ask价开空（而非bid价开多）
2. Bybit使用ask价开多（而非bid价开空）
3. 点差计算使用Bybit做多点差值

实现方法：
- 复制正向开仓的所有方法
- 修改方法名：`_forward_` → `_reverse_`
- 修改挂单方向和价格类型
- 修改点差计算逻辑

### 2.5 阶段五：辅助功能实现

#### 2.5.1 停止控制
```python
async def _should_stop(self) -> bool:
    """检查是否应该停止策略"""
    # 手动停止
    if self.execution_state.stop_requested:
        return True

    # 超时停止
    if self.execution_state.start_time:
        elapsed_hours = (datetime.now() - self.execution_state.start_time).total_seconds() / 3600
        if elapsed_hours >= self.config.max_runtime_hours:
            logger.warning(f"策略运行超时: {elapsed_hours}小时")
            return True

    return False

async def request_stop(self):
    """请求停止策略"""
    self.execution_state.stop_requested = True
    logger.info("收到停止请求")
```

#### 2.5.2 API调用重试
```python
async def _api_call_with_retry(
    self,
    func,
    *args,
    max_retries: int = 3,
    **kwargs
) -> Optional[Dict]:
    """API调用失败自动重试"""
    for attempt in range(max_retries):
        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                await self._push_status_update("error", f"API调用失败: {str(e)}")
                return None
            await asyncio.sleep(0.5)
    return None
```

#### 2.5.3 日志记录优化
```python
def _log_opening_operation(
    self,
    operation: str,
    account: str,
    qty: float,
    spread: float,
    trigger_condition: str,
    result: str
):
    """记录开仓操作日志"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "strategy_id": self.config.strategy_id,
        "operation": operation,
        "account": account,
        "qty": qty,
        "spread": spread,
        "trigger_condition": trigger_condition,
        "result": result
    }
    logger.info(f"开仓操作: {log_entry}")
```

## 三、API接口调整

### 3.1 新增停止接口
```python
@router.post("/strategies/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """手动停止策略"""
    # 调用strategy_manager停止策略
    result = await strategy_manager.stop_strategy(strategy_id, db)
    return {"success": result}
```

### 3.2 状态查询接口优化
```python
@router.get("/strategies/{strategy_id}/status")
async def get_strategy_status(
    strategy_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取策略执行状态"""
    status = await strategy_manager.get_strategy_status(strategy_id)
    return {
        "is_running": status.is_running,
        "current_ladder": status.current_ladder_index,
        "accumulated_qty": status.ladder_accumulated_qty,
        "elapsed_time": status.elapsed_time,
        "can_stop": status.is_running
    }
```

## 四、前端调整

### 4.1 策略控制按钮
在StrategyPanel.vue中添加：
- 停止按钮（仅在策略运行时显示）
- 运行时长显示
- 当前阶梯和累计成交显示

### 4.2 状态推送
通过WebSocket实时推送：
- 策略执行状态
- 当前阶梯信息
- 累计成交手数
- 错误和警告信息

## 五、测试计划

### 5.1 单元测试
- 手数精度处理
- 持仓校验逻辑
- 阶梯切换逻辑
- API重试机制

### 5.2 集成测试
- 正向开仓完整流程
- 反向开仓完整流程
- 三种成交场景
- 停止控制

### 5.3 压力测试
- 高频触发场景
- 网络延迟场景
- API失败场景

## 六、部署计划

### 6.1 数据库迁移
如需新增字段，创建迁移脚本

### 6.2 配置更新
更新策略配置参数

### 6.3 灰度发布
先在测试环境验证，再逐步推广到生产环境

## 七、风险控制

### 7.1 回滚方案
保留旧版本代码，出现问题立即回滚

### 7.2 监控告警
- 策略执行异常告警
- 持仓异常告警
- API调用失败告警

### 7.3 资金安全
- 严格的持仓校验
- 价差超限拦截
- 手动停止机制

## 八、后续优化

### 8.1 性能优化
- 减少API调用频率
- 优化数据库查询
- 缓存市场数据

### 8.2 功能扩展
- 支持更多交易对
- 支持自定义策略参数
- 支持策略回测

### 8.3 用户体验
- 更详细的执行日志
- 更直观的状态展示
- 更灵活的控制选项
