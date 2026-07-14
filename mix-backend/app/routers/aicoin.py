"""AiCoin 行情接口(自 testgo backend/app/api/v1/aicoin.py + services/aicoin_client.py 移植)。

- 配置权威 = mix_main.aicoin_config(id=1 单行;首次保存自动建表),60s 进程内缓存热生效。
- /aicoin/kline /aicoin/coin-search = 只读代理(签名在服务端,secret 绝不下发前端)。
- 凭据从 https://open.aicoin.com 获取;测试连接走 distributor/quota。
"""
import base64
import hashlib
import hmac
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import require_viewer, require_admin
from .. import datasources as ds

router = APIRouter()

_PERIOD_TO_SECONDS = {"1": "60", "5": "300", "15": "900", "30": "1800",
                      "60": "3600", "240": "14400", "1440": "86400"}
_cache: dict = {"client": None, "key": "", "secret": "", "ts": 0}
_TTL = 60

_DDL = """CREATE TABLE IF NOT EXISTS aicoin_config (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    api_key TEXT NOT NULL DEFAULT '',
    api_secret TEXT NOT NULL DEFAULT '',
    api_base TEXT NOT NULL DEFAULT 'https://open.aicoin.com',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""


class AiCoinClient:
    """AiCoin OpenAPI 签名客户端(HMAC-SHA1→b64,testgo 实现原样)。"""

    def __init__(self, api_key: str, api_secret: str, base: str = "https://open.aicoin.com"):
        self.api_key, self.api_secret, self.base = api_key, api_secret, base or "https://open.aicoin.com"

    def _sign(self) -> dict:
        nonce = uuid.uuid4().hex[:16]
        ts = str(int(time.time()))
        pre = f"AccessKeyId={self.api_key}&SignatureNonce={nonce}&Timestamp={ts}"
        sig = base64.b64encode(hmac.new(self.api_secret.encode(), pre.encode(),
                                        hashlib.sha1).hexdigest().encode()).decode()
        return {"AccessKeyId": self.api_key, "SignatureNonce": nonce, "Timestamp": ts, "Signature": sig}

    async def _get(self, path: str, params: dict | None = None) -> dict:
        q = self._sign()
        if params:
            q.update(params)
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{self.base}{path}", params=q)
            r.raise_for_status()
            body = r.json()
            if not body.get("success", True) and body.get("errorCode") not in (200, None):
                raise RuntimeError(f"AiCoin {body.get('errorCode')}: {body.get('error')}")
            return body

    async def kline(self, symbol: str, period: str, size: int = 300) -> list:
        d = await self._get("/api/v2/commonKline/dataRecords",
                            {"symbol": symbol, "period": period, "size": str(min(size, 500))})
        k = d.get("data", {})
        return k.get("kline_data", []) if isinstance(k, dict) else (k if isinstance(k, list) else [])

    async def search(self, kw: str) -> list:
        d = await self._get("/api/upgrade/v2/coin/search", {"search": kw, "page": "1", "page_size": "20"})
        r = d.get("data", {})
        return r.get("list", []) if isinstance(r, dict) else (r if isinstance(r, list) else [])

    async def quota(self) -> dict:
        d = await self._get("/api/upgrade/v2/distributor/quota")
        return d.get("data", d)


async def _load_row():
    pool = await ds.pg_main()
    if pool is None:
        return None
    try:
        return await pool.fetchrow("SELECT * FROM aicoin_config WHERE id=1")
    except Exception:  # noqa: BLE001  # 表未建
        return None


async def _client():
    now = time.time()
    if _cache["client"] is None or now - _cache["ts"] > _TTL:
        row = await _load_row()
        if not row or not row["enabled"] or not row["api_key"] or not row["api_secret"]:
            _cache.update({"client": None, "key": "", "secret": "", "ts": now})
            return None
        if row["api_key"] != _cache["key"] or row["api_secret"] != _cache["secret"]:
            _cache.update({"client": AiCoinClient(row["api_key"], row["api_secret"], row["api_base"]),
                           "key": row["api_key"], "secret": row["api_secret"]})
        _cache["ts"] = now
    return _cache["client"]


@router.get("/system/aicoin-config")
async def aicoin_config_get(_who=Depends(require_viewer)):
    row = await _load_row()
    if not row:
        return {"configured": False, "enabled": False, "api_key": "", "api_base": "https://open.aicoin.com"}
    sec = row["api_secret"] or ""
    return {"configured": bool(row["api_key"] and sec), "enabled": row["enabled"],
            "api_key": row["api_key"], "api_secret_masked": (sec[:4] + "••••" + sec[-4:]) if len(sec) > 8 else "已设置",
            "api_base": row["api_base"], "expires_at": row["expires_at"],
            "updated_by": row["updated_by"], "updated_at": str(row["updated_at"] or "")}


@router.post("/system/aicoin-config")
async def aicoin_config_save(body: dict, admin=Depends(require_admin)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    await pool.execute(_DDL)
    key = str(body.get("api_key") or "").strip()
    sec = str(body.get("api_secret") or "").strip()
    if not key or not sec:
        raise HTTPException(400, "AccessKeyId 与 Secret Key 必填(留空不修改语义不支持,防误存半套凭据)")
    await pool.execute(
        "INSERT INTO aicoin_config(id, api_key, api_secret, api_base, enabled, expires_at, updated_by, updated_at) "
        "VALUES(1,$1,$2,$3,$4,$5,$6,now()) ON CONFLICT (id) DO UPDATE SET api_key=$1, api_secret=$2, "
        "api_base=$3, enabled=$4, expires_at=$5, updated_by=$6, updated_at=now()",
        key, sec, str(body.get("api_base") or "https://open.aicoin.com").strip(),
        bool(body.get("enabled", True)), str(body.get("expires_at") or ""), admin.get("admin", ""))
    _cache["ts"] = 0   # 立即失效缓存
    return {"ok": True, "note": "已保存,60s 内全端点生效"}


@router.post("/system/aicoin-config/test")
async def aicoin_config_test(body: dict, _admin=Depends(require_admin)):
    key = str(body.get("api_key") or "").strip()
    sec = str(body.get("api_secret") or "").strip()
    if not key or not sec:
        row = await _load_row()
        if not row:
            raise HTTPException(400, "无已存凭据可测")
        key, sec = row["api_key"], row["api_secret"]
    try:
        q = await AiCoinClient(key, sec, str(body.get("api_base") or "https://open.aicoin.com")).quota()
        return {"ok": True, "quota": q}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


@router.get("/aicoin/kline")
async def aicoin_kline(symbol: str = Query(...), period: str = Query("60"),
                       size: int = Query(300, ge=1, le=500), _who=Depends(require_viewer)):
    ac = await _client()
    if ac is None:
        raise HTTPException(503, "AiCoin 未配置或已禁用:系统配置 → AiCoin 配置")
    try:
        return {"data": await ac.kline(symbol, _PERIOD_TO_SECONDS.get(period, period), size)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AiCoin API error: {str(e)[:150]}")


@router.get("/aicoin/coin-search")
async def aicoin_search(q: str = Query(...), _who=Depends(require_viewer)):
    ac = await _client()
    if ac is None:
        raise HTTPException(503, "AiCoin 未配置或已禁用:系统配置 → AiCoin 配置")
    try:
        return await ac.search(q)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AiCoin API error: {str(e)[:150]}")


_LAB_DDL = """CREATE TABLE IF NOT EXISTS lab_case (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT 'OBSERVE',
    structure TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT '',
    product TEXT NOT NULL DEFAULT '',
    evidence_for TEXT NOT NULL DEFAULT '',
    evidence_against TEXT NOT NULL DEFAULT '',
    invalidation TEXT NOT NULL DEFAULT '',
    review_by TEXT NOT NULL DEFAULT '',
    tail_budget TEXT NOT NULL DEFAULT '',
    aicoin_price TEXT NOT NULL DEFAULT '',
    official_price TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""


@router.post("/aicoin/labcase")
async def labcase_save(body: dict, op=Depends(require_viewer)):
    """人工研判表→LabCase(XurMj 右栏)。规约:全字段必填(OBSERVE 除外);
    控盘置信度=仅人工标签非系统事实;案件只追加不覆盖(复盘用)。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    await pool.execute(_LAB_DDL)
    sym = str(body.get("symbol") or "").strip().upper()
    if not sym:
        raise HTTPException(400, "symbol 必填")
    action = str(body.get("action") or "OBSERVE")
    if action != "OBSERVE":
        for f in ("structure", "confidence", "stage", "product", "invalidation", "review_by", "tail_budget"):
            if not str(body.get(f) or "").strip():
                raise HTTPException(400, f"研判表字段 {f} 必填(规约:LabCase 全必填)")
    row = await pool.fetchrow(
        "INSERT INTO lab_case(symbol, operator, action, structure, confidence, stage, product, "
        "evidence_for, evidence_against, invalidation, review_by, tail_budget, aicoin_price, official_price) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id",
        sym, str(op.get("operator") or op.get("username") or op.get("admin") or "viewer"),
        action, *(str(body.get(k) or "") for k in
                  ("structure", "confidence", "stage", "product", "evidence_for", "evidence_against",
                   "invalidation", "review_by", "tail_budget", "aicoin_price", "official_price")))
    return {"ok": True, "id": row["id"]}


@router.get("/aicoin/labcases")
async def labcase_list(symbol: str = "", _who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return {"rows": []}
    try:
        if symbol:
            rows = await pool.fetch("SELECT * FROM lab_case WHERE symbol=$1 ORDER BY id DESC LIMIT 20",
                                    symbol.upper())
        else:
            rows = await pool.fetch("SELECT * FROM lab_case ORDER BY id DESC LIMIT 20")
        return {"rows": [{k: (str(v) if k == "created_at" else v) for k, v in dict(r).items()} for r in rows]}
    except Exception:
        return {"rows": []}
