#!/usr/bin/env python3
"""xv/dexlab 一致性快照 v2(LP backlog:常态化 timer 版,2026-07-25)。
SQLite online backup API(不复制在写文件,§9.2铁律)→ gzip → SHA-256 manifest → 轮转 → 条件S3。

v2相对v1:
- OUT改~/lab_archive磁盘(**绝不用/tmp**——dd的/tmp是tmpfs内存盘,2.7GB快照会OOM,LP1血教训)
- 轮转keep-N(默认5),只清xv_/dexlab_/manifest_前缀,不动LP1一次性CSV归档
- 条件S3上传:env S3_BUCKET就绪则aws s3 cp到s3://$BUCKET/lab-archive/$stamp/(fail-open,桶未就绪跳过不崩)
- 只快照会变的xv.db+dexlab.db;冻结CSV(ticks/options/exec_log)LP1已一次性归档不重复
"""
import glob
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time

HOME = os.path.expanduser("~")
OUT = os.path.join(HOME, "lab_archive")  # 磁盘,非tmpfs
KEEP = int(os.environ.get("SNAPSHOT_KEEP", "5"))
S3_BUCKET = os.environ.get("S3_BUCKET", "").strip()
S3_PREFIX = os.environ.get("S3_PREFIX", "lab-archive").strip("/")
os.makedirs(OUT, exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())

manifest = {"created_at_utc": stamp, "snapshot_method": "sqlite_online_backup+gzip",
            "host": "dd-13.230.29.158", "keep": KEEP, "items": []}
produced = []

for name, path in (("xv", os.path.join(HOME, "xv/xv.db")),
                   ("dexlab", os.path.join(HOME, "dexlab/dexlab.db"))):
    if not os.path.exists(path):
        print(f"{name}: SKIP(源不存在 {path})")
        continue
    t0 = time.time()
    snap = f"{OUT}/{name}_{stamp}.db"
    src = sqlite3.connect(path)
    dst = sqlite3.connect(snap)
    src.backup(dst)          # online backup:WAL一致性快照
    dst.close()
    src.close()
    raw_size = os.path.getsize(snap)
    gz = snap + ".gz"
    with open(snap, "rb") as fi, gzip.open(gz, "wb", compresslevel=1) as fo:
        shutil.copyfileobj(fi, fo, 1024 * 1024)
    os.remove(snap)
    h = hashlib.sha256()
    with open(gz, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    meta = {}
    try:
        c = sqlite3.connect(path)
        if name == "xv":
            meta["gaps_rows"] = c.execute("SELECT count(*) FROM gaps").fetchone()[0]
            meta["ts_range"] = list(c.execute("SELECT min(ts), max(ts) FROM gaps").fetchone())
        else:
            meta["tables"] = c.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        c.close()
    except Exception as e:  # noqa: BLE001
        meta["meta_err"] = repr(e)[:80]
    manifest["items"].append({
        "name": name, "source_path": path, "object": os.path.basename(gz),
        "raw_bytes": raw_size, "gz_bytes": os.path.getsize(gz),
        "content_sha256": h.hexdigest(), "snapshot_seconds": round(time.time() - t0, 1),
        **meta})
    produced.append(gz)
    print(f"{name}: raw={raw_size/1e6:.0f}MB gz={os.path.getsize(gz)/1e6:.0f}MB "
          f"sha256={h.hexdigest()[:16]} {round(time.time()-t0,1)}s")

mpath = f"{OUT}/manifest_{stamp}.json"
with open(mpath, "w") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)
produced.append(mpath)
print("manifest:", mpath)

# ---- 轮转:每前缀保留最新KEEP份 ----
for pat in ("xv_*.db.gz", "dexlab_*.db.gz", "manifest_*.json"):
    files = sorted(glob.glob(os.path.join(OUT, pat)))
    for old in files[:-KEEP] if len(files) > KEEP else []:
        try:
            os.remove(old)
            print(f"轮转删除: {os.path.basename(old)}")
        except OSError as e:
            print(f"轮转失败 {old}: {e}")

# ---- 条件S3上传(fail-open) ----
if S3_BUCKET:
    ok = 0
    for p in produced:
        key = f"{S3_PREFIX}/{stamp}/{os.path.basename(p)}"
        try:
            r = subprocess.run(
                ["aws", "s3", "cp", p, f"s3://{S3_BUCKET}/{key}", "--only-show-errors"],
                capture_output=True, text=True, timeout=600)
            if r.returncode == 0:
                ok += 1
            else:
                print(f"S3上传失败 {os.path.basename(p)}: {r.stderr.strip()[:120]}")
        except Exception as e:  # noqa: BLE001
            print(f"S3上传异常 {os.path.basename(p)}: {repr(e)[:120]}")
    print(f"S3: s3://{S3_BUCKET}/{S3_PREFIX}/{stamp}/ 上传{ok}/{len(produced)}件")
else:
    print("S3: 未配置S3_BUCKET,跳过(桶+PutObject授权就绪后设env激活)")
