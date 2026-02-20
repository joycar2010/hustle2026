"""
Comprehensive Login Diagnostics
"""
import requests
import json
import sys

print("=" * 60)
print("HUSTLE XAU - LOGIN DIAGNOSTICS")
print("=" * 60)
print()

# Test 1: Backend Health
print("TEST 1: Backend Health Check")
print("-" * 60)
try:
    response = requests.get("http://localhost:8000/health", timeout=3)
    print(f"✓ Backend is running")
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.json()}")
except requests.exceptions.ConnectionError:
    print("✗ BACKEND IS NOT RUNNING!")
    print()
    print("SOLUTION:")
    print("  Open a terminal and run:")
    print("  cd d:\\git\\hustle2026\\backend")
    print("  python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
    print()
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print()

# Test 2: Check if user exists
print("TEST 2: Check User in Database")
print("-" * 60)
try:
    import psycopg2
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password="postgres",
        database="hustle_db"
    )
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, email, is_active FROM users WHERE username = 'admin'")
    user = cursor.fetchone()

    if user:
        print(f"✓ User exists in database")
        print(f"  User ID: {user[0]}")
        print(f"  Username: {user[1]}")
        print(f"  Email: {user[2]}")
        print(f"  Active: {user[3]}")
    else:
        print("✗ User 'admin' not found in database!")
        print()
        print("SOLUTION:")
        print("  cd d:\\git\\hustle2026\\backend")
        print("  python create_user_simple.py")
        sys.exit(1)

    cursor.close()
    conn.close()
except Exception as e:
    print(f"⚠ Could not check database: {e}")

print()

# Test 3: Test Login API
print("TEST 3: Test Login API")
print("-" * 60)
credentials = {
    "username": "admin",
    "password": "admin123"
}

print(f"Attempting login with:")
print(f"  Username: {credentials['username']}")
print(f"  Password: {credentials['password']}")
print()

try:
    response = requests.post(
        "http://localhost:8000/api/v1/auth/login",
        json=credentials,
        headers={"Content-Type": "application/json"},
        timeout=5
    )

    print(f"Response Status: {response.status_code}")
    print(f"Response Body: {response.text}")
    print()

    if response.status_code == 200:
        data = response.json()
        print("✓ LOGIN SUCCESSFUL!")
        print(f"  Access Token: {data['access_token'][:50]}...")
        print(f"  User ID: {data['user_id']}")
        print(f"  Username: {data['username']}")
        print()
        print("=" * 60)
        print("DIAGNOSIS: Backend login is working correctly!")
        print("=" * 60)
        print()
        print("If frontend still shows error, check:")
        print("  1. Browser console (F12) for errors")
        print("  2. Network tab to see actual API calls")
        print("  3. Make sure frontend is using http://localhost:8000")

    elif response.status_code == 401:
        print("✗ LOGIN FAILED - Invalid credentials")
        print()
        print("DIAGNOSIS: Password hash mismatch")
        print()
        print("SOLUTION:")
        print("  The password hash in database doesn't match.")
        print("  Recreate the user:")
        print()
        print("  cd d:\\git\\hustle2026\\backend")
        print("  python create_user_simple.py")

    else:
        print(f"✗ Unexpected status code: {response.status_code}")

except Exception as e:
    print(f"✗ Error testing login: {e}")
    sys.exit(1)

print()
print("=" * 60)
