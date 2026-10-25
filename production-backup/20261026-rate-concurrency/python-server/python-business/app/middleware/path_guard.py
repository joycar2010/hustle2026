"""Request path protections for the public/static application surface."""

from __future__ import annotations

from urllib.parse import unquote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


def contains_dotfile_component(path: str) -> bool:
    """Return whether *path* contains a dot-prefixed URL path component.

    ASGI servers normally decode the URL once, but clients can send encoded
    dotfiles (or double-encoded variants) to try to bypass a string check.
    Decode a bounded number of times and reject both slash styles.
    """
    decoded = path or ""
    for _ in range(3):
        next_path = unquote(decoded)
        if next_path == decoded:
            break
        decoded = next_path

    components = decoded.replace("\\", "/").split("/")
    return any(component.startswith(".") for component in components if component)


class DotfilePathMiddleware(BaseHTTPMiddleware):
    """Fail closed for dotfiles instead of handing them to SPA fallback."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if contains_dotfile_component(request.url.path):
            return PlainTextResponse("Not Found", status_code=404)
        return await call_next(request)
