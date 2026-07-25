#!/usr/bin/env python3
"""把 2026-07-25 快照登记为正式 lab_source_manifest(LP1 §9.1)。"""
import glob
import json
import sqlite3

mf = sorted(glob.glob('/home/ec2-user/lab_archive/manifest_*.json'))[-1]
m = json.load(open(mf))
c = sqlite3.connect('/home/ec2-user/dexlab/dexlab.db')
for it in m['items']:
    sid = 'src-xv' if it['name'] == 'xv' else 'src-dexlab-kernel'
    if sid == 'src-dexlab-kernel':
        c.execute("INSERT OR IGNORE INTO lab_source_system(source_system_id, legacy_name, "
                  "source_type, host_alias, verification_state) "
                  "VALUES(?, 'dexlab/kernel-db', 'SQLITE', '13.230.29.158:~/dexlab/dexlab.db', "
                  "'DEPLOY_VERIFIED')", (sid,))
    mid = f"srcmf-{it['content_sha256'][:16]}"
    ts_range = it.get('ts_range') or [None, None]
    c.execute(
        "INSERT OR IGNORE INTO lab_source_manifest(manifest_id, source_system_id, source_kind, "
        "snapshot_method, object_uri, object_version, content_sha256, row_count, "
        "min_event_at, max_event_at, null_profile) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (mid, sid, 'SQLITE', m['snapshot_method'],
         f"file://dd/home/ec2-user/lab_archive/{it['object']}"
         f" + file://C/home/ec2-user/backups/lab_archive/{it['object']}",
         m['created_at_utc'], it['content_sha256'], it.get('gaps_rows'),
         ts_range[0], ts_range[1],
         json.dumps({'raw_bytes': it['raw_bytes'], 'gz_bytes': it['gz_bytes']})))
    print('registered', mid, sid, it['object'])
c.commit()
for r in c.execute("SELECT manifest_id, source_system_id, object_version, row_count "
                   "FROM lab_source_manifest"):
    print(dict(zip(('manifest_id', 'source', 'version', 'rows'), r)))
c.close()
