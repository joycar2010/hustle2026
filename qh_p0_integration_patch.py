"""
P0.1 集成补丁 - 为cmd_open_pair和cmd_close_pair添加全链路追踪
在现有代码中插入追踪点,最小化侵入性
"""

# 这个补丁文件展示需要在app.py中添加的代码片段

# ============================================
# 1. 在app.py顶部添加导入
# ============================================
"""
from qh_command_tracer import (
    init_tracer,
    get_tracer,
    CommandType,
    CommandStatus,
    TraceTimestamp
)

# 在初始化Redis后立即初始化tracer
init_tracer(R)
"""

# ============================================
# 2. cmd_open_pair入口添加追踪 (约在6415行)
# ============================================
"""
@app.post("/api/cmd/open_pair", dependencies=[Depends(require_license)])
async def cmd_open_pair(r: OpenPairReq):
    # === P0.1: 创建command追踪 ===
    tracer = get_tracer()
    command_id = tracer.create_command(
        cmd_type=CommandType.OPEN_PAIR,
        username=r.username,
        symbol=r.symbol,
        direction=r.direction,
        metadata={
            "slots": r.slots,
            "slot": r.slot,
            "license_key": r.license_key[:8] + "..." if r.license_key else None
        }
    )

    try:
        actor = _actor(r.license_key)
        if r.direction not in ("reverse", "forward"):
            raise HTTPException(400, "direction 必须为 reverse 或 forward")
        if not r.confirm:
            raise HTTPException(400, "二次确认未通过(confirm=true)")

        # === P0.1: 记录前置检查开始 ===
        tracer.record_timestamp(command_id, TraceTimestamp.PREFLIGHT_START)

        _maint_block_trading()
        await _conn_gate_exec()
        await _exec_owner_gate(r.username)

        t = _load_tmpl(r.username, r.symbol)
        if not t:
            raise HTTPException(404, "参数模板未找到")

        # ... 中间的参数计算代码保持不变 ...

        # === P0.1: 前置检查完成 ===
        tracer.record_timestamp(command_id, TraceTimestamp.PREFLIGHT_DONE)
        tracer.update_status(command_id, CommandStatus.PREFLIGHT)

        # ... 继续原有的开仓逻辑 ...
        # 在调用Bridge前后记录时间戳

    except HTTPException as he:
        # === P0.1: 记录失败 ===
        tracer.update_status(command_id, CommandStatus.FAILED)
        tracer.update_field(command_id, "failure_reason", str(he.detail))
        raise
    except Exception as e:
        # === P0.1: 记录异常 ===
        tracer.update_status(command_id, CommandStatus.FAILED)
        tracer.update_field(command_id, "failure_reason", str(e))
        raise
    finally:
        # === P0.1: 记录HTTP响应时间 ===
        tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
"""

# ============================================
# 3. 在调用Bridge order_send时添加追踪
# ============================================
"""
# 主腿order_send (假设在某个helper函数中)
async def _send_main_order(command_id, order_params):
    tracer = get_tracer()

    # 记录发送到Bridge的时间
    tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_SENT_MAIN)

    try:
        result = await main_bridge.order_send(order_params)

        # 记录收到Bridge响应
        tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_MAIN)

        # 记录ticket
        if result.get("retcode") == 10009:  # SUCCESS
            tracer.update_field(command_id, "main_ticket", result.get("order"))
            tracer.update_field(command_id, "main_deal", result.get("deal"))
            tracer.update_field(command_id, "main_retcode", result.get("retcode"))

        return result

    except asyncio.TimeoutError:
        # === P0.2: 超时处理 ===
        tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_MAIN)
        tracer.update_status(command_id, CommandStatus.UNKNOWN)
        raise
    except Exception as e:
        tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_MAIN)
        tracer.update_field(command_id, "main_error", str(e))
        raise

# 对冲腿order_send (类似逻辑)
async def _send_hedge_order(command_id, order_params):
    tracer = get_tracer()

    tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_SENT_HEDGE)

    try:
        result = await hedge_bridge.order_send(order_params)
        tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_HEDGE)

        if result.get("retcode") == 10009:
            tracer.update_field(command_id, "hedge_ticket", result.get("order"))
            tracer.update_field(command_id, "hedge_deal", result.get("deal"))
            tracer.update_field(command_id, "hedge_retcode", result.get("retcode"))

        return result

    except asyncio.TimeoutError:
        tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_HEDGE)
        tracer.update_status(command_id, CommandStatus.UNKNOWN)
        raise
    except Exception as e:
        tracer.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_HEDGE)
        tracer.update_field(command_id, "hedge_error", str(e))
        raise
"""

# ============================================
# 4. P0.2 修改返回逻辑,支持202 UNKNOWN
# ============================================
"""
# 在cmd_open_pair的最后返回前
if main_result.get("retcode") == 10009 and hedge_result.get("retcode") == 10009:
    # 成功
    tracer.update_status(command_id, CommandStatus.COMPLETED)
    return {
        "ok": True,
        "command_id": command_id,
        "demo": False,
        "main_ticket": main_result["order"],
        "hedge_ticket": hedge_result["order"],
        ...
    }
else:
    # 某腿超时或未知
    if tracer.get_command(command_id).get("status") == CommandStatus.UNKNOWN.value:
        # 返回202而非409
        return JSONResponse(
            status_code=202,
            content={
                "status": "UNKNOWN",
                "command_id": command_id,
                "msg": "订单提交超时,正在后台对账确认状态,请勿重复提交",
                "check_url": f"/api/command/{command_id}"
            }
        )
    else:
        # 明确失败
        tracer.update_status(command_id, CommandStatus.FAILED)
        return {"ok": False, "command_id": command_id, ...}
"""

# ============================================
# 5. 添加查询命令状态的端点
# ============================================
"""
@app.get("/api/command/{command_id}")
async def get_command_status(command_id: str):
    '''查询订单命令状态'''
    tracer = get_tracer()
    cmd = tracer.get_command(command_id)

    if not cmd:
        raise HTTPException(404, "命令不存在")

    # 计算延迟
    latencies = tracer.calculate_latencies(command_id)

    return {
        "command_id": command_id,
        "type": cmd.get("type"),
        "status": cmd.get("status"),
        "username": cmd.get("username"),
        "symbol": cmd.get("symbol"),
        "direction": cmd.get("direction"),
        "main_ticket": cmd.get("main_ticket"),
        "hedge_ticket": cmd.get("hedge_ticket"),
        "created_at": cmd.get(TraceTimestamp.API_RECEIVED),
        "latencies": latencies,
        "failure_reason": cmd.get("failure_reason"),
        "exposure_reason": cmd.get("exposure_reason"),
    }
"""

# ============================================
# 6. 启动对账Worker
# ============================================
"""
# 在app.py的启动事件中
from qh_reconciliation_worker import ReconciliationWorker

reconciliation_worker = None

@app.on_event("startup")
async def startup_event():
    global reconciliation_worker

    # 初始化tracer
    init_tracer(R)

    # 启动对账Worker
    reconciliation_worker = ReconciliationWorker(
        redis_client=R,
        db_session=SessionLocal(),
        bridge_main_url=os.environ.get("QH_BRIDGE_URL"),
        bridge_hedge_url=os.environ.get("QH_HEDGE_URL"),
        bridge_api_key=os.environ.get("QH_BRIDGE_KEY")
    )

    # 在后台运行
    asyncio.create_task(reconciliation_worker.start())

    logger.info("ReconciliationWorker started in background")

@app.on_event("shutdown")
async def shutdown_event():
    global reconciliation_worker
    if reconciliation_worker:
        await reconciliation_worker.stop()
"""

# ============================================
# 7. 实际部署步骤
# ============================================
"""
部署步骤:

1. 上传三个文件到QH服务器:
   - qh_command_tracer.py
   - qh_reconciliation_worker.py
   - qh_p0_integration_patch.py (本文件)

2. 备份当前app.py:
   cp /opt/quanthedge/app.py /opt/quanthedge/app.py.bak_p0_$(date +%Y%m%d_%H%M%S)

3. 编辑app.py,按照本文件的注释插入代码:
   - 添加import
   - 在cmd_open_pair入口添加command_id创建
   - 在各关键点添加timestamp记录
   - 修改返回逻辑支持202 UNKNOWN
   - 添加/api/command/{command_id}端点
   - 修改startup事件启动Worker

4. 重启QH服务:
   # 获取环境变量
   cat /proc/$(pgrep -f 'uvicorn.*8090' | head -1)/environ | tr '\\0' '\\n' > /tmp/qh_env.txt

   # 停止旧进程
   sudo kill $(pgrep -f 'uvicorn.*8090')

   # 启动新进程
   cd /opt/quanthedge
   export $(cat /tmp/qh_env.txt | xargs)
   nohup /opt/quanthedge/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8090 --workers 1 > /tmp/qh.log 2>&1 &

5. 验证:
   # 测试开仓并查询状态
   curl -X POST http://127.0.0.1:8090/api/cmd/open_pair ...
   # 返回中会有command_id

   curl http://127.0.0.1:8090/api/command/{command_id}
   # 应该能看到完整的追踪信息

   # 检查Redis中的追踪数据
   redis-cli -n 3 KEYS "qh:command:*"
   redis-cli -n 3 HGETALL "qh:command:open_no123_XAUUSD_..."

6. 监控对账Worker日志:
   tail -f /tmp/qh.log | grep -i "reconcil"
"""

print(__doc__)
