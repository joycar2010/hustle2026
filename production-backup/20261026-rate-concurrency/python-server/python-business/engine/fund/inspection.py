"""抗延迟定期巡检 —— 汇总点差护栏成效 + 借币二次确认放弃 + 时钟偏差 + feed 健康,
写入 coinadmin 后台跑马灯(NotificationLog channel=marquee,首行摘要+详情),WARN 时飞书告警。

数据源:
  · 点差引擎护栏计数 = Redis `engine:throughput`(rust 每 30s 写)
  · 借币二次确认放弃 = Position FAILED 且 error_message 含 'before borrow'/'after delay'(近1h)
  · 时钟偏差 = 本机↔币安 serverTime;点差源(95)摄入龄 = BTC ts vs 币安
  · feed 健康 = Redis spreads 币种数
多 worker 用 redis NX 锁,每周期仅一个真正执行。每次删旧巡检条插新,跑马灯只留最新一条。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time

import httpx
from sqlalchemy import func

from app.db.models import GlobalRules
from app.db.models_notify import NotificationLog
from app.db.session import SessionLocal
from engine.models import Position

logger = logging.getLogger(__name__)

LOCK_KEY = "inspection_run_lock"
MARQUEE_TITLE = "抗延迟巡检"
SERVER_TIME_URL = "https://fapi.binance.com/fapi/v1/time"


def _db_metrics():
    db = SessionLocal()
    try:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        aborts = db.query(func.count(Position.id)).filter(
            Position.status == "FAILED",
            Position.updated_at >= since,
            (Position.error_message.ilike("%before borrow%") | Position.error_message.ilike("%after delay%")),
        ).scalar() or 0
        g = db.query(GlobalRules).first()
        buf = float(g.open_spread_buffer) if g and g.open_spread_buffer is not None else 0.0
        msp = float(g.max_spread_pct) if g and g.max_spread_pct is not None else 0.0
        return int(aborts), buf, msp
    finally:
        db.close()


def _write_marquee(detail: str):
    db = SessionLocal()
    try:
        # 删旧巡检条 → 跑马灯只留最新一条(其他来源如文档变动不动)
        db.query(NotificationLog).filter(
            NotificationLog.channel == "marquee",
            NotificationLog.template_name == MARQUEE_TITLE,
        ).delete(synchronize_session=False)
        db.add(NotificationLog(template_name=MARQUEE_TITLE, channel="marquee", status="sent", content=detail))
        db.commit()
    finally:
        db.close()


async def run_inspection(redis, notifier) -> None:
    # 多 worker 去重:每周期仅一个执行
    try:
        if redis is not None and not await redis.set(LOCK_KEY, "1", nx=True, ex=1700):
            return
    except Exception:
        pass

    warns: list[str] = []
    lines: list[str] = []

    # 1) 点差引擎护栏计数(rust → Redis)
    tput = None
    try:
        raw = await redis.get("engine:throughput") if redis is not None else None
        if raw:
            tput = json.loads(raw)
    except Exception:
        pass
    if tput:
        age = int(time.time() * 1000) - int(tput.get("ts", 0))
        if age > 120000:
            warns.append("点差引擎吞吐上报过期(>2min,引擎可能停更)")
        lines.append(
            f"点差护栏(近30s窗): 发布 {tput.get('publishes')} · 活跃 {tput.get('active_pairs')} 币 | "
            f"stale跳过 {tput.get('stale_skipped')} · 冻结跳过 {tput.get('frozen_skipped')} · 背离跳过 {tput.get('divergent_skipped')}"
        )
    else:
        warns.append("无 engine:throughput(点差引擎未上报护栏计数)")
        lines.append("点差护栏: 无吞吐上报")

    # 2) 时钟偏差 + feed 摄入龄
    skew = None
    feed_age = None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            server = int((await c.get(SERVER_TIME_URL)).json()["serverTime"])
        skew = int(time.time() * 1000) - server
        if abs(skew) > 2000:
            warns.append(f"交易主机时钟偏差 {skew}ms(>2s,查 NTP)")
        try:
            btc = await redis.hget("spreads", "BTCUSDT") if redis is not None else None
            if btc:
                feed_age = server - int(json.loads(btc)["ts"])
                if abs(feed_age) > 5000:
                    warns.append(f"点差源(95)摄入龄 {feed_age}ms(>5s,查 95 NTP/feed)")
        except Exception:
            pass
        lines.append(f"时钟: 本机↔币安 {skew}ms" + (f" · 点差源摄入龄 {feed_age}ms" if feed_age is not None else ""))
    except Exception as e:
        warns.append("时钟检查失败(取币安时间异常)")
        lines.append(f"时钟: 检查失败 {str(e)[:40]}")

    # 3) DB:借币二次确认放弃 + 护栏配置 + feed 币种数
    try:
        aborts, buf, msp = await asyncio.to_thread(_db_metrics)
    except Exception as e:
        aborts, buf, msp = -1, 0.0, 0.0
        logger.debug(f"db metrics failed: {e}")
    lines.append(f"借币二次确认放弃(近1h): {aborts} 笔 | 开仓缓冲 {buf}% · 坏价护栏 {msp}%")
    feed_n = None
    try:
        feed_n = await redis.hlen("spreads") if redis is not None else None
        lines.append(f"点差 feed: {feed_n} 币种")
    except Exception:
        pass

    # 4) 汇总
    status = "WARN" if warns else "OK"
    icon = "⚠️" if warns else "✅"
    skew_s = f"{skew}ms" if skew is not None else "?"
    frozen_s = (tput or {}).get("frozen_skipped", "?")
    summary = (f"{icon} 抗延迟巡检 {status}: 时钟 {skew_s} · 冻结跳过 {frozen_s}/30s · "
               f"借币放弃 {aborts}/1h · feed {feed_n if feed_n is not None else '?'} 币")
    if warns:
        summary += " · 异常: " + "; ".join(warns)
    detail = summary + "\n\n" + "\n".join(f"· {x}" for x in lines)
    if warns:
        detail += "\n\n异常项:\n" + "\n".join(f"⚠ {w}" for w in warns)
    detail += f"\n\n巡检时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}(每 30 分钟自动巡检)"

    # 5) 写跑马灯(首行=summary,点击看 detail)+ 实时广播 + WARN 飞书
    try:
        await asyncio.to_thread(_write_marquee, detail)
    except Exception as e:
        logger.warning(f"write marquee failed: {e}")
    try:
        if redis is not None:
            await redis.publish("notification:broadcast", json.dumps({
                "title": MARQUEE_TITLE, "content": summary,
                "priority": 1 if warns else 3,
                "color": "#ef4444" if warns else "#22c55e",
                "blink": bool(warns), "sound": "alert" if warns else "none",
            }))
    except Exception:
        pass
    if warns:
        try:
            await notifier.send(f"抗延迟巡检 {status}", detail)
        except Exception:
            pass
    logger.info(f"Inspection done: {status} ({len(warns)} warns)")
