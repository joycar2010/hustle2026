"""有状态 Incident 引擎(批次1,V5 §17/ADR-008 去噪)。

同一 (venue, account, rule) 聚合为一个 Incident,只在四个时点通知:
  发生(OPEN)/ 升级(severity warn→fatal → ESCALATED)/ 恢复(RECOVERING 驻留满→CLOSED)/ 超时未处理(重提醒)。
持续命中只累加 hit_count 不出声——错误码逐条轰炸在此终结。
恢复带迟滞:条件消失先进 RECOVERING,驻留 DWELL 秒内复发则回 OPEN(不重复通知);
驻留满才 CLOSED+通知恢复。CLOSED 后复发=新行(历史不可变)。
铁律:本模块只写 venue_incident + 调用 fire,绝不动策略/仓位。
"""
import os
import time

RECOVER_DWELL_SEC = int(os.environ.get("DCM_INCIDENT_DWELL_SEC", "1800"))     # 恢复驻留(迟滞)
REMIND_SEC = int(os.environ.get("DCM_INCIDENT_REMIND_SEC", "14400"))          # OPEN 超时重提醒(4h)
_RANK = {"warn": 0, "fatal": 1}


async def touch(pool, fire, venue: str, rule: str, severity: str, title: str,
                detail: str, account_key: str = ""):
    """条件命中:开新 Incident(通知)/ 已有则累加;severity 升级→ESCALATED(通知);
    RECOVERING 中复发→回 OPEN(迟滞,不通知);OPEN 超 REMIND_SEC 未动→重提醒。"""
    if pool is None:
        await fire(f"inc:{venue}:{rule}", title, detail, level=severity)
        return
    key = f"{venue}:{account_key}:{rule}"
    row = await pool.fetchrow(
        "SELECT id, state, severity, last_notified_at, extract(epoch from now()-last_notified_at) AS quiet "
        "FROM venue_incident WHERE incident_key=$1 AND state != 'CLOSED'", key)
    if row is None:
        await pool.execute(
            "INSERT INTO venue_incident(incident_key,venue,account_key,rule,severity,title,detail,last_notified_at) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,now()) ON CONFLICT DO NOTHING",
            key, venue, account_key, rule, severity, title, detail[:500])
        await fire(f"inc:{key}", f"[Incident发生] {title}", detail, level=severity)
        return
    escalate = _RANK.get(severity, 0) > _RANK.get(row["severity"], 0)
    reopen = row["state"] == "RECOVERING"
    remind = (row["state"] in ("OPEN", "ESCALATED")
              and float(row["quiet"] or 0) > REMIND_SEC)
    await pool.execute(
        "UPDATE venue_incident SET last_seen=now(), hit_count=hit_count+1, detail=$2, "
        "severity=(CASE WHEN $3 THEN $4 ELSE severity END), "
        "state=(CASE WHEN $3 THEN 'ESCALATED' WHEN state='RECOVERING' THEN 'OPEN' ELSE state END), "
        "escalated_at=(CASE WHEN $3 THEN now() ELSE escalated_at END), "
        "recovering_at=(CASE WHEN state='RECOVERING' THEN NULL ELSE recovering_at END), "
        "last_notified_at=(CASE WHEN $3 OR $5 THEN now() ELSE last_notified_at END) "
        "WHERE id=$1", row["id"], detail[:500], escalate, severity, remind)
    if escalate:
        await fire(f"inc:{key}:esc", f"[Incident升级] {title}", detail, level="fatal")
    elif remind:
        await fire(f"inc:{key}:remind", f"[Incident超时未处理] {title}",
                   f"已持续未恢复,累计命中{row['id'] and ''}{detail[:300]}", level=severity)
    # reopen(迟滞回OPEN)故意不通知——防 NORMAL/WATCH 抖动轰炸


async def resolve(pool, fire, venue: str, rule: str, account_key: str = ""):
    """条件消失:OPEN/ESCALATED→RECOVERING(开始驻留);RECOVERING 驻留满→CLOSED+通知恢复。"""
    if pool is None:
        return
    key = f"{venue}:{account_key}:{rule}"
    row = await pool.fetchrow(
        "SELECT id, state, title, extract(epoch from now()-recovering_at) AS dwell "
        "FROM venue_incident WHERE incident_key=$1 AND state != 'CLOSED'", key)
    if row is None:
        return
    if row["state"] in ("OPEN", "ESCALATED"):
        await pool.execute("UPDATE venue_incident SET state='RECOVERING', recovering_at=now() WHERE id=$1",
                           row["id"])
    elif row["state"] == "RECOVERING" and float(row["dwell"] or 0) >= RECOVER_DWELL_SEC:
        await pool.execute("UPDATE venue_incident SET state='CLOSED', closed_at=now() WHERE id=$1", row["id"])
        await fire(f"inc:{key}:ok", f"[Incident恢复] {row['title']}",
                   f"条件已消失并驻留满 {RECOVER_DWELL_SEC//60}min,Incident 关闭", level="warn")


async def active_summary(pool) -> list:
    """活跃 Incident 摘要(供 dcm:risk:status / UI)。"""
    if pool is None:
        return []
    try:
        rows = await pool.fetch(
            "SELECT venue, account_key, rule, state, severity, title, hit_count, "
            "extract(epoch from now()-first_seen)::int AS age_sec "
            "FROM venue_incident WHERE state != 'CLOSED' ORDER BY severity DESC, first_seen")
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []
