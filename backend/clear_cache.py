"""Clear account service cache"""
from app.services.account_service import account_data_service

# Clear the cache
account_data_service._cache.clear()
print("Cache cleared successfully!")
print(f"Cache size: {len(account_data_service._cache)}")
