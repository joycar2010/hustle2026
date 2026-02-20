"""
Test login functionality
"""
import requests
import json

# Test credentials
username = "admin"
password = "admin123"

print("=" * 50)
print("Testing Hustle XAU Login")
print("=" * 50)
print()

# Test backend health
print("1. Checking backend health...")
try:
    response = requests.get("http://localhost:8000/health", timeout=5)
    if response.status_code == 200:
        print("✓ Backend is running")
    else:
        print(f"✗ Backend returned status {response.status_code}")
        exit(1)
except requests.exceptions.ConnectionError:
    print("✗ Backend is not running")
    print("  Please start the backend first:")
    print("  cd backend && uvicorn app.main:app --reload")
    exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    exit(1)

print()

# Test login
print("2. Testing login...")
print(f"   Username: {username}")
print(f"   Password: {password}")
print()

try:
    response = requests.post(
        "http://localhost:8000/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json"},
        timeout=5
    )

    if response.status_code == 200:
        data = response.json()
        print("✓ Login successful!")
        print(f"  Access Token: {data['access_token'][:50]}...")
        print(f"  User ID: {data['user_id']}")
        print(f"  Username: {data['username']}")
        print()
        print("=" * 50)
        print("Login is working correctly!")
        print("=" * 50)
        print()
        print("You can now:")
        print("  1. Start frontend: cd frontend && npm run dev")
        print("  2. Open browser: http://localhost:3000")
        print("  3. Login with admin/admin123")
    else:
        print(f"✗ Login failed with status {response.status_code}")
        print(f"  Response: {response.text}")

        if response.status_code == 401:
            print()
            print("This might be a password hash mismatch.")
            print("Try recreating the user:")
            print("  cd backend && python create_user_simple.py")

except Exception as e:
    print(f"✗ Error: {e}")
    exit(1)
