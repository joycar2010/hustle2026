#!/usr/bin/env python3
"""xv/dexlab 一致性快照(LP1 插队项,2026-07-25)。
SQLite online backup API(不复制正在写的文件,包§9.2铁律)→ gzip → SHA-256 manifest。
产物落 /tmp/lab_archive/,由 C 机拉取(信任方向:生产拉研究,LAB 不持生产凭证)。"""
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import time

OUT = "/tmp/lab_archive"
os.makedirs(OUT, exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())

manifest = {"created_at_utc": stamp, "snapshot_method": "sqlite_online_backup+gzip",
            "host": "dd-13.230.29.158", "items": []}

for name, path in (("xv", "/home/ec2-user/xv/xv.db"),
                   ("dexlab", "/home/ec2-user/dexlab/dexlab.db")):
    t0 = time.time()
    snap = f"{OUT}/{name}_{stamp}.db"
    src = sqlite3.connect(path)
    dst = sqlite3.connect(snap)
    src.backup(dst)          # online backup API:WAL 一致性快照
    dst.close(); src.close()
    raw_size = os.path.getsize(snap)
    gz = snap + ".gz"
    with open(snap, "rb") as fi, gzip.open(gz, "wb", compresslevel=1) as fo:
        shutil.copyfileobj(fi, fo, 1024 * 1024)
    os.remove(snap)
    h = hashlib.sha256()
    with open(gz, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    # 行数/时间边界(轻查询,防止巨表全扫只取关键表)
    meta = {}
    try:
        c = sqlite3.connect(path)
        if name == "xv":
            meta["gaps_rows"] = c.execute("SELECT count(*) FROM gaps").fetchone()[0]
            meta["ts_range"] = list(c.execute("SELECT min(ts), max(ts) FROM gaps").fetchone())
        else:
            meta["tables"] = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        c.close()
    except Exception as e:  # noqa: BLE001
        meta["meta_err"] = repr(e)[:80]
    manifest["items"].append({
        "name": name, "source_path": path, "object": os.path.basename(gz),
        "raw_bytes": raw_size, "gz_bytes": os.path.getsize(gz),
        "content_sha256": h.hexdigest(), "snapshot_seconds": round(time.time() - t0, 1),
        **meta})
    print(f"{name}: raw={raw_size/1e6:.0f}MB gz={os.path.getsize(gz)/1e6:.0f}MB sha256={h.hexdigest()[:16]}…")

mpath = f"{OUT}/manifest_{stamp}.json"
with open(mpath, "w") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)
print("manifest:", mpath)
