import requests
import json

# 配置
BASE_URL = "https://app.hustle2026.xyz"
# 需要替换为实际的token
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwYmM5YzVmNy1kYzc3LTRmN2QtYmZiZi00YjM0N2E5MzRiMjQiLCJleHAiOjE3NzM3NDYxMjZ9.YfbA1sdS94Mn0GiRGsCUS4E2XRvcdz6oR0EFCxzoBH4"
ACCOUNT_ID = "1ce0146d-b2cb-467d-8b34-ff951e696563"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# 测试获取MT5客户端列表
print("=== 测试获取MT5客户端列表 ===")
response = requests.get(
    f"{BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/mt5-clients",
    headers=headers
)
print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
print()

# 测试创建MT5客户端
print("=== 测试创建MT5客户端 ===")
test_client_data = {
    "client_name": "测试客户端",
    "mt5_login": "3971962",
    "mt5_password": "Lk106504",
    "password_type": "primary",
    "mt5_server": "Bybit-Live-2",
    "mt5_path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
    "mt5_data_path": None,
    "proxy_id": None,
    "priority": 1,
    "is_active": True
}

response = requests.post(
    f"{BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/mt5-clients",
    headers=headers,
    json=test_client_data
)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
else:
    print(f"Error: {response.text}")
