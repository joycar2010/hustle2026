"""
优雅重启后端服务脚本
"""
import requests
import subprocess
import time
import sys
import os

def check_service_running():
    """检查服务是否运行"""
    try:
        response = requests.get("http://localhost:8000/docs", timeout=2)
        return response.status_code == 200
    except:
        return False

def restart_service():
    """重启后端服务"""
    print("正在重启后端服务...")

    # 检查当前服务状态
    if check_service_running():
        print("✓ 后端服务当前正在运行")
        print("⚠️  需要手动重启服务以应用飞书配置")
        print("\n请执行以下步骤：")
        print("1. 停止当前后端服务（Ctrl+C 或 kill 进程）")
        print("2. 重新启动后端服务")
        print("\n或者在服务器上执行：")
        print("   cd c:/app/hustle2026/backend")
        print("   # 停止服务")
        print("   pkill -f 'uvicorn app.main:app'")
        print("   # 启动服务")
        print("   nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &")
        return True
    else:
        print("✗ 后端服务未运行")
        print("请启动后端服务：")
        print("   cd c:/app/hustle2026/backend")
        print("   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")
        return False

if __name__ == "__main__":
    restart_service()
