#!/usr/bin/env python3
"""一次性生成器:从盘上 sqlite_master 逐字取第二代严谨表 DDL,改写为 IF NOT EXISTS,
产出代码自有 schema 模块 lab_schema.py。不改任何数据;只读 DB。"""
import sqlite3, os, re

DB = os.path.expanduser("~/dexlab/dexlab.db")
STRICT = ["lab_run_plans", "lab_run_manifests", "lab_redemption_models",
          "lab_episodes", "lab_validation_gate_results"]  # 依赖序:plans 先于 manifests
SCHEMA_VERSION = 2

def idem(sql, typ):
    if typ == "table":
        return re.sub(r"^CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", sql, count=1)
    return re.sub(r"^CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", sql, count=1)

c = sqlite3.connect(DB)
blocks = []
for name in STRICT:
    row = c.execute("SELECT sql FROM sqlite_master WHERE type=\"table\" AND name=?", (name,)).fetchone()
    assert row and row[0], "missing table DDL: %s" % name
    blocks.append(idem(row[0].strip(), "table") + ";")
    for iname, isql in c.execute(
            "SELECT name,sql FROM sqlite_master WHERE type=\"index\" AND tbl_name=? AND sql IS NOT NULL ORDER BY name", (name,)):
        blocks.append(idem(isql.strip(), "index") + ";")
ddl = "\n\n".join(blocks)

out = []
out.append("\"\"\"lab_schema.py — 第二代严谨表(plan/manifest/redemption/episode/gate)的代码自有 DDL。")
out.append("此前它们是孤儿 DDL(某次 pack apply 建表,全库代码零引用)。此模块收编为代码所有,")
out.append("全部 CREATE ... IF NOT EXISTS:对已存在的 live 库零作用,仅令真库可从代码重建。")
out.append("DDL 逐字取自盘上 sqlite_master(gen_schema.py 生成),唯一改动=补 IF NOT EXISTS。\"\"\"")
out.append("import time")
out.append("")
out.append("SCHEMA_VERSION = %d  # 2 = 含第二代严谨表(plan->manifest 主脊)" % SCHEMA_VERSION)
out.append("")
out.append("DDL_V2 = \"\"\"")
out.append(ddl)
out.append("\"\"\"")
out.append("")
out.append("")
out.append("def ensure_v2(conn):")
out.append("    \"\"\"幂等:建表(IF NOT EXISTS)+ 盖版本戳。调用点在 main._init() 的 executescript(_DDL) 之后。\"\"\"")
out.append("    conn.executescript(DDL_V2)")
out.append("    conn.execute(\"PRAGMA user_version = %d\" % SCHEMA_VERSION)")
out.append("    conn.execute(\"INSERT OR REPLACE INTO lab_meta(key,value) VALUES(\x27schema_version\x27,?)\", (str(SCHEMA_VERSION),))")
out.append("    conn.execute(\"INSERT OR IGNORE INTO lab_meta(key,value) VALUES(\x27mig_v62_strict_tables\x27,?)\", (str(int(time.time())),))")
out.append("")
open(os.path.expanduser("~/dexlab/lab_schema.py"), "w", encoding="utf-8").write("\n".join(out))
print("lab_schema.py written, %d bytes; %d DDL statements" % (
    os.path.getsize(os.path.expanduser("~/dexlab/lab_schema.py")), ddl.count(";")))
