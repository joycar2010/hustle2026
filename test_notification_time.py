import requests
import json

# Login
login_response = requests.post(
    "http://localhost:8000/api/v1/auth/login",
    json={"username": "admin", "password": "admin123"}
)

if login_response.status_code != 200:
    print(f"Login failed: {login_response.status_code}")
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
print(f"Current user: {user['username']}")
print(f"  feishu_open_id: {user.get('feishu_open_id')}")
print()

if not user.get('feishu_open_id'):
    print("Error: Current user doesn't have feishu_open_id set!")
    exit(1)

# Get notification templates
templates_response = requests.get(
    "http://localhost:8000/api/v1/notifications/templates",
    headers=headers
)

if templates_response.status_code != 200:
    print(f"Get templates failed: {templates_response.status_code}")
    exit(1)

templates = templates_response.json()["templates"]
print(f"Found {len(templates)} templates")

if len(templates) == 0:
    print("No templates available for testing")
    exit(0)

# Use the first template for testing
template = templates[0]
print(f"\nTesting with template: {template['template_key']}")

# Send test notification
send_response = requests.post(
    "http://localhost:8000/api/v1/notifications/send",
    headers=headers,
    json={
        "template_key": template["template_key"],
        "user_ids": [str(user["user_id"])],
        "variables": {
            "user_name": user["username"],
            "timestamp": "2026-03-06 15:30:00",  # Beijing time
            "test_value": "测试数据"
        }
    }
)

print(f"\nSend response status: {send_response.status_code}")
if send_response.status_code == 200:
    result = send_response.json()
    print(f"Success: {result.get('success')}")
    print(f"Results: {json.dumps(result.get('results', []), indent=2)}")
else:
    print(f"Error: {send_response.text}")

# Check logs to verify Beijing time
print("\nChecking notification logs...")
logs_response = requests.get(
    "http://localhost:8000/api/v1/notifications/logs",
    headers=headers,
    params={"limit": 5}
)

if logs_response.status_code == 200:
    logs = logs_response.json()["logs"]
    print(f"Recent logs (showing last 3):")
    for log in logs[:3]:
        print(f"  - {log['template_key']}: {log['status']} at {log.get('sent_at', 'N/A')}")
else:
    print(f"Failed to get logs: {logs_response.status_code}")
