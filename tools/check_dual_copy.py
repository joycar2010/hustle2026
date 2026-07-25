#!/usr/bin/env python3
"""B机双写纪律对账(2026-07-25):exec服务跑仓库根副本,src/services/exec-kernel是git镜像——
两处必须一致。本脚本每日对账,漂移即飞书warn(经dcm_common Notifier)+退出码1。
crontab: 7 9 * * * /home/ec2-user/dexcexmix/venv/bin/python /home/ec2-user/dexcexmix/tools/check_dual_copy.py
"""
import hashlib
import os
import sys

ROOT = "/home/ec2-user/dexcexmix"
SRC = f"{ROOT}/src/services/exec-kernel"
# root 与 src 都应存在且一致的运行时文件
DUAL = ["manager.py", "recon.py", "opener.py", "runner.py", "repair.py", "exec_core.py",
        "real_venue.py", "store.py", "policy_client.py", "canary_c2.py",
        "recon_orphan_handler.py", "recon_qty_handler.py"]


def md5(p):
    with open(p, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def main():
    drift = []
    for f in DUAL:
        rp, sp = f"{ROOT}/{f}", f"{SRC}/{f}"
        if not os.path.exists(rp):
            drift.append(f"{f}: root缺失")
        elif not os.path.exists(sp):
            drift.append(f"{f}: src缺失")
        elif md5(rp) != md5(sp):
            drift.append(f"{f}: md5不一致")
    if not drift:
        print("dual-copy OK: 12文件root=src全一致")
        return 0
    msg = "B机root vs src副本漂移: " + "; ".join(drift) + " —— 改必双写纪律被违反,须立即同步(root=运行真相)"
    print("DRIFT:", msg)
    try:
        sys.path.insert(0, f"{ROOT}/src/packages/dcm-common")
        from dcm_common.notify import Notifier
        Notifier(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.95:6379/0"),
                 "dual-copy-check").fire("drift", "双写副本漂移", msg, level="warn")
    except Exception as e:  # noqa: BLE001
        print("notify fail:", e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
