import http.client
import json

# 测试添加账户
print("测试添加账户...")
try:
    conn = http.client.HTTPConnection("localhost", 8000, timeout=10)
    headers = {"Content-Type": "application/json"}
    data = {
        "platform_id": 1,
        "account_name": "test_account_3",
        "api_key": "test_api_key_3",
        "api_secret": "test_api_secret_3",
        "is_active": True
    }

    conn.request("POST", "/api/v1/accounts", json.dumps(data), headers)
    response = conn.getresponse()
    print(f"添加账户响应状态码: {response.status}")
    print(f"添加账户响应内容: {response.read().decode()}")
    conn.close()

    # 测试获取账户列表
    print("\n测试获取账户列表...")
    conn = http.client.HTTPConnection("localhost", 8000, timeout=10)
    conn.request("GET", "/api/v1/accounts/list")
    response = conn.getresponse()
    print(f"获取账户列表响应状态码: {response.status}")
    print(f"获取账户列表响应内容: {response.read().decode()}")
    conn.close()

    print("测试完成！")
except Exception as e:
    print(f"错误: {e}")