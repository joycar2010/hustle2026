import os
import sys
import subprocess
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.middleware.permissions import require_super_admin

router = APIRouter(prefix="/api/admin/system", tags=["admin-system"])

_start_time = time.time()
_BRANCH = "coin"


# ─── System Info ───

@router.get("/info")
def system_info(request: Request):
    require_super_admin(request)

    uptime_sec = int(time.time() - _start_time)
    hours, rem = divmod(uptime_sec, 3600)
    minutes, secs = divmod(rem, 60)

    git_branch = ""
    git_commit = ""
    try:
        git_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        pass

    return {
        "backend_version": "0.5.0",
        "python_version": sys.version.split()[0],
        "db_version": "PostgreSQL",
        "uptime": f"{hours}h {minutes}m {secs}s",
        "git_branch": git_branch,
        "git_commit": git_commit,
    }


# ─── Git Operations (coin branch) ───

class GitPushRequest(BaseModel):
    message: str


def _ensure_coin_branch():
    """Ensure 'coin' branch exists. Create if not."""
    try:
        branches = subprocess.check_output(
            ["git", "branch", "--list", _BRANCH],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        if not branches:
            subprocess.check_output(
                ["git", "branch", _BRANCH],
                stderr=subprocess.DEVNULL, timeout=5,
            )
    except Exception:
        pass


def _get_current_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        return "main"


@router.get("/git-history")
def git_history(request: Request):
    require_super_admin(request)

    try:
        _ensure_coin_branch()
        output = subprocess.check_output(
            ["git", "log", _BRANCH, "--oneline", "--format=%H|%h|%s|%an|%ai", "-20"],
            stderr=subprocess.DEVNULL, timeout=10,
        ).decode().strip()

        commits = []
        for line in output.split("\n"):
            if not line:
                continue
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "message": parts[2],
                    "author": parts[3],
                    "date": parts[4],
                })
        return commits
    except Exception:
        return []


@router.post("/git-push")
def git_push(req: GitPushRequest, request: Request):
    require_super_admin(request)

    original_branch = _get_current_branch()
    _ensure_coin_branch()

    try:
        subprocess.check_output(["git", "stash"], stderr=subprocess.STDOUT, timeout=10)
        subprocess.check_output(["git", "checkout", _BRANCH], stderr=subprocess.STDOUT, timeout=10)
        subprocess.check_output(
            ["git", "merge", original_branch, "--no-edit", "-X", "theirs"],
            stderr=subprocess.STDOUT, timeout=30,
        )
        subprocess.check_output(["git", "add", "-A"], stderr=subprocess.STDOUT, timeout=30)
        try:
            subprocess.check_output(
                ["git", "commit", "-m", req.message],
                stderr=subprocess.STDOUT, timeout=30,
            )
        except subprocess.CalledProcessError:
            pass
        result = subprocess.check_output(
            ["git", "push", "origin", _BRANCH],
            stderr=subprocess.STDOUT, timeout=60,
        ).decode()
        subprocess.check_output(["git", "checkout", original_branch], stderr=subprocess.STDOUT, timeout=10)
        try:
            subprocess.check_output(["git", "stash", "pop"], stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
        return {"status": "success", "output": result[:500]}
    except subprocess.CalledProcessError as e:
        try:
            subprocess.check_output(["git", "checkout", original_branch], stderr=subprocess.DEVNULL, timeout=10)
            subprocess.check_output(["git", "stash", "pop"], stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
        return {"status": "error", "output": e.output.decode()[:500] if e.output else str(e)}


@router.post("/git-rollback")
def git_rollback(req: GitPushRequest, request: Request):
    require_super_admin(request)

    original_branch = _get_current_branch()
    _ensure_coin_branch()

    try:
        subprocess.check_output(["git", "stash"], stderr=subprocess.STDOUT, timeout=10)
        subprocess.check_output(["git", "checkout", _BRANCH], stderr=subprocess.STDOUT, timeout=10)
        subprocess.check_output(
            ["git", "revert", "HEAD", "--no-edit"],
            stderr=subprocess.STDOUT, timeout=30,
        )
        result = subprocess.check_output(
            ["git", "push", "origin", _BRANCH],
            stderr=subprocess.STDOUT, timeout=60,
        ).decode()
        subprocess.check_output(["git", "checkout", original_branch], stderr=subprocess.STDOUT, timeout=10)
        try:
            subprocess.check_output(["git", "stash", "pop"], stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
        return {"status": "success", "output": result[:500]}
    except subprocess.CalledProcessError as e:
        try:
            subprocess.check_output(["git", "checkout", original_branch], stderr=subprocess.DEVNULL, timeout=10)
            subprocess.check_output(["git", "stash", "pop"], stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
        return {"status": "error", "output": e.output.decode()[:500] if e.output else str(e)}


@router.post("/git-delete")
def git_delete_commit(req: GitPushRequest, request: Request):
    """Delete the latest commit from coin branch (revert + push)."""
    require_super_admin(request)
    return git_rollback(req, request)


# ─── Database Management ───

@router.get("/database/stats")
def database_stats(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    try:
        size_result = db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).fetchone()
        db_size = size_result[0] if size_result else "unknown"

        table_count = db.execute(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
        )).fetchone()

        conn_count = db.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )).fetchone()

        return {
            "size": db_size,
            "table_count": table_count[0] if table_count else 0,
            "active_connections": conn_count[0] if conn_count else 0,
        }
    except Exception:
        return {"size": "error", "table_count": 0, "active_connections": 0}


@router.get("/database/tables")
def database_tables(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    try:
        rows = db.execute(text("""
            SELECT
                t.table_name,
                COALESCE(s.n_live_tup, 0) as row_count,
                pg_size_pretty(pg_total_relation_size(quote_ident(t.table_name))) as size
            FROM information_schema.tables t
            LEFT JOIN pg_stat_user_tables s ON s.relname = t.table_name
            WHERE t.table_schema = 'public'
            ORDER BY COALESCE(s.n_live_tup, 0) DESC
        """)).fetchall()

        return [
            {"name": r[0], "row_count": r[1], "size": r[2]}
            for r in rows
        ]
    except Exception:
        return []


@router.get("/database/tables/{table_name}/data")
def table_data(table_name: str, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    safe_chars = set("abcdefghijklmnopqrstuvwxyz_0123456789")
    if not all(c in safe_chars for c in table_name.lower()):
        raise HTTPException(status_code=400, detail="Invalid table name")

    try:
        result = db.execute(text(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 100"))
        columns = list(result.keys())
        rows = [dict(zip(columns, [str(v) if v is not None else None for v in row])) for row in result.fetchall()]
        return {"columns": columns, "rows": rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/database/backup")
def database_backup(request: Request):
    """Backup database and commit SQL dump to coin branch."""
    require_super_admin(request)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"/tmp/cex_backup_{timestamp}.sql"
    original_branch = _get_current_branch()
    _ensure_coin_branch()

    try:
        subprocess.check_output(
            ["pg_dump", "-h", "127.0.0.1", "-U", "postgres", "-d", "cex_trading", "-f", backup_file],
            stderr=subprocess.STDOUT, timeout=120,
            env={**os.environ, "PGPASSWORD": "cex_trading_2026"},
        )
        size = os.path.getsize(backup_file)

        subprocess.check_output(["git", "stash"], stderr=subprocess.STDOUT, timeout=10)
        subprocess.check_output(["git", "checkout", _BRANCH], stderr=subprocess.STDOUT, timeout=10)

        backup_dir = os.path.join(os.getcwd(), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        dest = os.path.join(backup_dir, f"cex_backup_{timestamp}.sql")
        os.rename(backup_file, dest)

        subprocess.check_output(["git", "add", dest], stderr=subprocess.STDOUT, timeout=10)
        subprocess.check_output(
            ["git", "commit", "-m", f"DB backup {timestamp}"],
            stderr=subprocess.STDOUT, timeout=30,
        )
        subprocess.check_output(
            ["git", "push", "origin", _BRANCH],
            stderr=subprocess.STDOUT, timeout=60,
        )

        subprocess.check_output(["git", "checkout", original_branch], stderr=subprocess.STDOUT, timeout=10)
        try:
            subprocess.check_output(["git", "stash", "pop"], stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass

        return {"status": "success", "file": dest, "size_mb": round(size / 1024 / 1024, 2)}
    except subprocess.CalledProcessError as e:
        try:
            subprocess.check_output(["git", "checkout", original_branch], stderr=subprocess.DEVNULL, timeout=10)
            subprocess.check_output(["git", "stash", "pop"], stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
        return {"status": "error", "output": e.output.decode()[:500] if e.output else str(e)}


@router.post("/database/cleanup")
def database_cleanup(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    try:
        deleted_logs = db.execute(text(
            "DELETE FROM trade_logs WHERE created_at < NOW() - INTERVAL '90 days'"
        ))
        deleted_audit = db.execute(text(
            "DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '90 days'"
        ))
        deleted_health = db.execute(text(
            "DELETE FROM proxy_health_logs WHERE checked_at < NOW() - INTERVAL '30 days'"
        ))
        db.commit()

        return {
            "status": "success",
            "deleted": {
                "trade_logs": deleted_logs.rowcount,
                "audit_logs": deleted_audit.rowcount,
                "proxy_health_logs": deleted_health.rowcount,
            },
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}


# ─── Role Permissions ───

@router.get("/roles")
def list_roles(request: Request):
    require_super_admin(request)

    return [
        {
            "role": "SUPER_ADMIN",
            "description": "超级管理员 - 完全权限",
            "permissions": ["users", "engine", "system", "database", "ssl", "proxy", "audit", "ai"],
        },
        {
            "role": "ADMIN",
            "description": "管理员 - 运营管理权限",
            "permissions": ["engine", "ssl", "proxy", "audit"],
        },
        {
            "role": "USER",
            "description": "普通用户 - 仅自有数据",
            "permissions": ["own_data"],
        },
    ]
