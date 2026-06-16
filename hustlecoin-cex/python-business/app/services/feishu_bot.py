"""飞书自建应用(app_id/app_secret)机器人发送:tenant_access_token(进程内缓存)→ im/v1/messages 发文本给 open_id。

供引擎 FeishuSender(告警按 worker 的 user 路由到各自 feishu_open_id)与 /rules 测试统一调用。
与 admin_notify 的 _get_tenant_token 同口径(自建应用 tenant token)。同步函数(httpx 同步);
async 调用方用 asyncio.to_thread 包。所有异常吞掉,返回 (ok, detail)。
"""
import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
_token_cache: dict[str, tuple[str, float]] = {}   # app_id -> (token, expire_ts)


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
    """用自建应用机器人发文本给指定 open_id。返回 (ok, detail)。"""
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
