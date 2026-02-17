import redis
from .config import settings

REDIS_URL = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def get_redis():
    return redis_client
