"""SMTP 邮件发送(P0 告警通道,2026-07-25)——短信/电话通道的替代实现(用户拍板用邮件)。

env 配置(缺任一必填项=静默禁用,零回归):
  DCM_SMTP_HOST        SMTP 服务器
  DCM_SMTP_PORT        465=SSL / 587=STARTTLS(按端口自动选择,默认465)
  DCM_SMTP_USER        登录账号
  DCM_SMTP_PASS        登录密码/应用专用密码
  DCM_ALERT_EMAIL_TO   收件人(逗号分隔多个)
  DCM_ALERT_EMAIL_FROM 发件人显示地址(默认=DCM_SMTP_USER)

同步实现(smtplib,timeout=10s);由 notify.fire 在 fatal 级调用(已过 300s/1 硬地板节流,
不会邮件风暴)。发送失败只记入 results 不抛——邮件是升级通道,绝不反噬主告警链路。
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formatdate


def _cfg():
    host = os.environ.get("DCM_SMTP_HOST", "").strip()
    port = int(os.environ.get("DCM_SMTP_PORT", "465") or 465)
    user = os.environ.get("DCM_SMTP_USER", "").strip()
    pw = os.environ.get("DCM_SMTP_PASS", "").strip()
    to = [x.strip() for x in os.environ.get("DCM_ALERT_EMAIL_TO", "").split(",") if x.strip()]
    frm = os.environ.get("DCM_ALERT_EMAIL_FROM", "").strip() or user
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
