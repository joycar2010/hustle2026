"""测试 MT5 微服务"""
import requests
import json

BASE_URL = "http://localhost:8001"
API_KEY = "OQ6bUimHZDmXEZzJKE"
HEADERS = {"X-API-Key": API_KEY}

def test_health():
    """测试健康检查"""
    resp = requests.get(f"{BASE_URL}/health")
    print(f"Health Check: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    print()

def test_connection_status():
    """测试连接状态"""
    resp = requests.get(f"{BASE_URL}/mt5/connection/status", headers=HEADERS)
    print(f"Connection Status: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    print()

def test_account_balance():
    """测试账户余额"""
    resp = requests.get(f"{BASE_URL}/mt5/account/balance", headers=HEADERS)
    print(f"Account Balance: {resp.status_code}")
    if resp.status_code == 200:
        print(json.dumps(resp.json(), indent=2))
    else:
        print(resp.text)
    print()

def test_positions():
    """测试持仓查询"""
    resp = requests.get(f"{BASE_URL}/mt5/positions", headers=HEADERS)
    print(f"Positions: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Total positions: {len(data.get('positions', []))}")
        print(json.dumps(data, indent=2))
    else:
        print(resp.text)
    print()

if __name__ == "__main__":
    print("=== Testing MT5 Microservice ===\n")
    
    try:
        test_health()
        test_connection_status()
        test_account_balance()
        test_positions()
        
        print("✓ All tests completed")
    except Exception as e:
        print(f"✗ Test failed: {e}")
