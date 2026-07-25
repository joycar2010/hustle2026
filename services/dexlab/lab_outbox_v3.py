#!/usr/bin/env python3
"""lab_outbox_v3 —— 签名不可变 research artifact(PACK-01 §11.1,LP4 LAB侧)。

铁律:①artifact不可变(hash+HMAC签名,内容改=新artifact+supersede链);
②Outbox无任何下单/Intent/生产配置接口;③签名key(LAB_ARTIFACT_HMAC_KEY)
与交易永不共用;④C端用同key验签(对称HMAC v1,非对称留升级)。

用法:
  python3 lab_outbox_v3.py publish-model-release   # 把最新model release发成artifact
  python3 lab_outbox_v3.py list
"""
import hashlib
import hmac as hmac_mod
import json
import os
import sqlite3
import sys
import time

DB = os.path.expanduser("~/dexlab/dexlab.db")
HMAC_KEY = os.environ.get("LAB_ARTIFACT_HMAC_KEY", "")

DDL = """
CREATE TABLE IF NOT EXISTS research_artifact (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL CHECK(artifact_type IN
        ('LAB_RUN_COMPLETED','LAB_EVIDENCE_UPDATED','LAB_VERDICT_PUBLISHED',
         'LAB_VERDICT_RETRACTED','LAB_REOPEN_REVIEW_REQUESTED','LAB_GRADUATION_PROPOSAL',
         'LAB_MODEL_RELEASE_DRAFT')),
    subject_code TEXT NOT NULL,
    revision_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 3,
    source_environment TEXT NOT NULL DEFAULT 'DEX_LAB',
    payload TEXT NOT NULL,
    evidence_snapshot_hash TEXT,
    requested_target_capability TEXT,
    requested_scope TEXT,
    generated_at INTEGER DEFAULT (strftime('%s','now')),
    expires_at INTEGER,
    supersedes_artifact_id TEXT,
    artifact_hash TEXT NOT NULL,
    signing_key_id TEXT NOT NULL,
    signature TEXT NOT NULL
);
"""


def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(DDL)
    return c


def _canon(d: dict) -> str:
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sign_artifact(body: dict) -> dict:
    """artifact_hash=sha256(canonical body);signature=HMAC(key, artifact_hash)。"""
    if not HMAC_KEY:
        raise SystemExit("缺 LAB_ARTIFACT_HMAC_KEY(.env)")
    ah = hashlib.sha256(_canon(body).encode()).hexdigest()
    sig = hmac_mod.new(HMAC_KEY.encode(), ah.encode(), hashlib.sha256).hexdigest()
    return {**body, "artifact_hash": ah,
            "signing_key_id": "lab-hmac-v1-" + hashlib.sha256(HMAC_KEY.encode()).hexdigest()[:8],
            "signature": sig}


def publish(c, artifact_type, subject_code, revision_id, payload: dict,
            capability=None, scope=None, ttl_days=14, supersedes=None):
    now = int(time.time())
    body = {"artifact_type": artifact_type, "subject_code": subject_code,
            "revision_id": revision_id, "schema_version": 3,
            "source_environment": "DEX_LAB", "payload": payload,
            "requested_target_capability": capability, "requested_scope": scope,
            "generated_at": now, "expires_at": now + ttl_days * 86400,
            "supersedes_artifact_id": supersedes}
    signed = sign_artifact(body)
    aid = f"art-{signed['artifact_hash'][:16]}"
    c.execute("INSERT OR IGNORE INTO research_artifact(artifact_id, artifact_type, subject_code, "
              "revision_id, schema_version, source_environment, payload, "
              "requested_target_capability, requested_scope, generated_at, expires_at, "
              "supersedes_artifact_id, artifact_hash, signing_key_id, signature) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (aid, artifact_type, subject_code, revision_id, 3, "DEX_LAB",
               json.dumps(payload, ensure_ascii=False), capability, scope,
               now, body["expires_at"], supersedes,
               signed["artifact_hash"], signed["signing_key_id"], signed["signature"]))
    c.commit()
    return aid


def publish_model_release():
    c = _db()
    rel = c.execute("SELECT * FROM lab_model_release ORDER BY created_at DESC LIMIT 1").fetchone()
    if not rel:
        print("无model release"); return
    payload = {
        "release_id": rel["release_id"], "model_version": rel["model_version"],
        "release_status": rel["release_status"],
        "observation_starts_at": rel["observation_starts_at"],
        "observation_days_required": rel["observation_days_required"],
        "certifications": json.loads(rel["certifications_json"] or "{}"),
        "note": "DRAFT通报:四项认证全过,30天观察钟已起跑;非毕业提案,不请求任何生产能力"}
    aid = publish(c, "LAB_MODEL_RELEASE_DRAFT", "C2H.CROSS_VENUE_FUNDING_DISCOVERY",
                  rel["subject_revision_id"], payload,
                  capability=None, scope="research_only")
    print(f"published: {aid} (LAB_MODEL_RELEASE_DRAFT, {rel['release_id']})")
    c.close()


def list_all():
    c = _db()
    for r in c.execute("SELECT artifact_id, artifact_type, subject_code, generated_at, "
                       "expires_at FROM research_artifact ORDER BY generated_at DESC LIMIT 20"):
        print(dict(r))
    c.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "publish-model-release":
        publish_model_release()
    else:
        list_all()
