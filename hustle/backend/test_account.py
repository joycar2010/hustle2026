import requests
import json

# 测试添加账户
print("测试添加账户...")
url = "http://localhost:8000/api/v1/accounts"
headers = {"Content-Type": "application/json"}
data = {
    "platform_id": 1,
    "account_name": "test_account",
    "api_key": "test_api_key",
    "api_secret": "test_api_secret",
    "is_active": True
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(f"添加账户响应状态码: {response.status_code}")
print(f"添加账户响应内容: {response.text}")

# 测试获取账户列表
print("\n测试获取账户列表...")
url = "http://localhost:8000/api/v1/accounts/list"
response = requests.get(url)
print(f"获取账户列表响应状态码: {response.status_code}")
print(f"获取账户列表响应内容: {response.text}")