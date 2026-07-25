#!/usr/bin/env python3
"""crossarb/data 五源CSV归档(LP1续,§9.2):只读封存+gzip+SHA-256+manifest登记。"""
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import time

SRC = "/home/ec2-user/crossarb/data"
OUT = "/home/ec2-user/lab_archive"
DB = "/home/ec2-user/dexlab/dexlab.db"
stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())

FILES = {
    "ticks.csv": ("src-dc", "dc CrossArb tick明细(9.6M行)"),
    "exec_log.csv": ("src-dc", "dc 真金执行日志(P1 canary)"),
    "dexarb_shadow.csv": ("src-dd-atomic", "dd DEX-DEX atomic shadow(仅3行,594次失败无原始数据)"),
    "options_ticks.csv": ("src-op", "op 期权平价tick(1.6M行,含total_fee_bps)"),
    "cexdex_shadow.csv": ("src-dd-gap", "dd gap survival事件表(665行)"),
    "cexdex_shadow.deanchor_prev.csv": ("src-dd-gap", "去锚版本演进存档"),
    "cexdex_shadow.deadpool_bug.csv": ("src-dd-gap", "死池bug版本存档(假阳性根因物证)"),
}

c = sqlite3.connect(DB)
manifest = {"created_at_utc": stamp, "snapshot_method": "readonly_gzip",
            "host": "dd-13.230.29.158", "items": []}
for fn, (sid, note) in FILES.items():
    p = f"{SRC}/{fn}"
    if not os.path.exists(p):
        print("skip missing", fn)
        continue
    gz = f"{OUT}/{fn}.{stamp}.gz"
    with open(p, "rb") as fi, gzip.open(gz, "wb", compresslevel=1) as fo:
        shutil.copyfileobj(fi, fo, 1024 * 1024)
    h = hashlib.sha256()
    with open(gz, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    rows = sum(1 for _ in open(p, "rb")) - 1
    mid = f"srcmf-{h.hexdigest()[:16]}"
    c.execute("INSERT OR IGNORE INTO lab_source_manifest(manifest_id, source_system_id, "
              "source_kind, snapshot_method, object_uri, object_version, content_sha256, "
              "row_count, null_profile) VALUES(?,?,?,?,?,?,?,?,?)",
              (mid, sid, "CSV", "readonly_gzip",
               f"file://dd{gz} + file://D:/lab_archive/{os.path.basename(gz)}",
               stamp, h.hexdigest(), rows, json.dumps({"note": note,
                "raw_bytes": os.path.getsize(p), "gz_bytes": os.path.getsize(gz)})))
    manifest["items"].append({"name": fn, "object": os.path.basename(gz), "rows": rows,
                              "sha256": h.hexdigest(), "manifest_id": mid})
    print(f"{fn}: rows={rows} gz={os.path.getsize(gz)/1e6:.0f}MB {mid}")
c.commit()
c.close()
with open(f"{OUT}/csv_manifest_{stamp}.json", "w") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)
print("done:", f"{OUT}/csv_manifest_{stamp}.json")
