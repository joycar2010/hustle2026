"""Test script to call accounts API and check liquidation prices"""
import requests
import json

# Login first to get token
login_url = "http://localhost:8001/api/v1/auth/login"
login_data = {
    "username": "admin",
    "password": "admin123"
}

response = requests.post(login_url, json=login_data)
if response.status_code != 200:
    print(f"Login failed: {response.text}")
    exit(1)

token = response.json()["access_token"]
print(f"Login successful, token: {token[:20]}...")

# Call accounts API
accounts_url = "http://localhost:8001/api/v1/accounts"
headers = {
    "Authorization": f"Bearer {token}"
}

response = requests.get(accounts_url, headers=headers)
if response.status_code != 200:
    print(f"Get accounts failed: {response.text}")
    exit(1)

accounts = response.json()
print(f"\nFound {len(accounts)} accounts\n")

# Find MT5 account and print liquidation prices
for account in accounts:
    if account.get("is_mt5_account"):
        print("=" * 80)
        print(f"MT5 Account: {account['account_name']}")
        print("=" * 80)
        balance = account.get("balance", {})
        print(f"Total Assets: {balance.get('total_assets', 0):.2f}")
        print(f"Equity: {balance.get('net_assets', 0):.2f}")
        print(f"Risk Ratio: {balance.get('risk_ratio', 0):.2f}%")
        print(f"Total Positions: {balance.get('total_positions', 0)}")
        print(f"Entry Price: {balance.get('entry_price', 0):.2f}")
        print(f"Leverage: {balance.get('leverage', 0)}x")
        print(f"\nLiquidation Prices:")
        print(f"  Long Liquidation: {balance.get('long_liquidation_price', 0):.2f}")
        print(f"  Short Liquidation: {balance.get('short_liquidation_price', 0):.2f}")
        print("=" * 80)
