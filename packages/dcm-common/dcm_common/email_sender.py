"""SMTP 邮件发送(P0 告警通道,2026-07-25)——短信/电话通道的替代实现(用户拍板用邮件)。

配置权威(增量 2026-07-25):**Redis `dcm:notify:email`**(mixadmin 通知模块→邮件(SMTP)
保存时分发,{host,port,user,sender,password,to})——一处填写双机生效;
env 回落(DCM_SMTP_HOST/PORT/USER/PASS + DCM_ALERT_EMAIL_TO/FROM)。
缺任一必填项=静默禁用,零回归。60s 进程内缓存(与 notify._global_config 同款习语)。

同步实现(smtplib,timeout=10s);由 notify.fire 在 fatal 级调用(已过 300s/1 硬地板节流,
不会邮件风暴)。发送失败只记入 results 不抛——邮件是升级通道,绝不反噬主告警链路。
"""
import json
import os
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.utils import formatdate

EMAIL_REDIS_KEY = "dcm:notify:email"
_RCFG_CACHE: dict = {"ts": 0.0, "cfg": None}
_RCFG_TTL = 60.0


def _redis_cfg() -> dict | None:
    """读 mixadmin 分发的 SMTP 配置(60s 缓存;失败=None 走 env 回落)。"""
    if time.monotonic() - _RCFG_CACHE["ts"] < _RCFG_TTL:
        return _RCFG_CACHE["cfg"]
    cfg = None
    try:
        import redis as _redis_sync
        url = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.95:6379/0")
        r = _redis_sync.from_url(url, decode_responses=True,
                                 socket_timeout=2, socket_connect_timeout=2)
        raw = r.get(EMAIL_REDIS_KEY)
        r.close()
        if raw:
            cfg = json.loads(raw)
    except Exception:  # noqa: BLE001
        cfg = None
    _RCFG_CACHE.update(ts=time.monotonic(), cfg=cfg)
    return cfg


def _cfg():
    rc = _redis_cfg() or {}
    host = (str(rc.get("host") or "") or os.environ.get("DCM_SMTP_HOST", "")).strip()
    try:
        port = int(rc.get("port") or os.environ.get("DCM_SMTP_PORT", "465") or 465)
    except (ValueError, TypeError):
        port = 465
    user = (str(rc.get("user") or "") or os.environ.get("DCM_SMTP_USER", "")).strip()
    pw = (str(rc.get("password") or "") or os.environ.get("DCM_SMTP_PASS", "")).strip()
    to_raw = str(rc.get("to") or "") or os.environ.get("DCM_ALERT_EMAIL_TO", "")
    to = [x.strip() for x in to_raw.split(",") if x.strip()]
    sender_disp = str(rc.get("sender") or "").strip()
    frm = (f"{sender_disp} <{user}>" if sender_disp
           else (os.environ.get("DCM_ALERT_EMAIL_FROM", "").strip() or user))
    return host, port, user, pw, to, frm


def email_configured() -> bool:
    host, _port, user, pw, to, _frm = _cfg()
    return bool(host and user and pw and to)


def send_alert_email(subject: str, body: str) -> tuple:
    """返回 (ok, detail)。未配置=(False,'email未配置');任何异常=(False, repr)。"""
    host, port, user, pw, to, frm = _cfg()
    if not (host and user and pw and to):
        return False, "email未配置"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10,
                                  context=ssl.create_default_context()) as s:
                s.login(user, pw)
                s.sendmail(frm, to, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pw)
                s.sendmail(frm, to, msg.as_string())
        return True, "sent"
    except Exception as e:  # noqa: BLE001
        return False, repr(e)[:120]
