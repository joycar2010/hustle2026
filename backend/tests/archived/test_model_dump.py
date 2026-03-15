"""Test AccountBalance model_dump behavior"""
from app.schemas.account import AccountBalance

# Create AccountBalance with funding_fee
balance1 = AccountBalance(
    total_assets=1000.0,
    available_balance=800.0,
    net_assets=900.0,
    frozen_assets=100.0,
    margin_balance=900.0,
    unrealized_pnl=50.0,
    funding_fee=10.17  # Set funding_fee
)

print("Test 1: AccountBalance with funding_fee=10.17")
print("-" * 50)
dumped1 = balance1.model_dump()
print(f"funding_fee in dict: {'funding_fee' in dumped1}")
print(f"funding_fee value: {dumped1.get('funding_fee')}")
print()

# Create AccountBalance without funding_fee (None)
balance2 = AccountBalance(
    total_assets=1000.0,
    available_balance=800.0,
    net_assets=900.0,
    frozen_assets=100.0,
    margin_balance=900.0,
    unrealized_pnl=50.0
)

print("Test 2: AccountBalance without funding_fee (None)")
print("-" * 50)
dumped2 = balance2.model_dump()
print(f"funding_fee in dict: {'funding_fee' in dumped2}")
print(f"funding_fee value: {dumped2.get('funding_fee')}")
print()

# Test with exclude_none
print("Test 3: model_dump(exclude_none=True)")
print("-" * 50)
dumped3 = balance2.model_dump(exclude_none=True)
print(f"funding_fee in dict: {'funding_fee' in dumped3}")
print(f"Keys in dict: {list(dumped3.keys())}")
