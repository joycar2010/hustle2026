"""极简 SQL 迁移器(禁 create_all 纪律的执行工具)。

按文件名序应用 db/migrations/*.sql,每个文件一个事务,applied 记录在 schema_migrations。
幂等:已应用的跳过。用法:
    set -a; . ~/dexcexmix/.env; set +a
    ~/dexcexmix/venv/bin/python ~/dexcexmix/src/db/migrate.py
"""
import asyncio
import os
import pathlib
import sys

import asyncpg

DSN = os.environ.get("DCM_PG_DSN", "")
MIG_DIR = pathlib.Path(__file__).parent / "migrations"


async def main():
    if not DSN:
        print("FATAL: DCM_PG_DSN 未设置")
        sys.exit(1)
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations("
            "name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        applied = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
        files = sorted(p for p in MIG_DIR.glob("*.sql"))
        ran = 0
        for f in files:
            if f.name in applied:
                continue
            sql = f.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations(name) VALUES($1)", f.name)
            print(f"APPLIED {f.name}")
            ran += 1
        print(f"MIGRATE_OK applied={ran} total={len(files)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
