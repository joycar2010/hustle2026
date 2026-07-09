"""飞书发送:自建应用 bot(tenant_access_token 进程内缓存)+ 群 webhook。

同步 httpx;async 调用方用 asyncio.to_thread 包。所有异常吞掉,返回 (ok, detail)。
"""
import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
_token_cache: dict[str, tuple[str, float]] = {}  # app_id -> (token, expire_ts)


def _tenant_token(app_id: str, app_secret: str) -> str | None:
    now = time.time()
    cached = _token_cache.get(app_id)
    if cached and cached[1] - now > 60:
        return cached[0]
    try:
        resp = httpx.post(_TOKEN_URL, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
        d = resp.json()
        if d.get("code") != 0:
            logger.warning(f"feishu tenant token failed: {d.get('msg')}")
            return None
        tok = d["tenant_access_token"]
        _token_cache[app_id] = (tok, now + int(d.get("expire", 7200)))
        return tok
    except Exception as e:
        logger.warning(f"feishu tenant token error: {e}")
        return None


def send_bot_text(app_id: str, app_secret: str, open_id: str, title: str, content: str) -> tuple[bool, str]:
    """自建应用机器人发文本给指定 open_id。"""
    if not (app_id and app_secret and open_id):
        return False, "app_id/app_secret/open_id 不全"
    tok = _tenant_token(app_id, app_secret)
    if not tok:
        return False, "获取 tenant_access_token 失败"
    try:
        resp = httpx.post(
            _MSG_URL,
            params={"receive_id_type": "open_id"},
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"receive_id": open_id, "msg_type": "text",
                  "content": json.dumps({"text": f"[{title}]\n{content}"})},
            timeout=10,
        )
        d = resp.json()
        if d.get("code") == 0:
            return True, d.get("data", {}).get("message_id", "")
        return False, d.get("msg", "unknown")
    except Exception as e:
        return False, str(e)


def send_webhook_text(webhook_url: str, title: str, content: str) -> tuple[bool, str]:
    """群自定义机器人 webhook 发文本。"""
    if not webhook_url:
        return False, "webhook 未配置"
    try:
        resp = httpx.post(
            webhook_url,
            json={"msg_type": "text", "content": {"text": f"[{title}]\n{content}"}},
            timeout=10,
        )
        return resp.status_code == 200, f"http {resp.status_code}"
    except Exception as e:
        return False, str(e)
