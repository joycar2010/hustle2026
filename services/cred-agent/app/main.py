"""dcm-cred-agent —— API 凭证下发代理（B 机;明文解密只在此发生）。

安全边界（用户拍板方案一=浏览器端加密）：
  - mix_main.api_credentials 只存密文(sealed box);私钥只在 B 机 ~/dexcexmix/.mix_cred_key(600);
  - 本 agent 60s 轮询 pending → 本机解密 → 写 ~/dexcexmix/.creds/{account_key}.env(600) → 回写 active;
  - revoked → 删除该 .env + 回写;解密失败/格式错 → error 回写(网页可见,不吞)。
  - 交易客户端(account-snapshot/引擎)从 .creds/ 读该账户 key + proxy_url(直连=空)。
明文仅存在于:B 机进程内存(瞬时)+ B 机 .creds/*.env(600)。绝不回传 mix-backend/DB/网页。"""
import base64
import json
import logging
import os
import time

import psycopg2
import psycopg2.extras
from nacl.public import PrivateKey, SealedBox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cred-agent")

DSN = os.environ["MIX_MAIN_DSN"]
KEYFILE = os.path.expanduser("~/dexcexmix/.mix_cred_key")
CREDS_DIR = os.path.expanduser("~/dexcexmix/.creds")
INTERVAL = int(os.environ.get("CRED_AGENT_INTERVAL_SEC", "60"))

os.makedirs(CREDS_DIR, mode=0o700, exist_ok=True)
_SK = PrivateKey(base64.b64decode(open(KEYFILE).read().strip()))
_BOX = SealedBox(_SK)


def _decrypt(ct: str) -> dict:
    raw = _BOX.decrypt(base64.b64decode(ct)).decode()
    parts = (raw.split("\n") + ["", "", ""])[:3]
    return {"key": parts[0].strip(), "secret": parts[1].strip(), "passphrase": parts[2].strip()}


def _write_env(account_key: str, cred: dict, proxy_url: str):
    path = os.path.join(CREDS_DIR, f"{account_key}.env")
    lines = [f"API_KEY={cred['key']}", f"API_SECRET={cred['secret']}"]
    if cred.get("passphrase"):
        lines.append(f"API_PASSPHRASE={cred['passphrase']}")
    lines.append(f"PROXY_URL={proxy_url or ''}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")


def _mask(k: str) -> str:
    return f"{k[:4]}…{k[-4:]}" if len(k) > 8 else "****"


def process(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT account_key, ciphertext, proxy_url, state FROM api_credentials "
                    "WHERE state IN ('pending','revoked')")
        rows = cur.fetchall()
    for r in rows:
        ak = r["account_key"]
        if r["state"] == "revoked":
            p = os.path.join(CREDS_DIR, f"{ak}.env")
            if os.path.exists(p):
                os.remove(p)
            log.info("REVOKED %s (env removed)", ak)
            continue
        try:
            cred = _decrypt(r["ciphertext"])
            if not cred["key"] or not cred["secret"]:
                raise ValueError("解密结果缺 key/secret")
            _write_env(ak, cred, r["proxy_url"])
            detail = f"key={_mask(cred['key'])} proxy={'on' if r['proxy_url'] else 'direct'}"
            with conn.cursor() as cur:
                cur.execute("UPDATE api_credentials SET state='active', applied_detail=%s, updated_at=now() "
                            "WHERE account_key=%s", (detail, ak))
            conn.commit()
            log.info("ACTIVE %s (%s)", ak, detail)
        except Exception as e:  # noqa: BLE001
            with conn.cursor() as cur:
                cur.execute("UPDATE api_credentials SET state='error', applied_detail=%s, updated_at=now() "
                            "WHERE account_key=%s", (repr(e)[:200], ak))
            conn.commit()
            log.warning("ERROR %s: %r", ak, e)


def main():
    log.info("cred-agent up interval=%ss creds_dir=%s", INTERVAL, CREDS_DIR)
    while True:
        try:
            conn = psycopg2.connect(DSN)
            try:
                process(conn)
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning("round failed: %r", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
