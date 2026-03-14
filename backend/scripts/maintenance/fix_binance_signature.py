"""
Binance Futures API Signature Fix
Resolves -1022 Invalid Signature Error
"""

import hmac
import hashlib
import time
import requests
from typing import Dict, Any


class BinanceFuturesClientFixed:
    """Fixed Binance Futures API Client"""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://fapi.binance.com"
        self.time_offset = 0

    def sync_time(self) -> None:
        """Synchronize local time with Binance server time"""
        try:
            local_time = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/fapi/v1/time", timeout=5)
            server_time = response.json()["serverTime"]
            self.time_offset = server_time - local_time

            print(f"OK Time synchronized")
            print(f"  Local time: {local_time}")
            print(f"  Server time: {server_time}")
            print(f"  Time offset: {self.time_offset}ms")

        except Exception as e:
            print(f"ERROR Time sync failed: {e}")
            raise

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """
        Generate HMAC SHA256 signature

        Steps:
        1. Sort parameters by ASCII code
        2. Concatenate as query string: key1=value1&key2=value2
        3. HMAC SHA256 encrypt with API Secret
        4. Convert to lowercase hexadecimal
        """
        # Step 1: Sort parameters by ASCII code
        sorted_params = sorted(params.items())

        # Step 2: Concatenate as query string
        query_string = "&".join([f"{key}={value}" for key, value in sorted_params])
        print(f"  Query string: {query_string}")

        # Step 3 & 4: HMAC SHA256 and convert to hex
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        print(f"  Signature: {signature}")
        return signature

    def get_account_info(self) -> Dict[str, Any]:
        """Get account information (requires signature)"""
        print("\n=== Calling /fapi/v2/account ===")

        # 1. Prepare parameters (without signature)
        params = {
            "timestamp": int(time.time() * 1000) + self.time_offset,
            "recvWindow": 60000
        }

        print(f"  Timestamp: {params['timestamp']}")
        print(f"  Recv window: {params['recvWindow']}ms")

        # 2. Generate signature
        signature = self._generate_signature(params)

        # 3. Add signature to parameters
        params["signature"] = signature

        # 4. Prepare headers
        headers = {
            "X-MBX-APIKEY": self.api_key
        }

        # 5. Send request
        try:
            url = f"{self.base_url}/fapi/v2/account"
            print(f"  Request URL: {url}")

            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=10
            )

            # 6. Handle response
            if response.status_code == 200:
                print(f"OK Request successful")
                return response.json()
            else:
                error_data = response.json()
                error_code = error_data.get("code")
                error_msg = error_data.get("msg")

                print(f"ERROR Request failed")
                print(f"  HTTP status: {response.status_code}")
                print(f"  Error code: {error_code}")
                print(f"  Error message: {error_msg}")

                if error_code == -1022:
                    print("\n[-1022 Error Analysis]")
                    print("  Reason: Invalid signature")
                    print("  Possible issues:")
                    print("    1. Incorrect API Secret")
                    print("    2. Parameters not sorted by ASCII")
                    print("    3. Wrong query string format")
                    print("    4. Signature not lowercase hex")
                elif error_code == -1021:
                    print("\n[-1021 Error Analysis]")
                    print("  Reason: Timestamp outside recvWindow")
                    print("  Solution: Call sync_time() first")

                raise Exception(f"Binance API error: {error_data}")

        except requests.exceptions.Timeout:
            print(f"ERROR Request timeout")
            raise
        except requests.exceptions.ConnectionError:
            print(f"ERROR Connection error")
            raise
        except Exception as e:
            print(f"ERROR Unknown error: {e}")
            raise


def main():
    """Main function"""
    print("=" * 60)
    print("Binance Futures API Signature Fix Verification")
    print("=" * 60)

    # 1. Get API credentials from database
    import psycopg2

    conn = psycopg2.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='postgres',
        database='postgres'
    )
    cursor = conn.cursor()
    cursor.execute("SELECT api_key, api_secret FROM accounts WHERE platform_id = 1 LIMIT 1")
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        print("ERROR No Binance account found")
        return

    api_key, api_secret = result
    print(f"\nUsing API Key: {api_key[:20]}...")

    # 2. Create client
    client = BinanceFuturesClientFixed(api_key, api_secret)

    # 3. Sync time (IMPORTANT!)
    print("\nStep 1: Synchronize server time")
    print("-" * 60)
    client.sync_time()

    # 4. Get account info
    print("\nStep 2: Get account information")
    print("-" * 60)
    try:
        account_data = client.get_account_info()

        print("\nOK Account information retrieved successfully!")
        print(f"  Total wallet balance: {account_data.get('totalWalletBalance')}")
        print(f"  Available balance: {account_data.get('availableBalance')}")
        print(f"  Total margin balance: {account_data.get('totalMarginBalance')}")
        print(f"  Total unrealized profit: {account_data.get('totalUnrealizedProfit')}")

        print("\n" + "=" * 60)
        print("OK -1022 Signature error has been fixed!")
        print("=" * 60)

    except Exception as e:
        print(f"\nERROR Failed to get account info: {e}")
        print("\nPlease check:")
        print("  1. API Key and Secret are correct")
        print("  2. API Key has futures permission")
        print("  3. IP is whitelisted")


if __name__ == "__main__":
    main()
