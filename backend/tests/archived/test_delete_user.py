"""测试删除用户 API"""
import requests
import json

# 配置
BASE_URL = "http://localhost:8001"
# 需要先登录获取 token
LOGIN_URL = f"{BASE_URL}/api/v1/auth/login"
DELETE_USER_URL = f"{BASE_URL}/api/v1/users"

# 1. 登录获取 token（使用 admin 账户）
login_data = {
    "username": "admin",
    "password": "admin123"  # 请替换为实际密码
}

print("1. 尝试登录...")
try:
    response = requests.post(LOGIN_URL, json=login_data)
    print(f"   状态码: {response.status_code}")
    if response.status_code == 200:
        token = response.json().get("access_token")
        print(f"   登录成功，获取到 token")

        # 2. 获取所有用户列表
        headers = {"Authorization": f"Bearer {token}"}
        users_response = requests.get(f"{DELETE_USER_URL}/", headers=headers)
        print(f"\n2. 获取用户列表")
        print(f"   状态码: {users_response.status_code}")

        if users_response.status_code == 200:
            users = users_response.json()
            print(f"   用户数量: {len(users)}")
            for user in users[:5]:  # 只显示前5个
                print(f"   - {user['username']} ({user['user_id']})")

            # 3. 测试删除（这里不实际删除，只是显示如何调用）
            print(f"\n3. 删除用户 API 端点: DELETE {DELETE_USER_URL}/{{user_id}}")
            print(f"   请在前端测试删除功能")
        else:
            print(f"   错误: {users_response.text}")
    else:
        print(f"   登录失败: {response.text}")
except Exception as e:
    print(f"   错误: {e}")
