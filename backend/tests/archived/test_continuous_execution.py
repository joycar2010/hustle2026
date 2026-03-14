"""测试连续执行功能的诊断脚本"""
# -*- coding: utf-8 -*-
import asyncio
import sys
import os
import io

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_imports():
    """测试所有必要的导入"""
    print("=" * 60)
    print("测试1: 检查导入")
    print("=" * 60)

    try:
        from app.services.continuous_executor import ContinuousStrategyExecutor, LadderConfig
        print("✓ ContinuousStrategyExecutor 导入成功")
    except Exception as e:
        print(f"✗ ContinuousStrategyExecutor 导入失败: {e}")
        return False

    try:
        from app.services.execution_task_manager import execution_task_manager
        print("✓ execution_task_manager 导入成功")
    except Exception as e:
        print(f"✗ execution_task_manager 导入失败: {e}")
        return False

    try:
        from app.services.order_executor_v2 import OrderExecutorV2
        print("✓ OrderExecutorV2 导入成功")
    except Exception as e:
        print(f"✗ OrderExecutorV2 导入失败: {e}")
        return False

    return True

async def test_api_endpoint():
    """测试API端点是否存在"""
    print("\n" + "=" * 60)
    print("测试2: 检查API端点")
    print("=" * 60)

    try:
        from app.api.v1.strategies import router

        # 检查路由
        routes = [route.path for route in router.routes]

        if "/execute/{strategy_type}/continuous" in routes:
            print("✓ 连续开仓端点存在")
        else:
            print("✗ 连续开仓端点不存在")
            print(f"可用路由: {routes}")
            return False

        if "/close/{strategy_type}/continuous" in routes:
            print("✓ 连续平仓端点存在")
        else:
            print("✗ 连续平仓端点不存在")
            return False

        if "/execution/{task_id}/status" in routes:
            print("✓ 执行状态端点存在")
        else:
            print("✗ 执行状态端点不存在")
            return False

        if "/execution/{task_id}/stop" in routes:
            print("✓ 停止执行端点存在")
        else:
            print("✗ 停止执行端点不存在")
            return False

        return True
    except Exception as e:
        print(f"✗ API端点检查失败: {e}")
        return False

async def test_executor_creation():
    """测试执行器创建"""
    print("\n" + "=" * 60)
    print("测试3: 测试执行器创建")
    print("=" * 60)

    try:
        from app.services.continuous_executor import ContinuousStrategyExecutor
        from app.services.order_executor_v2 import order_executor_v2

        executor = ContinuousStrategyExecutor(
            strategy_id="test_strategy",
            order_executor=order_executor_v2,
            trigger_check_interval=0.05
        )

        print("✓ 执行器创建成功")
        print(f"  - Strategy ID: {executor.strategy_id}")
        print(f"  - Is Running: {executor.is_running}")
        print(f"  - Trigger Check Interval: {executor.trigger_check_interval}")

        return True
    except Exception as e:
        print(f"✗ 执行器创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("连续执行功能诊断")
    print("=" * 60 + "\n")

    results = []

    # 测试1: 导入
    results.append(await test_imports())

    # 测试2: API端点
    results.append(await test_api_endpoint())

    # 测试3: 执行器创建
    results.append(await test_executor_creation())

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    print(f"通过: {passed}/{total}")

    if passed == total:
        print("\n✓ 所有测试通过！连续执行功能应该可以正常工作。")
        print("\n如果仍然看不到挂单，请检查：")
        print("1. 后端服务是否正在运行")
        print("2. 前端是否正确连接到后端")
        print("3. 浏览器控制台是否有错误信息")
        print("4. 后端日志是否有错误信息")
    else:
        print("\n✗ 部分测试失败。请查看上面的错误信息。")

    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
