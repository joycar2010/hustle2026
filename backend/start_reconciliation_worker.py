#!/usr/bin/env python3
"""
QH对账Worker独立启动脚本
用于对账UNKNOWN/RECONCILING状态的订单
"""
import asyncio
import os
import sys
import redis
import logging

# 添加当前目录到Python路径
sys.path.insert(0, '/opt/quanthedge')

from qh_reconciliation_worker import ReconciliationWorker
from qh_command_tracer import init_tracer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)


async def main():
    logger.info("启动QH对账Worker...")

    # 初始化Redis
    redis_client = redis.Redis(
        host="127.0.0.1",
        port=6379,
        db=3,
        decode_responses=True
    )

    # 测试Redis连接
    try:
        redis_client.ping()
        logger.info("Redis连接成功")
    except Exception as e:
        logger.error(f"Redis连接失败: {e}")
        return

    # 初始化tracer
    init_tracer(redis_client)
    logger.info("追踪器初始化完成")

    # 从环境变量读取配置
    bridge_main_url = os.environ.get("QH_BRIDGE_URL", "http://172.31.5.62:8041")
    bridge_hedge_url = os.environ.get("QH_HEDGE_URL", "http://172.31.5.62:8042")
    bridge_api_key = os.environ.get("QH_BRIDGE_KEY", "7af2221c27241dd524273d2752772aa43e6b18c0187dffbf")

    logger.info(f"配置: Main={bridge_main_url}, Hedge={bridge_hedge_url}")

    # 创建Worker
    worker = ReconciliationWorker(
        redis_client=redis_client,
        db_session=None,  # 暂不需要DB
        bridge_main_url=bridge_main_url,
        bridge_hedge_url=bridge_hedge_url,
        bridge_api_key=bridge_api_key
    )

    # 启动Worker (会阻塞直到停止)
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号,停止Worker...")
        await worker.stop()
    except Exception as e:
        logger.error(f"Worker异常退出: {e}", exc_info=True)
        await worker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        sys.exit(1)
