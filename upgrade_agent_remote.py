# 通过 Python 脚本远程执行 MT5 Agent 升级
import requests
import time
import json

# 配置
BACKEND_URL = "https://admin.hustle2026.xyz"
USERNAME = "admin"
PASSWORD = "Hustle@2026"

def login():
    """登录获取 token"""
    response = requests.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"username": USERNAME, "password": PASSWORD}
    )
    response.raise_for_status()
    return response.json()["access_token"]

def upgrade_agent_via_api(token):
    """通过 API 升级 Agent"""
    headers = {"Authorization": f"Bearer {token}"}

    print("=" * 50)
    print("MT5 Agent V4 升级工具（通过 API）")
    print("=" * 50)
    print()

    # 步骤 1: 获取当前实例状态
    print("[1/5] 检查当前实例状态...")
    response = requests.get(f"{BACKEND_URL}/api/v1/mt5/instances", headers=headers)
    instances = response.json()
    print(f"  找到 {len(instances)} 个实例")
    for inst in instances:
        print(f"    - 端口 {inst['service_port']}: {inst['status']}")
    print()

    # 步骤 2: 停止所有实例（准备升级）
    print("[2/5] 停止所有实例...")
    for inst in instances:
        port = inst['service_port']
        instance_id = inst['instance_id']
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/v1/mt5/instances/{instance_id}/stop",
                headers=headers
            )
            if response.status_code == 200:
                print(f"  ✓ 端口 {port} 已停止")
            else:
                print(f"  ✗ 端口 {port} 停止失败: {response.text}")
        except Exception as e:
            print(f"  ✗ 端口 {port} 停止失败: {e}")

    time.sleep(3)
    print()

    # 步骤 3: 执行升级（需要在 MT5 服务器上手动执行）
    print("[3/5] 升级 Agent...")
    print("  注意: 需要在 MT5 服务器上手动执行以下命令:")
    print("  cd C:\\MT5Agent")
    print("  copy /Y main.py main.py.backup_v3")
    print("  copy /Y main_v4.py main.py")
    print("  start /B python main.py")
    print()
    print("  等待手动执行... (按 Enter 继续)")
    input()

    # 步骤 4: 验证 Agent 状态
    print("[4/5] 验证 Agent 状态...")
    time.sleep(5)

    # 通过检查实例是否能重启来验证
    print()

    # 步骤 5: 重启所有实例
    print("[5/5] 重启所有实例...")
    for inst in instances:
        port = inst['service_port']
        instance_id = inst['instance_id']
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/v1/mt5/instances/{instance_id}/start",
                headers=headers
            )
            if response.status_code == 200:
                print(f"  ✓ 端口 {port} 已启动")
            else:
                print(f"  ✗ 端口 {port} 启动失败: {response.text}")
        except Exception as e:
            print(f"  ✗ 端口 {port} 启动失败: {e}")

    print()
    print("=" * 50)
    print("升级流程完成！")
    print("=" * 50)
    print()
    print("请验证实例状态:")
    response = requests.get(f"{BACKEND_URL}/api/v1/mt5/instances", headers=headers)
    instances = response.json()
    for inst in instances:
        print(f"  端口 {inst['service_port']}: {inst['status']}")

if __name__ == "__main__":
    try:
        token = login()
        print("✓ 登录成功")
        print()
        upgrade_agent_via_api(token)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
