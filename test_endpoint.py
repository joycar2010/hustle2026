import requests
import json

# Test the new endpoint
url = "http://localhost:8000/api/v1/trading/orders/realtime"

# Try without auth first
response = requests.get(url)
print(f"Status without auth: {response.status_code}")
print(f"Response: {response.text[:200]}")

# The endpoint requires authentication, so we expect 401 or 403, not 404
# If we get 404, the route is not registered correctly
