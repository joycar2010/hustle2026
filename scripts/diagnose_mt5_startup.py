#!/usr/bin/env python3
"""
诊断 MT5 实例启动问题
检查桥接服务和 MT5 客户端的实际运行状态
"""
import requests
import json

def check_windows_agent():
    """检查 Windows Agent 状态"""
    print("=== Windows Agent 状态 ===")
    try:
        r = requests.get("http://172.31.14.113:9000/", timeout=5)
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"错误: {e}")

def check_instances():
    """检查所有实例"""
    print("\n=== MT5 实例列表 ===")
    try:
        r = requests.get("http://172.31.14.113:9000/instances", timeout=5)
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"错误: {e}")

def check_bridge_health(port):
    """检查桥接服务健康状态"""
    print(f"\n=== 桥接服务 {port} 健康检查 ===")
    try:
        r = requests.get(f"http://172.31.14.113:{port}/health", timeout=5)
        data = r.json()
        print(json.dumps(data, indent=2))

        # 分析状态
        if data.get("mt5") == True:
            print("✓ MT5 客户端已连接")
        else:
            print("✗ MT5 客户端未连接")

    except requests.exceptions.ConnectionError:
        print(f"✗ 桥接服务未运行（端口 {port} 无响应）")
    except Exception as e:
        print(f"错误: {e}")

def check_instance_status(port):
    """检查实例详细状态"""
    print(f"\n=== 实例 {port} 详细状态 ===")
    try:
        r = requests.get(f"http://172.31.14.113:9000/instances/{port}/status", timeout=5)
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    check_windows_agent()
    check_instances()

    # 检查端口 8001 和 8002
    for port in [8001, 8002]:
        check_bridge_health(port)
        check_instance_status(port)

    print("\n=== 诊断总结 ===")
    print("如果桥接服务运行但 MT5 未连接，可能原因：")
    print("1. MT5 terminal64.exe 进程未启动")
    print("2. MT5 启动失败（路径错误、权限问题）")
    print("3. MT5 启动但未能连接到桥接服务")
    print("4. 桥接服务的 MT5 初始化失败")
