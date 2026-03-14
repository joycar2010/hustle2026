import asyncio
import aiohttp

async def test_market_data():
    """Test if market data service is working"""
    url = "http://localhost:8000/api/v1/market/data/latest"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"symbol": "XAUUSDT"}) as response:
                print(f"Status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    print(f"\nLatest market data:")
                    print(f"  Timestamp: {data.get('timestamp')}")
                    print(f"  Binance bid/ask: {data.get('binance_bid')}/{data.get('binance_ask')}")
                    print(f"  Bybit bid/ask: {data.get('bybit_bid')}/{data.get('bybit_ask')}")
                    print(f"  Forward spread: {data.get('forward_spread')}")
                    print(f"  Reverse spread: {data.get('reverse_spread')}")
                else:
                    text = await response.text()
                    print(f"Error: {text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_market_data())
