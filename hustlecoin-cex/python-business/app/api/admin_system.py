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
from app.db.models import AiCoinConfig
from app.middleware.permissions import require_super_admin

router = APIRouter(prefix="/api/admin/system", tags=["admin-system"])

_start_time = time.time()
_BRANCH = "coin"
_SSH_KEY = os.path.expanduser("~/.ssh/cex-trading-key2.pem")
_RUST_HOST = "57.182.57.4"
_SSH_USER = "ec2-user"
_VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "VERSION")


def _ssh_command(host: str, cmd: str, timeout: int = 10) -> str:
    try:
        result = subprocess.check_output(
            ["ssh", "-i", _SSH_KEY, "-o", "StrictHostKeyChecking=no",
             "-o", f"ConnectTimeout={timeout}",
             f"{_SSH_USER}@{host}", cmd],
            stderr=subprocess.DEVNULL, timeout=timeout + 5,
        )
        return result.decode().strip()
    except Exception:
        return ""


def _read_version() -> str:
    try:
        with open(_VERSION_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return "0.5.0"


def _write_version(ver: str):
    with open(_VERSION_FILE, "w") as f:
        f.write(ver + "\n")


def _bump_version(ver: str) -> str:
    parts = ver.split(".")
    if len(parts) == 3:
        parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts)


def _decrement_version(ver: str) -> str:
    parts = ver.split(".")
    if len(parts) == 3 and int(parts[2]) > 0:
        parts[2] = str(int(parts[2]) - 1)
    return ".".join(parts)


# ─── System Info ───

@router.get("/info")
def system_info(request: Request):
    require_super_admin(request)

    uptime_sec = int(time.time() - _start_time)
    hours, rem = divmod(uptime_sec, 3600)
    minutes, secs = divmod(rem, 60)

    git_commit = ""
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        pass

    return {
        "backend_version": _read_version(),
        "python_version": sys.version.split()[0],
        "db_version": "PostgreSQL",
        "uptime": f"{hours}h {minutes}m {secs}s",
        "git_branch": _BRANCH,
        "git_commit": git_commit,
    }


# ─── Multi-Service Versions ───

@router.get("/versions")
def service_versions(request: Request):
    require_super_admin(request)

    uptime_sec = int(time.time() - _start_time)
    hours, rem = divmod(uptime_sec, 3600)
    minutes, secs = divmod(rem, 60)

    backend_commit = ""
    try:
        backend_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        pass

    ver = _read_version()

    backend_info = {
        "service": "后端",
        "host": "coinadmin.hustle2026.xyz",
        "version": ver,
        "git_commit": backend_commit,
        "uptime": f"{hours}h {minutes}m {secs}s",
        "status": "running",
    }

    frontend_commit = ""
    frontend_deploy_time = ""
    try:
        frontend_commit = subprocess.check_output(
            ["git", "log", "-1", "--format=%h", "--", "frontend/", "frontend-admin/", "python-business/static/"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        frontend_deploy_time = subprocess.check_output(
            ["git", "log", "-1", "--format=%ai", "--", "frontend/", "frontend-admin/", "python-business/static/"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        pass

    frontend_info = {
        "service": "前端",
        "host": "coin.hustle2026.xyz",
        "version": ver,
        "git_commit": frontend_commit or backend_commit,
        "last_deploy": frontend_deploy_time[:19] if frontend_deploy_time else "-",
        "status": "deployed",
    }

    rust_status = _ssh_command(_RUST_HOST, "systemctl is-active cex-engine 2>/dev/null || echo stopped")
    rust_version = _ssh_command(_RUST_HOST,
        "grep '^version' /home/ec2-user/hustlecoin-cex/rust-engine/Cargo.toml 2>/dev/null"
        " | head -1 | sed 's/.*\"\\(.*\\)\"/\\1/'")
    rust_uptime = _ssh_command(_RUST_HOST,
        "systemctl show cex-engine --property=ActiveEnterTimestamp --value 2>/dev/null")
    rust_binary_time = _ssh_command(_RUST_HOST,
        "stat -c '%y' /home/ec2-user/hustlecoin-cex/rust-engine/target/release/cex-engine 2>/dev/null"
        " | cut -d. -f1")

    rust_info = {
        "service": "Rust引擎",
        "host": "57.182.57.4",
        "version": rust_version or "unknown",
        "git_commit": rust_binary_time or "-",
        "uptime": rust_uptime or "-",
        "status": rust_status or "unknown",
    }

    return {"services": [frontend_info, backend_info, rust_info]}


# ─── Git Operations (coin branch, no checkout needed) ───

class GitPushRequest(BaseModel):
    message: str


class GitCommitRequest(BaseModel):
    commit_hash: str


@router.get("/git-history")
def git_history(request: Request):
    require_super_admin(request)

    try:
        output = subprocess.check_output(
            ["git", "log", "--oneline", "--format=%H|%h|%s|%an|%ai", "-20"],
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


_REPO_SUBDIRS = ["frontend", "frontend-admin", "python-business", "rust-engine", "deploy"]


def _repo_root() -> str:
    """git 仓库根(已对齐到家目录 /home/ec2-user;代码在 hustlecoin-cex/ 下,与 GitHub 结构一致)。"""
    return subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=os.path.dirname(_VERSION_FILE), stderr=subprocess.DEVNULL, timeout=10,
    ).decode().strip()


def _pull_rust_source(root: str) -> bool:
    """从 Rust 交易服务器(57.182.57.4)拉当前 rust-engine 源进本仓库 —— 备份的 Rust 腿。
    best-effort:失败不阻断(前后端仍照常备份)。"""
    proj = os.path.join(root, "hustlecoin-cex")
    cmd = (
        f'ssh -i {_SSH_KEY} -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10 '
        f'{_SSH_USER}@{_RUST_HOST} '
        f'"cd /home/ec2-user/hustlecoin-cex && tar -cf - --exclude=target --exclude=.git '
        f'rust-engine/src rust-engine/Cargo.toml rust-engine/Cargo.lock" '
        f'| tar -C {proj} -xf -'
    )
    try:
        subprocess.run(cmd, shell=True, timeout=60, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


@router.post("/git-push")
def git_push(req: GitPushRequest, request: Request):
    require_super_admin(request)

    try:
        root = _repo_root()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # 0. 备份标签(best-effort)
        try:
            subprocess.check_output(["git", "tag", f"backup-{timestamp}"],
                                    cwd=root, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass

        # 1. 拉 Rust 服务器当前源(两服务器全量备份的 Rust 腿)
        rust_ok = _pull_rust_source(root)

        # 2. 暂存:仅 5 个项目子目录(自动排除家目录敏感文件 + hustlecoin-cex/hustlecoin-cex 旧副本);
        #    dist 被 .gitignore 忽略故 -f 强制纳入;最后剔除 *.bak 杂物。
        subprocess.check_output(
            ["git", "add"] + [f"hustlecoin-cex/{d}" for d in _REPO_SUBDIRS],
            cwd=root, stderr=subprocess.STDOUT, timeout=90,
        )
        try:
            subprocess.check_output(
                ["git", "add", "-f",
                 "hustlecoin-cex/python-business/static/spa",
                 "hustlecoin-cex/python-business/static/admin-spa"],
                cwd=root, stderr=subprocess.DEVNULL, timeout=30,
            )
        except Exception:
            pass
        staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"],
                                         cwd=root, timeout=20).decode().splitlines()
        baks = [p for p in staged if ".bak" in p]
        if baks:
            subprocess.run(["git", "reset", "-q", "--"] + baks, cwd=root, timeout=30, check=False)

        # 3. 有变更才升版本号
        has_changes = False
        try:
            subprocess.check_output(["git", "diff", "--cached", "--quiet"],
                                    cwd=root, stderr=subprocess.DEVNULL, timeout=10)
        except subprocess.CalledProcessError:
            has_changes = True
        if has_changes:
            new_ver = _bump_version(_read_version())
            _write_version(new_ver)
            subprocess.check_output(["git", "add", _VERSION_FILE],
                                    cwd=root, stderr=subprocess.DEVNULL, timeout=5)

        # 4. 提交
        try:
            subprocess.check_output(["git", "commit", "-m", req.message],
                                    cwd=root, stderr=subprocess.STDOUT, timeout=30)
        except subprocess.CalledProcessError:
            pass

        # 5. 推送(仓库已对齐 origin/coin,fast-forward)
        result = subprocess.check_output(["git", "push", "origin", _BRANCH],
                                         cwd=root, stderr=subprocess.STDOUT, timeout=180).decode()
        return {"status": "success", "output": result[:800],
                "version": _read_version(), "rust_synced": rust_ok}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.output.decode()[:800] if e.output else str(e)}
    except Exception as e:
        return {"status": "error", "output": str(e)[:800]}


@router.post("/git-rollback")
def git_rollback(req: GitCommitRequest, request: Request):
    require_super_admin(request)

    try:
        ver = _read_version()
        new_ver = _decrement_version(ver)

        subprocess.check_output(
            ["git", "reset", "--hard", req.commit_hash],
            stderr=subprocess.STDOUT, timeout=30,
        )

        _write_version(new_ver)
        subprocess.check_output(["git", "add", _VERSION_FILE], stderr=subprocess.DEVNULL, timeout=5)
        subprocess.check_output(
            ["git", "commit", "-m", f"rollback to {req.commit_hash[:8]}, version {new_ver}"],
            stderr=subprocess.STDOUT, timeout=30,
        )

        result = subprocess.check_output(
            ["git", "push", "--force", "origin", _BRANCH],
            stderr=subprocess.STDOUT, timeout=60,
        ).decode()
        return {"status": "success", "output": result[:500], "version": new_ver}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.output.decode()[:500] if e.output else str(e)}


@router.post("/git-delete")
def git_delete_commit(req: GitCommitRequest, request: Request):
    require_super_admin(request)

    try:
        subprocess.check_output(
            ["git", "revert", req.commit_hash, "--no-edit"],
            stderr=subprocess.STDOUT, timeout=30,
        )
        result = subprocess.check_output(
            ["git", "push", "origin", _BRANCH],
            stderr=subprocess.STDOUT, timeout=60,
        ).decode()
        return {"status": "success", "output": result[:500]}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.output.decode()[:500] if e.output else str(e)}


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
    require_super_admin(request)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"/tmp/cex_backup_{timestamp}.sql"

    try:
        subprocess.check_output(
            ["pg_dump", "-h", "127.0.0.1", "-U", "postgres", "-d", "cex_trading", "-f", backup_file],
            stderr=subprocess.STDOUT, timeout=120,
            env={**os.environ, "PGPASSWORD": "cex_trading_2026"},
        )
        size = os.path.getsize(backup_file)

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

        return {"status": "success", "file": dest, "size_mb": round(size / 1024 / 1024, 2)}
    except subprocess.CalledProcessError as e:
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


# ─── AiCoin Config ───

class AiCoinConfigUpdate(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None


@router.get("/aicoin-config")
def get_aicoin_config(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    cfg = db.query(AiCoinConfig).first()
    if not cfg:
        return {"api_key": "", "api_secret": ""}
    return {
        "api_key": cfg.api_key or "",
        "api_secret": "****" if cfg.api_secret else "",
    }


@router.put("/aicoin-config")
def update_aicoin_config(req: AiCoinConfigUpdate, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    cfg = db.query(AiCoinConfig).first()
    if not cfg:
        cfg = AiCoinConfig()
        db.add(cfg)

    if req.api_key is not None:
        cfg.api_key = req.api_key
    if req.api_secret is not None and req.api_secret != "****":
        cfg.api_secret = req.api_secret

    db.commit()

    from app.api.market import _reset_aicoin
    _reset_aicoin()

    return {"message": "AiCoin config updated"}


@router.post("/aicoin-test")
async def test_aicoin(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    cfg = db.query(AiCoinConfig).first()
    api_key = (cfg.api_key if cfg and cfg.api_key else None) or ""
    api_secret = (cfg.api_secret if cfg and cfg.api_secret else None) or ""
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="AiCoin API Key/Secret 未配置")

    from app.services.aicoin_client import AiCoinClient
    try:
        client = AiCoinClient(api_key, api_secret)
        coins = await client.get_coin_list()
        return {"status": "ok", "coin_count": len(coins)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AiCoin API 连接失败: {e}")
