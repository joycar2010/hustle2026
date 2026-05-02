from functools import wraps

from fastapi import HTTPException, Request


def get_current_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def get_current_role(request: Request) -> str:
    return getattr(request.state, "role", "USER")


def get_effective_user_id(request: Request, query_user_id: int | None = None) -> int:
    """For SUPER_ADMIN: allows overriding user_id via query param.
    For others: always returns their own user_id."""
    current_id = get_current_user_id(request)
    role = get_current_role(request)
    if query_user_id is not None and role == "SUPER_ADMIN":
        return query_user_id
    return current_id


def require_role(*roles: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, request: Request, **kwargs):
            user_role = get_current_role(request)
            if user_role not in roles:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(*args, request=request, **kwargs)
        return wrapper
    return decorator


def require_admin(request: Request):
    role = get_current_role(request)
    if role not in ("SUPER_ADMIN", "ADMIN"):
        raise HTTPException(status_code=403, detail="Admin access required")


def require_super_admin(request: Request):
    role = get_current_role(request)
    if role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Super admin access required")
