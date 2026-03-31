"""
检查 Windows 服务器上的 MT5 进程
"""
import requests
import json

# 通过 Windows Agent 的自定义端点检查进程
# 如果没有这个端点，我们需要添加一个

print("=== 尝试获取 Windows 进程信息 ===")

# 方法1: 检查是否有进程查询端点
try:
    r = requests.get("http://172.31.14.113:9000/system/processes", timeout=5)
    if r.status_code == 200:
        print("进程列表:")
        print(json.dumps(r.json(), indent=2))
    else:
        print(f"端点不存在或返回错误: {r.status_code}")
except Exception as e:
    print(f"无法访问进程端点: {e}")

# 方法2: 通过桥接服务检查 MT5 状态
print("\n=== 检查桥接服务的 MT5 状态 ===")
for port in [8001, 8002]:
    try:
        r = requests.get(f"http://172.31.14.113:{port}/health", timeout=5)
        data = r.json()
        mt5_status = "运行中" if data.get("mt5") else "未运行"
        print(f"端口 {port}: 桥接服务={data.get('status')}, MT5={mt5_status}")
    except Exception as e:
        print(f"端口 {port}: 无法访问 - {e}")

print("\n=== 建议 ===")
print("需要在 Windows Agent 添加进程查询端点来确认 terminal64.exe 是否真的在运行")
