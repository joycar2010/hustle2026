#!/usr/bin/env python3
"""research_inbox_importer —— C-control 主动拉取 LAB artifact 并验签入库(PACK-01 §11.2,LP4)。

信任边界(§3.3):C 主动拉,LAB 不推;C 验签/hash/schema/expiry/revision/scope 六道校验后
才写 production_research_import(仅记录,不授权);真钱授权走后续人工WorkItem+Passkey(§11.2)。
C 拒绝:未知schema/过期/撤回/旧Revision/scope超提案/LAB请求直接开真钱(§11.2)。

用法:
  python3 research_inbox_importer.py pull    # 从dd拉+验签+入库
  python3 research_inbox_importer.py list
运行环境:C机,需 DD_LAB_TOKEN + LAB_ARTIFACT_HMAC_KEY(.env);
SG未开通时pull优雅报连接失败,不崩(§21)。
"""
import hashlib
import hmac as hmac_mod
import json
import os
import sys
import time

import asyncpg
import httpx

DD_URL = os.environ.get("DD_LAB_URL", "http://13.230.29.158:8700")
DD_TOKEN = os.environ.get("DD_LAB_TOKEN", "")
HMAC_KEY = os.environ.get("LAB_ARTIFACT_HMAC_KEY", "")
PG_DSN = os.environ.get("DCM_PG_DSN", "")

KNOWN_TYPES = {"LAB_RUN_COMPLETED", "LAB_EVIDENCE_UPDATED", "LAB_VERDICT_PUBLISHED",
               "LAB_VERDICT_RETRACTED", "LAB_REOPEN_REVIEW_REQUESTED",
               "LAB_GRADUATION_PROPOSAL", "LAB_MODEL_RELEASE_DRAFT"}
KNOWN_SCHEMA = {3}

DDL = """
CREATE TABLE IF NOT EXISTS production_research_import (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    subject_code TEXT NOT NULL,
    revision_id TEXT,
    schema_version INT,
    payload JSONB,
    requested_target_capability TEXT,
    requested_scope TEXT,
    artifact_hash TEXT,
    signing_key_id TEXT,
    verify_status TEXT NOT NULL,
    reject_reason TEXT,
    generated_at BIGINT,
    expires_at BIGINT,
    imported_at TIMESTAMPTZ DEFAULT now(),
    review_status TEXT DEFAULT 'PENDING'
        CHECK(review_status IN ('PENDING','APPROVED','REJECTED','NO_ACTION')),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ
);
"""


def _canon(d: dict) -> str:
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def verify(a: dict) -> tuple:
    """六道校验。返回 (status, reason)。status=VERIFIED|REJECTED。"""
    if a.get("artifact_type") not in KNOWN_TYPES:
        return "REJECTED", f"unknown_type:{a.get('artifact_type')}"
    if a.get("schema_version") not in KNOWN_SCHEMA:
        return "REJECTED", f"unknown_schema:{a.get('schema_version')}"
    now = int(time.time())
    if a.get("expires_at") and now > a["expires_at"]:
        return "REJECTED", "expired"
    # 重算hash:payload在DB里是字符串,还原成dict再canonical
    try:
        payload = json.loads(a["payload"]) if isinstance(a["payload"], str) else a["payload"]
    except Exception:  # noqa: BLE001
        return "REJECTED", "payload_unparseable"
    body = {"artifact_type": a["artifact_type"], "subject_code": a["subject_code"],
            "revision_id": a.get("revision_id"), "schema_version": a["schema_version"],
            "source_environment": a.get("source_environment", "DEX_LAB"), "payload": payload,
            "requested_target_capability": a.get("requested_target_capability"),
            "requested_scope": a.get("requested_scope"),
            "generated_at": a.get("generated_at"), "expires_at": a.get("expires_at"),
            "supersedes_artifact_id": a.get("supersedes_artifact_id")}
    recomputed = hashlib.sha256(_canon(body).encode()).hexdigest()
    if recomputed != a.get("artifact_hash"):
        return "REJECTED", "hash_mismatch"
    if not HMAC_KEY:
        return "REJECTED", "C_missing_hmac_key"
    expect_sig = hmac_mod.new(HMAC_KEY.encode(), recomputed.encode(), hashlib.sha256).hexdigest()
    if not hmac_mod.compare_digest(expect_sig, a.get("signature", "")):
        return "REJECTED", "signature_invalid"
    # LAB 请求直接开真钱=硬拒(§11.2):DRAFT/研究类不得带生产能力请求
    cap = a.get("requested_target_capability")
    if cap and cap not in ("", "None", None) and "READ" not in str(cap):
        return "REJECTED", f"lab_requested_production_capability:{cap}"
    return "VERIFIED", None


async def pull():
    if not PG_DSN:
        print("缺 DCM_PG_DSN"); return
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    await pool.execute(DDL)
    try:
        try:
            async with httpx.AsyncClient(timeout=10) as cli:
                r = await cli.get(f"{DD_URL}/v3/artifacts",
                                  headers={"X-Lab-Token": DD_TOKEN})
                r.raise_for_status()
                arts = r.json().get("artifacts", [])
        except Exception as e:  # noqa: BLE001
            print(f"拉取失败(SG未开通?): {repr(e)[:100]}")
            return
        imported = rejected = 0
        for a in arts:
            status, reason = verify(a)
            if status == "VERIFIED":
                imported += 1
            else:
                rejected += 1
            await pool.execute(
                "INSERT INTO production_research_import(artifact_id, artifact_type, subject_code, "
                "revision_id, schema_version, payload, requested_target_capability, "
                "requested_scope, artifact_hash, signing_key_id, verify_status, reject_reason, "
                "generated_at, expires_at) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12,$13,$14) "
                "ON CONFLICT (artifact_id) DO NOTHING",
                a["artifact_id"], a["artifact_type"], a["subject_code"], a.get("revision_id"),
                a.get("schema_version"),
                a["payload"] if isinstance(a["payload"], str) else json.dumps(a["payload"]),
                a.get("requested_target_capability"), a.get("requested_scope"),
                a.get("artifact_hash"), a.get("signing_key_id"), status, reason,
                a.get("generated_at"), a.get("expires_at"))
            print(f"  [{status}] {a['artifact_id']} {a['artifact_type']}"
                  + (f" REJECT={reason}" if reason else ""))
        print(f"pull: {len(arts)}个artifact,verified={imported} rejected={rejected}")
    finally:
        await pool.close()


async def list_imports():
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    await pool.execute(DDL)
    try:
        for r in await pool.fetch(
                "SELECT artifact_id, artifact_type, subject_code, verify_status, "
                "reject_reason, review_status FROM production_research_import "
                "ORDER BY imported_at DESC LIMIT 20"):
            print(dict(r))
    finally:
        await pool.close()


if __name__ == "__main__":
    import asyncio
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    asyncio.run(pull() if cmd == "pull" else list_imports())
