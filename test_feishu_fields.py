import requests
import json

# Login first
login_response = requests.post(
    "http://localhost:8000/api/v1/auth/login",
    json={"username": "admin", "password": "admin123"}
)

if login_response.status_code != 200:
    print(f"Login failed: {login_response.status_code}")
    print(login_response.text)
    exit(1)

token = login_response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Get all users
users_response = requests.get(
    "http://localhost:8000/api/v1/users/",
    headers=headers
)

if users_response.status_code != 200:
    print(f"Get users failed: {users_response.status_code}")
    print(users_response.text)
    exit(1)

users_data = users_response.json()
print("Users API response structure:")
print(json.dumps(users_data, indent=2, default=str)[:500])

users = users_data.get("users", [])
print(f"\nTotal users: {len(users)}")

for user in users[:3]:
    print(f"\nUser: {user['username']}")
    print(f"  feishu_open_id: {user.get('feishu_open_id')}")
    print(f"  feishu_mobile: {user.get('feishu_mobile')}")
    print(f"  feishu_union_id: {user.get('feishu_union_id')}")
