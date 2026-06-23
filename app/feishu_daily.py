"""每日飞书播报:汇总 ticks.csv(近24h + 累计 + 假设净值/最佳机会)发给指定 open_id。

由 systemd timer 每日触发:python -m app.feishu_daily
飞书自建应用口径(与生产 feishu_bot 一致):tenant_access_token → im/v1/messages 发文本。
未配置 app_id/secret/open_id 时静默跳过。所有异常打印不抛(timer 不报错噪音)。
"""
from __future__ import annotations

import csv
import json
import os
import time

import requests

from .config import cfg
from .report import build_report

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
CONTACT_URL = "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id"


def resolve_open_id_by_mobile(app_id: str, app_secret: str, mobile: str) -> tuple[str | None, str]:
    """手机号 → 本应用 open_id(需应用有"通过手机号/邮箱获取用户ID"权限)。"""
    tok = _tenant_token(app_id, app_secret)
    cands = [mobile] + ([f"+86{mobile}"] if not mobile.startswith("+") else [])
    last = "未知"
    for m in cands:
        try:
            r = requests.post(
                CONTACT_URL, params={"user_id_type": "open_id"},
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                json={"mobiles": [m]}, timeout=10,
            )
            d = r.json()
            if d.get("code") != 0:
                last = f"{d.get('code')} {d.get('msg')}"
                continue
            for u in d.get("data", {}).get("user_list", []):
                if u.get("user_id"):
                    return u["user_id"], ""
            last = "该手机号未匹配到企业内用户"
        except Exception as e:  # noqa: BLE001
            last = str(e)
    return None, last


def _tenant_token(app_id: str, app_secret: str) -> str:
    r = requests.post(TOKEN_URL, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"tenant_access_token 失败: {d.get('msg')}")
    return d["tenant_access_token"]


def send_text(app_id: str, app_secret: str, receive_id_type: str, receive_id: str, text: str) -> tuple[bool, str]:
    tok = _tenant_token(app_id, app_secret)
    r = requests.post(
        MSG_URL, params={"receive_id_type": receive_id_type},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": text})},
        timeout=10,
    )
    d = r.json()
    return (d.get("code") == 0, d.get("msg", "") or d.get("data", {}).get("message_id", ""))


def _last24h(csv_path: str, threshold: float) -> dict:
    cutoff = (time.time() - 86400) * 1000
    agg: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    ts = int(row["ts"])
                    if ts < cutoff:
                        continue
                    mk = row["market"]
                    net = float(row["net_bps"])
                except (KeyError, ValueError):
                    continue
                a = agg.setdefault(mk, {"n": 0, "opp": 0, "best": -1e18})
                a["n"] += 1
                if net > threshold:
                    a["opp"] += 1
                a["best"] = max(a["best"], net)
    return agg


def build_message() -> str:
    thr = cfg.min_net_bps
    rep = build_report(cfg.csv_path, thr)
    d24 = _last24h(cfg.csv_path, thr)
    L = ["📊 CrossArb 影子日报", f"阈值 net>{thr:g}bps · 看板 https://dex.hustle2026.xyz/report", "",
         "【近24小时·按机会高到低】"]
    # 按近24h机会数降序;机会数相同则按最佳net降序(最有价值的市场排最前)
    markets_sorted = sorted(
        rep["markets"],
        key=lambda m: (
            d24.get(m["market"], {}).get("opp", 0),
            d24.get(m["market"], {}).get("best", -1e18),
        ),
        reverse=True,
    )
    for m in markets_sorted:
        a = d24.get(m["market"], {"n": 0, "opp": 0, "best": None})
        best = f"{a['best']:.1f}" if a["n"] else "—"
        flag = " ⚠有机会" if a["opp"] > 0 else ""
        L.append(f"· {m['market'].replace('BASE:', '')}: 样本{a['n']} 机会{a['opp']} 最佳net {best}bps{flag}")
    t = rep["totals"]
    L += ["", "【累计】",
          f"· 样本 {t['samples']} · 达标机会 {t['opp_count']} ({t['opp_rate_pct']}%)",
          f"· 假设累计净值 ${rep['est_total_pnl']} · 机会段 {rep['episode_count']} 次"]
    if rep["best_episodes"]:
        e = rep["best_episodes"][0]
        L.append(f"· 最佳单段 {e['market'].replace('BASE:', '')} 入场{e['entry_net']}bps 估${e['pnl']}")
    return "\n".join(L)


def main():
    app_id, secret = cfg.feishu_app_id, cfg.feishu_app_secret
    if not (app_id and secret):
        print("飞书未配置(APP_ID/APP_SECRET),跳过")
        return
    # 收件人优先级:email(与应用无关) > mobile(解析为本应用open_id) > 直接open_id
    if cfg.feishu_email:
        rtype, rid = "email", cfg.feishu_email
    elif cfg.feishu_mobile:
        oid, err = resolve_open_id_by_mobile(app_id, secret, cfg.feishu_mobile)
        if not oid:
            print(f"手机号→open_id 解析失败: {err}（应用需开'通过手机号/邮箱获取用户ID'权限,且用户在企业内）")
            return
        rtype, rid = "open_id", oid
    elif cfg.feishu_open_id:
        rtype, rid = "open_id", cfg.feishu_open_id
    else:
        print("未配置收件人(EMAIL/MOBILE/OPEN_ID),跳过")
        return
    try:
        text = build_message()
        ok, detail = send_text(app_id, secret, rtype, rid, text)
        print(f"飞书发送({rtype}):", "OK " + str(detail) if ok else "失败 " + str(detail))
    except Exception as e:  # noqa: BLE001
        print("飞书播报异常:", type(e).__name__, e)


if __name__ == "__main__":
    main()
