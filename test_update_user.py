import requests
import json

# Login
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

# Get current user
user_response = requests.get(
    "http://localhost:8000/api/v1/users/me",
    headers=headers
)

if user_response.status_code != 200:
    print(f"Get user failed: {user_response.status_code}")
    exit(1)

user = user_response.json()
print("Current user data:")
print(f"  Username: {user['username']}")
print(f"  feishu_open_id: {user.get('feishu_open_id')}")
print(f"  feishu_mobile: {user.get('feishu_mobile')}")
print(f"  feishu_union_id: {user.get('feishu_union_id')}")
print()

# Test 1: Clear feishu_union_id by setting it to null
print("Test 1: Clearing feishu_union_id...")
update_response = requests.put(
    "http://localhost:8000/api/v1/users/me",
    headers=headers,
    json={
        "feishu_union_id": None
    }
)

if update_response.status_code != 200:
    print(f"Update failed: {update_response.status_code}")
    print(update_response.text)
else:
    updated_user = update_response.json()
    print(f"  feishu_union_id after update: {updated_user.get('feishu_union_id')}")
    print()

# Test 2: Clear feishu_union_id by setting it to empty string
print("Test 2: Setting feishu_union_id to empty string...")
update_response = requests.put(
    "http://localhost:8000/api/v1/users/me",
    headers=headers,
    json={
        "feishu_union_id": ""
    }
)

if update_response.status_code != 200:
    print(f"Update failed: {update_response.status_code}")
    print(update_response.text)
else:
    updated_user = update_response.json()
    print(f"  feishu_union_id after update: {updated_user.get('feishu_union_id')}")
    print()

# Test 3: Restore the original value
if user.get('feishu_union_id'):
    print("Test 3: Restoring original feishu_union_id...")
    update_response = requests.put(
        "http://localhost:8000/api/v1/users/me",
        headers=headers,
        json={
            "feishu_union_id": user['feishu_union_id']
        }
    )

    if update_response.status_code != 200:
        print(f"Restore failed: {update_response.status_code}")
        print(update_response.text)
    else:
        updated_user = update_response.json()
        print(f"  feishu_union_id after restore: {updated_user.get('feishu_union_id')}")

print("\nAll tests completed!")
