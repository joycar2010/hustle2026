"""Check AccountBalance model fields"""
from app.schemas.account import AccountBalance
import inspect

print("AccountBalance fields:")
print("-" * 50)

# Get all fields from the Pydantic model
if hasattr(AccountBalance, 'model_fields'):
    fields = AccountBalance.model_fields
    for field_name, field_info in fields.items():
        print(f"  {field_name}: {field_info.annotation}")
else:
    print("Using __fields__:")
    for field_name, field in AccountBalance.__fields__.items():
        print(f"  {field_name}: {field.type_}")

print("\n" + "=" * 50)
print("Checking if 'funding_fee' exists...")
if hasattr(AccountBalance, 'model_fields'):
    if 'funding_fee' in AccountBalance.model_fields:
        print("[OK] funding_fee field exists in AccountBalance model")
    else:
        print("[ERROR] funding_fee field NOT FOUND in AccountBalance model!")
else:
    if 'funding_fee' in AccountBalance.__fields__:
        print("[OK] funding_fee field exists in AccountBalance model")
    else:
        print("[ERROR] funding_fee field NOT FOUND in AccountBalance model!")
