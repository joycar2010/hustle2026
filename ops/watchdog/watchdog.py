#!/usr/bin/env python3
"""外部 watchdog——独立于 A/B/C,跑在 crossarb-testbox(不同 VPC)。轮询生产面公开健康摘要
https://mix.hustle2026.xyz/api/v1/watchdog;连续 N 次不可达/降级 → 独立飞书通道告警(dcm app),
恢复也报。**只读+只告警,绝不接管下单**(§5.5)。捕获"整个生产面/主告警器同时死"——内部网自己报不了的场景。"""
import json, os, time, urllib.request

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "watchdog", "state.json")
URL = os.environ.get("WATCHDOG_URL", "https://mix.hustle2026.xyz/api/v1/watchdog")
APP_ID = os.environ.get("DCM_FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("DCM_FEISHU_APP_SECRET", "")
OPEN_ID = os.environ.get("DCM_FEISHU_OPEN_ID", "")
FAIL_N = int(os.environ.get("WATCHDOG_FAIL_N", "2"))


def feishu(title, text):
    if not (APP_ID and APP_SECRET and OPEN_ID):
        print("feishu creds missing, skip"); return
    try:
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode(),
            headers={"Content-Type": "application/json"})
        tok = json.loads(urllib.request.urlopen(req, timeout=12).read())["tenant_access_token"]
        body = {"receive_id": OPEN_ID, "msg_type": "text",
                "content": json.dumps({"text": f"[外部watchdog@crossarb] {title}\n{text}"})}
        req2 = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
        urllib.request.urlopen(req2, timeout=12).read()
        print("feishu sent:", title)
    except Exception as e:  # noqa: BLE001
        print("feishu err", repr(e)[:150])


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:  # noqa: BLE001
        return {"fails": 0, "alerted": False}


def probe():
    try:
        d = json.loads(urllib.request.urlopen(URL, timeout=15).read())
        return d.get("ok") is True, d
    except Exception as e:  # noqa: BLE001
        return False, {"error": repr(e)[:150]}


def main():
    ok, d = probe()
    st = load_state()
    if ok:
        if st.get("alerted"):
            feishu("✅生产面已恢复",
                   f"health ok, mode={d.get('global_mode')} services={d.get('services_total')} risk_age={d.get('risk_status_age_sec')}s")
        st = {"fails": 0, "alerted": False}
        print("OK", d.get("global_mode"), d.get("services_total"))
    else:
        st["fails"] = st.get("fails", 0) + 1
        detail = d.get("error") or f"ok=false critical_stale={d.get('critical_stale')} risk_age={d.get('risk_status_age_sec')}s"
        print(f"BAD ({st['fails']}/{FAIL_N}): {detail}")
        if st["fails"] >= FAIL_N and not st.get("alerted"):
            feishu("⚠️生产面不可达/降级",
                   f"连续{st['fails']}次探测失败。{detail}\n建议:登录检查A/B/C。此为独立box告警(主通道可能同时失效)。")
            st["alerted"] = True
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"))


if __name__ == "__main__":
    main()
