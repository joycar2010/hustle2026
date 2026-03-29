"""检查后台任务运行状态"""
import sys
import io
import requests
import json

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 80)
print("后台任务运行状态检查")
print("=" * 80)
print()

# 检查后台服务是否运行
print("【1】检查后台服务状态")
print("-" * 80)
try:
    response = requests.get("http://localhost:8000/health", timeout=5)
    if response.status_code == 200:
        print("✓ 后台服务正在运行")
        print(f"  响应: {response.json()}")
    else:
        print(f"✗ 后台服务响应异常: {response.status_code}")
except Exception as e:
    print(f"✗ 无法连接到后台服务: {e}")
print()

# 检查后台任务状态
print("【2】检查后台任务状态")
print("-" * 80)
try:
    # 尝试获取任务状态（如果有相关API）
    response = requests.get("http://localhost:8000/api/system/tasks", timeout=5)
    if response.status_code == 200:
        tasks = response.json()
        print(f"后台任务列表:")
        print(json.dumps(tasks, indent=2, ensure_ascii=False))
    else:
        print(f"⚠ 无法获取任务状态: {response.status_code}")
except Exception as e:
    print(f"⚠ 无法查询任务状态: {e}")
print()

# 检查WebSocket连接
print("【3】检查WebSocket服务")
print("-" * 80)
try:
    response = requests.get("http://localhost:8000/api/websocket/status", timeout=5)
    if response.status_code == 200:
        print("✓ WebSocket服务可用")
    else:
        print(f"⚠ WebSocket服务状态: {response.status_code}")
except Exception as e:
    print(f"⚠ 无法检查WebSocket服务: {e}")
print()

print("=" * 80)
print("建议")
print("=" * 80)
print("""
如果后台服务未运行或任务未启动：

1. 检查后台进程
   ps aux | grep python | grep app.main

2. 查看后台日志
   tail -f backend/logs/app.log

3. 重启后台服务
   cd backend && python -m uvicorn app.main:app --reload

4. 检查任务是否自动启动
   - AccountBalanceStreamer 应该在服务启动时自动启动
   - 检查 app/main.py 中的 startup 事件
""")
