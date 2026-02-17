import requests
import json

# 测试添加账户
print("测试添加账户...")
try:
    url = "http://localhost:8000/api/v1/accounts"
    headers = {"Content-Type": "application/json"}
    data = {
        "platform_id": 1,
        "account_name": "test_account_2",
        "api_key": "test_api_key_2",
        "api_secret": "test_api_secret_2",
        "is_active": True
    }

    response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
    print(f"添加账户响应状态码: {response.status_code}")
    print(f"添加账户响应内容: {response.text}")

    # 测试获取账户列表
    print("\n测试获取账户列表...")
    url = "http://localhost:8000/api/v1/accounts/list"
    response = requests.get(url, timeout=10)
    print(f"获取账户列表响应状态码: {response.status_code}")
    print(f"获取账户列表响应内容: {response.text}")

    print("测试完成！")
except Exception as e:
    print(f"错误: {e}")