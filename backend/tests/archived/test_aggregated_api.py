#!/usr/bin/env python3
"""Test the aggregated dashboard API endpoint"""

import requests
import json

# Test the aggregated dashboard API
url = "http://localhost:8000/api/v1/accounts/dashboard/aggregated"

print("Testing aggregated dashboard API...")
print("=" * 50)

try:
    response = requests.get(url)
    print(f"Status Code: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"\nResponse received with {len(data.get('accounts', []))} accounts")

        # Find MT5 account
        for account in data.get('accounts', []):
            if account.get('is_mt5_account'):
                print(f"\nMT5 Account Found:")
                print(f"  Account ID: {account.get('account_id')}")
                print(f"  Account Name: {account.get('account_name')}")
                print(f"  Platform: {account.get('platform_id')}")

                balance = account.get('balance', {})
                print(f"\nBalance Data:")
                print(f"  Total Assets: {balance.get('total_assets')} USD")
                print(f"  Net Assets: {balance.get('net_assets')} USD")
                print(f"  Available Balance: {balance.get('available_balance')} USD")
                print(f"  Funding Fee: {balance.get('funding_fee')} USD")

                if balance.get('funding_fee') == 0.0:
                    print("\n[ERROR] Funding fee is 0.0 - should be ~10.17 USD")
                else:
                    print(f"\n[OK] Funding fee is {balance.get('funding_fee')} USD")

                break
        else:
            print("\n[ERROR] No MT5 account found in response")
    else:
        print(f"Error: {response.text}")

except Exception as e:
    print(f"Exception: {e}")
