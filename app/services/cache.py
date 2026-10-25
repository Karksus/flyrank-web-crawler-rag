from cachetools import TTLCache
from functools import wraps
from app.core.config import settings

# Global cache instance
cache = TTLCache(maxsize=1000, ttl=settings.CACHE_TTL_SECONDS)


def cached(ttl: int = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key
            key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            if key in cache:
                return cache[key]
            result = await func(*args, **kwargs)
            cache[key] = result
            return result
        return wrapper
    return decorator


def invalidate_cache(pattern: str = None):
    """Invalidate cache entries"""
    if pattern:
        keys_to_delete = [k for k in cache.keys() if pattern in k]
        for k in keys_to_delete:
            del cache[k]
    else:
        cache.clear()
