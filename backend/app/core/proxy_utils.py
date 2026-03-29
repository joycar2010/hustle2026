"""Proxy URL builder utility for IPIPGO static IP proxy support."""
from typing import Optional


def build_proxy_url(proxy_config: Optional[dict]) -> Optional[str]:
    """Convert a proxy_config dict to a proxy URL string.

    Args:
        proxy_config: dict with keys: proxy_type, host, port, username, password, region

    Returns:
        Proxy URL string (e.g. "socks5://user:pass@host:port") or None if not configured.
    """
    if not proxy_config:
        return None
    host = proxy_config.get("host", "").strip()
    port = proxy_config.get("port")
    if not host or not port:
        return None

    proxy_type = proxy_config.get("proxy_type", "socks5").strip()
    username = proxy_config.get("username", "")
    password = proxy_config.get("password", "")

    if username and password:
        auth = f"{username}:{password}@"
    elif username:
        auth = f"{username}@"
    else:
        auth = ""

    return f"{proxy_type}://{auth}{host}:{port}"
