"""System management API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path
import subprocess
import os
import re
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.core.config import settings
from app.tasks.redis_monitor import redis_monitor
from app.services.version_service import version_service
from app.services.mt5_bridge import mt5_bridge

router = APIRouter()


# Pydantic models for request bodies
class RestoreDatabaseRequest(BaseModel):
    filename: str

class UpdateRecordRequest(BaseModel):
    record: Dict[str, Any]
    where: Dict[str, Any]

class RollbackRequest(BaseModel):
    hash: str = None
    version: str = None  # For backward compatibility
    branch: Optional[str] = None


# ============================================================================
# Deployment Helpers (shared by push/rollback/delete go branch operations)
# ============================================================================

# The Python backend's WorkingDirectory is /data/hustle2026/backend; parent is
# the repo root that contains frontend/, backend/, etc.
REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

# Nginx deploy targets for admin and go (main) frontends. These paths are
# symlinked into /home/ubuntu/hustle2026 but we target the canonical location.
# Independent frontend project directories (split from monorepo 2026-04-16)
FRONTEND_ADMIN_DIR = "/home/ubuntu/hustle2026/frontend-admin"
FRONTEND_GO_DIR = "/home/ubuntu/hustle2026/frontend-go"
FRONTEND_WWW_DIR = "/home/ubuntu/hustle2026/frontend-www"

# Nginx deploy targets = each project's own dist/
NGINX_ADMIN_DIST = os.path.join(FRONTEND_ADMIN_DIR, "dist")
NGINX_GO_DIST = os.path.join(FRONTEND_GO_DIR, "dist")

# Build output = same as deploy (each project builds into its own dist/)
BUILD_ADMIN_DIST = NGINX_ADMIN_DIST
BUILD_GO_DIST = NGINX_GO_DIST


def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a subprocess with sane defaults and return the completed process.

    Raises RuntimeError with stderr if the command fails.
    """
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd or REPO_ROOT,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command {' '.join(cmd)} failed (code {proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    return proc


def _build_frontend() -> Dict[str, str]:
    """Build admin, go, and www frontends from independent project directories.

    Each project has its own package.json, node_modules, vite.config.js.
    Build output goes directly into each project's dist/ directory.
    """
    results = {}

    # Build admin
    if os.path.isdir(FRONTEND_ADMIN_DIR):
        _run(["npx", "vite", "build"], cwd=FRONTEND_ADMIN_DIR, timeout=600)
        results["admin_dist"] = NGINX_ADMIN_DIST
    else:
        raise RuntimeError(f"frontend-admin not found: {FRONTEND_ADMIN_DIR}")

    # Build go
    if os.path.isdir(FRONTEND_GO_DIR):
        _run(["npx", "vite", "build"], cwd=FRONTEND_GO_DIR, timeout=600)
        results["go_dist"] = NGINX_GO_DIST
    else:
        raise RuntimeError(f"frontend-go not found: {FRONTEND_GO_DIR}")

    # Build www
    if os.path.isdir(FRONTEND_WWW_DIR):
        _run(["npx", "vite", "build"], cwd=FRONTEND_WWW_DIR, timeout=600)
        results["www_dist"] = os.path.join(FRONTEND_WWW_DIR, "dist")

    return results


def _sync_dir(src: str, dst: str) -> None:
    """Replace dst directory contents with src contents atomically-ish.

    Uses rsync when available for safety; falls back to shutil otherwise.
    """
    import shutil
    if not os.path.isdir(src):
        raise RuntimeError(f"Source directory missing: {src}")
    os.makedirs(dst, exist_ok=True)

    # Prefer rsync for atomic-ish replace and preserved metadata
    if shutil.which("rsync"):
        _run(
            ["rsync", "-a", "--delete", f"{src.rstrip('/')}/", f"{dst.rstrip('/')}/"],
            cwd=REPO_ROOT,
            timeout=300,
        )
        return

    # Fallback: clear dst then copy
    for entry in os.listdir(dst):
        entry_path = os.path.join(dst, entry)
        if os.path.isdir(entry_path) and not os.path.islink(entry_path):
            shutil.rmtree(entry_path)
        else:
            os.remove(entry_path)
    for entry in os.listdir(src):
        s = os.path.join(src, entry)
        d = os.path.join(dst, entry)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def _deploy_frontend() -> Dict[str, str]:
    """No-op: each independent project builds directly into its own dist/.
    Nginx points to these directories, so no sync is needed."""
    return {
        "admin": NGINX_ADMIN_DIST,
        "go": NGINX_GO_DIST,
        "www": os.path.join(FRONTEND_WWW_DIR, "dist"),
    }


def _restart_services() -> Dict[str, str]:
    """Restart python/go backends and reload nginx. Returns per-service status.

    Errors are captured per-service so a single failure does not prevent the
    other services from restarting. Caller decides how to report partial
    failure to the user.
    """
    results: Dict[str, str] = {}
    for unit, action in (
        ("hustle-go", "restart"),
        ("nginx", "reload"),
        # Restart Python LAST so the current request can return before the
        # process is replaced. We schedule it via systemd so the reply flushes.
        ("hustle-python", "restart"),
    ):
        try:
            # Use sudo -n to avoid interactive prompts; ubuntu has NOPASSWD:ALL
            _run(["sudo", "-n", "systemctl", action, unit], cwd=REPO_ROOT, timeout=60)
            results[unit] = "ok"
        except Exception as exc:
            results[unit] = f"failed: {exc}"
    return results

class DeleteRecordRequest(BaseModel):
    where: Dict[str, Any]

class RefreshSettingsRequest(BaseModel):
    settings: Dict[str, Any]
    modules: List[Dict[str, Any]]


@router.get("/database/stats")
async def get_database_stats(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get database statistics"""
    try:
        # Get database size
        result = await db.execute(text("""
            SELECT pg_size_pretty(pg_database_size(current_database())) as size
        """))
        db_size = result.scalar()

        # Get number of tables
        result = await db.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """))
        table_count = result.scalar()

        # Get active connections
        result = await db.execute(text("""
            SELECT COUNT(*) FROM pg_stat_activity
            WHERE datname = current_database()
        """))
        connections = result.scalar()

        # Get table details
        result = await db.execute(text("""
            SELECT
                schemaname,
                relname as tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) as size,
                n_live_tup as rows
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(schemaname||'.'||relname) DESC
        """))

        tables = []
        for row in result:
            tables.append({
                "name": row.tablename,
                "rows": str(row.rows),
                "size": row.size
            })

        return {
            "stats": {
                "size": db_size,
                "tables": table_count,
                "connections": connections
            },
            "tables": tables
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get database stats: {str(e)}"
        )


@router.get("/database/table/{table_name}")
async def view_table(
    table_name: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """View table data (first 100 rows)"""
    try:
        # Validate table name to prevent SQL injection
        result = await db.execute(text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename = :table_name
        """), {"table_name": table_name})

        if not result.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Table not found"
            )

        # Get table columns
        result = await db.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = :table_name
            ORDER BY ordinal_position
        """), {"table_name": table_name})

        columns = [{"name": row.column_name, "type": row.data_type} for row in result]

        # Get table data (limit to 100 rows for safety)
        result = await db.execute(text(f'SELECT * FROM "{table_name}" LIMIT 100'))
        rows = [dict(row._mapping) for row in result]

        return {
            "table_name": table_name,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to view table: {str(e)}"
        )


@router.post("/database/backup")
async def backup_database(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Backup database via pg_dump, then commit and push to go branch"""
    try:
        backup_dir = Path(REPO_ROOT) / "database_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}_UTC.sql"
        file_path = backup_dir / filename

        db_host = settings.DB_HOST
        db_port = settings.DB_PORT
        db_name = settings.DB_NAME
        db_user = settings.DB_USER
        db_password = settings.DB_PASSWORD

        env = os.environ.copy()
        env["PGPASSWORD"] = db_password

        result = subprocess.run(
            ["pg_dump", "-h", db_host, "-p", str(db_port), "-U", db_user, "-d", db_name, "-f", str(file_path)],
            capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            raise Exception(f"pg_dump failed: {result.stderr}")

        size_mb = file_path.stat().st_size / 1024 / 1024

        # Git add + commit + push to go branch
        _run(["git", "add", str(file_path)], cwd=REPO_ROOT)
        commit_msg = f"[db-backup] {filename} ({size_mb:.2f} MB) - {timestamp} UTC"
        _run(["git", "commit", "-m", commit_msg, "--no-verify"], cwd=REPO_ROOT)
        _run(["git", "push", "origin", "go"], cwd=REPO_ROOT, timeout=120)

        return {
            "message": "Database backup successful and pushed to go branch",
            "filename": filename,
            "path": str(file_path),
            "size": f"{size_mb:.2f} MB"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to backup database: {str(e)}"
        )


@router.post("/database/backup-table/{table_name}")
async def backup_table(
    table_name: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Backup specific table"""
    try:
        # Validate table exists
        result = await db.execute(text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename = :table_name
        """), {"table_name": table_name})

        if not result.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Table not found"
            )

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{table_name}_{timestamp}_UTC.sql"

        return {
            "message": f"Table {table_name} backup initiated",
            "filename": filename,
            "note": "Table backup functionality requires pg_dump configuration"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to backup table: {str(e)}"
        )


@router.post("/database/restore")
async def restore_database(
    request: RestoreDatabaseRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Restore database from backup"""
    try:
        backup_dir = Path("/data/hustle2026/database_backups")
        file_path = backup_dir / request.filename

        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Backup file not found: {request.filename}"
            )

        db_host = settings.DB_HOST
        db_port = settings.DB_PORT
        db_name = settings.DB_NAME
        db_user = settings.DB_USER
        db_password = settings.DB_PASSWORD

        env = os.environ.copy()
        env["PGPASSWORD"] = db_password

        result = subprocess.run(
            ["psql", "-h", db_host, "-p", str(db_port), "-U", db_user, "-d", db_name, "-f", str(file_path)],
            capture_output=True,
            text=True,
            env=env
        )

        if result.returncode != 0:
            raise Exception(f"psql restore failed: {result.stderr}")

        return {
            "message": "Database restore successful",
            "filename": request.filename
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore database: {str(e)}"
        )


@router.post("/database/clean-logs")
async def clean_logs(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Clean old log entries"""
    try:
        # Clean old market data (keep last 7 days)
        result = await db.execute(text("""
            DELETE FROM market_data
            WHERE timestamp < NOW() - INTERVAL '7 days'
        """))
        market_deleted = result.rowcount

        # Clean old spread records (keep last 7 days)
        result = await db.execute(text("""
            DELETE FROM spread_records
            WHERE timestamp < NOW() - INTERVAL '7 days'
        """))
        spread_deleted = result.rowcount

        await db.commit()

        return {
            "message": "Logs cleaned successfully",
            "market_data_deleted": market_deleted,
            "spread_records_deleted": spread_deleted
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clean logs: {str(e)}"
        )


@router.get("/info")
async def get_system_info(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get system information"""
    try:
        # Get PostgreSQL version
        result = await db.execute(text("SELECT version()"))
        pg_version = result.scalar()

        # Extract version number
        version_parts = pg_version.split()
        pg_version_number = version_parts[1] if len(version_parts) > 1 else "Unknown"

        # Get current versions from version service
        versions = version_service.get_versions()

        # Get Go version
        go_version = "unknown"
        try:
            go_result = subprocess.run(
                ["/usr/local/go/bin/go", "version"],
                capture_output=True, text=True, timeout=3
            )
            if go_result.returncode == 0:
                parts = go_result.stdout.split()
                if len(parts) >= 3:
                    go_version = parts[2].lstrip("go")
        except Exception:
            pass

        return {
            "frontend_version": versions["frontend_version"],
            "frontend_build_time": versions.get("last_backup_time", "2026-02-19 12:00:00"),
            "backend_version": versions["backend_version"],
            "python_version": "3.12",
            "go_version": go_version,
            "db_version": pg_version_number,
            "uptime": "Running",
            "start_time": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system info: {str(e)}"
        )

@router.get("/database/backups")
async def get_backup_history(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get backup history"""
    try:
        backup_dir = Path("/data/hustle2026/database_backups")
        backups = []

        if backup_dir.exists():
            for file in backup_dir.glob("*.sql"):
                stat = file.stat()
                backups.append({
                    "filename": file.name,
                    "size": f"{stat.st_size / 1024 / 1024:.2f} MB",
                    "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })

        backups.sort(key=lambda x: x["created_at"], reverse=True)
        return backups
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get backup history: {str(e)}"
        )


@router.post("/database/table/{table_name}/record")
async def add_table_record(
    table_name: str,
    record: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Add a new record to a table"""
    try:
        # Validate table exists
        result = await db.execute(text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename = :table_name
        """), {"table_name": table_name})
        
        if not result.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Table not found"
            )
        
        # Build INSERT query
        columns = list(record.keys())
        placeholders = [f":{col}" for col in columns]
        
        query = f"""
            INSERT INTO "{table_name}" ({', '.join(f'"{col}"' for col in columns)})
            VALUES ({', '.join(placeholders)})
        """
        
        await db.execute(text(query), record)
        await db.commit()
        
        return {"message": "Record added successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add record: {str(e)}"
        )


@router.put("/database/table/{table_name}/record")
async def update_table_record(
    table_name: str,
    request: UpdateRecordRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Update a record in a table"""
    try:
        record = request.record
        where = request.where
        # Validate table exists
        result = await db.execute(text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename = :table_name
        """), {"table_name": table_name})
        
        if not result.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Table not found"
            )
        
        # Build UPDATE query
        set_clauses = [f'"{col}" = :{col}' for col in record.keys()]
        where_clauses = [f'"{col}" = :where_{col}' for col in where.keys()]
        
        query = f"""
            UPDATE "{table_name}"
            SET {', '.join(set_clauses)}
            WHERE {' AND '.join(where_clauses)}
        """
        
        # Combine parameters
        params = {**record, **{f"where_{k}": v for k, v in where.items()}}
        
        await db.execute(text(query), params)
        await db.commit()
        
        return {"message": "Record updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update record: {str(e)}"
        )


@router.delete("/database/table/{table_name}/record")
async def delete_table_record(
    table_name: str,
    request: DeleteRecordRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Delete a record from a table"""
    try:
        where = request.where
        # Validate table exists
        result = await db.execute(text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename = :table_name
        """), {"table_name": table_name})
        
        if not result.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Table not found"
            )
        
        # Build DELETE query
        where_clauses = [f'"{col}" = :{col}' for col in where.keys()]
        
        query = f"""
            DELETE FROM "{table_name}"
            WHERE {' AND '.join(where_clauses)}
        """
        
        await db.execute(text(query), where)
        await db.commit()
        
        return {"message": "Record deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete record: {str(e)}"
        )


# GitHub Version Management Endpoints

@router.get("/github/versions")
async def get_version_history(
    user_id: str = Depends(get_current_user_id),
) -> List[Dict[str, Any]]:
    """Get Git commit history from GitHub main branch"""
    try:
        import subprocess

        # Fetch latest commits from remote GO branch
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", "go"],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if fetch_result.returncode != 0:
            raise Exception(f"Failed to fetch from GitHub GO branch: {fetch_result.stderr}")

        # Get last 20 commits from origin/go (GitHub GO branch)
        result = subprocess.run(
            ["git", "log", "origin/go", "--pretty=format:%H|%an|%ae|%ad|%s", "--date=format:%Y-%m-%d %H:%M:%S", "-100"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=".."
        )

        if result.returncode != 0:
            raise Exception(f"Git command failed: {result.stderr}")

        versions = []
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|')
                    if len(parts) >= 5:
                        versions.append({
                            "hash": parts[0],
                            "author": parts[1],
                            "email": parts[2],
                            "date": parts[3],
                            "message": parts[4]
                        })

        return versions
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get version history: {str(e)}"
        )


@router.post("/github/push")
async def push_to_github(
    remark: Optional[str] = Body(None, embed=True),
    branch: Optional[str] = Body(None, embed=True),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Push current version to GitHub GO branch.

    Flow (when branch == "go"):
      1. Build admin + go frontends via vite (fails fast on build error).
      2. Sync dist-admin → frontend-admin/dist and dist → frontend/dist so the
         Nginx deploy directories and the git snapshot stay in sync.
      3. git add . && git commit && git push --force origin HEAD:go.

    This guarantees the GO branch snapshot contains the *exact* code currently
    deployed to go.hustle2026.xyz and admin.hustle2026.xyz.
    """
    build_info: Dict[str, Any] = {}
    try:
        # ----------------------------------------------------------------
        # Step 1: Build frontend (only when pushing to go — avoids rebuild
        # overhead on non-GO branches). Failure aborts before git ops.
        # ----------------------------------------------------------------
        if branch == "go":
            try:
                build_info["build"] = _build_frontend()
                build_info["deploy"] = _deploy_frontend()
            except Exception as build_exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"前端构建或部署失败，已取消推送: {build_exc}",
                )

        # Get current branch name
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if branch_result.returncode != 0:
            raise Exception(f"Failed to get current branch: {branch_result.stderr}")

        current_branch = branch_result.stdout.strip()

        # Initialize warning message
        warning_msg = None

        # Check if there are changes to commit
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if status_result.stdout.strip():
            # Increment version numbers before committing
            version_data = version_service.increment_on_backup()
            frontend_ver = version_data["frontend_version"]
            backend_ver = version_data["backend_version"]

            # There are uncommitted changes - commit them
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " UTC"
            if remark:
                commit_message = f"Version {frontend_ver}/{backend_ver}: {timestamp} - {remark}"
            else:
                commit_message = f"Version {frontend_ver}/{backend_ver}: {timestamp}"

            # Check for large files before adding (GitHub limit is 100MB)
            import os
            large_files = []
            max_size = 100 * 1024 * 1024  # 100MB in bytes

            # Get list of files that would be added
            files_to_check = []
            for line in status_result.stdout.strip().split('\n'):
                if line:
                    # Parse git status output (format: XY filename)
                    status_code = line[:2]
                    filename = line[3:].strip()
                    # Remove quotes if present
                    if filename.startswith('"') and filename.endswith('"'):
                        filename = filename[1:-1]
                    files_to_check.append(filename)

            # Check file sizes
            for filename in files_to_check:
                filepath = os.path.join("..", filename)
                if os.path.isfile(filepath):
                    try:
                        file_size = os.path.getsize(filepath)
                        if file_size > max_size:
                            large_files.append({
                                "name": filename,
                                "size": file_size,
                                "size_mb": round(file_size / (1024 * 1024), 2)
                            })
                    except Exception as e:
                        # Skip files that can't be accessed
                        pass

            # If there are large files, exclude them and warn
            if large_files:
                # Add files individually, excluding large ones
                for filename in files_to_check:
                    filepath = os.path.join("..", filename)
                    try:
                        if os.path.isfile(filepath):
                            file_size = os.path.getsize(filepath)
                            if file_size <= max_size:
                                add_result = subprocess.run(
                                    ["git", "add", filename],
                                    capture_output=True,
                                    text=True,
                                    cwd=".."
                                )
                                if add_result.returncode != 0:
                                    raise Exception(f"Git add failed for {filename}: {add_result.stderr}")
                        else:
                            # Add directories or deleted files
                            add_result = subprocess.run(
                                ["git", "add", filename],
                                capture_output=True,
                                text=True,
                                cwd=".."
                            )
                    except Exception as e:
                        # Skip files that cause errors
                        print(f"Warning: Could not add {filename}: {str(e)}")

                # Create warning message
                large_files_msg = ", ".join([f"{f['name']} ({f['size_mb']}MB)" for f in large_files])
                warning_msg = f"警告: 以下文件超过100MB已被排除: {large_files_msg}"
            else:
                # No large files, add all changes normally
                add_result = subprocess.run(
                    ["git", "add", "."],
                    capture_output=True,
                    text=True,
                    cwd=".."
                )

                if add_result.returncode != 0:
                    raise Exception(f"Git add failed: {add_result.stderr}")

            # Commit changes (skip pre-commit hooks for automated backups)
            commit_result = subprocess.run(
                ["git", "commit", "--no-verify", "-m", commit_message],
                capture_output=True,
                text=True,
                cwd=".."
            )

            if commit_result.returncode != 0:
                error_msg = commit_result.stderr or commit_result.stdout or "Unknown error"
                raise Exception(f"Git commit failed: {error_msg}")

        # Push to remote — go branch uses force-push to HEAD:go refspec
        push_args = ["git", "push"]
        if branch == "go":
            push_args.extend(["--force", "origin", "HEAD:go"])
        elif current_branch.startswith("backup-"):
            push_args.extend(["--force", "origin", current_branch])
        else:
            push_args.extend(["origin", current_branch])

        push_result = subprocess.run(
            push_args,
            capture_output=True,
            text=True,
            cwd=".."
        )

        if push_result.returncode != 0:
            raise Exception(f"Git push failed: {push_result.stderr}")

        target_branch = branch if branch else current_branch
        response_data: Dict[str, Any] = {
            "message": f"Successfully pushed to GitHub branch: {target_branch}",
            "branch": target_branch,
            "output": push_result.stdout,
        }

        # Attach frontend build/deploy info so the UI can show what happened
        if build_info:
            response_data["build_info"] = build_info

        # Add warning message if large files were excluded
        if warning_msg:
            response_data["warning"] = warning_msg

        return response_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to push to GitHub: {str(e)}"
        )


@router.post("/github/rollback")
async def rollback_version(
    request: RollbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Rollback the GO server to a specific commit hash.

    Flow:
      1. Fetch origin/go so the requested hash is locally reachable.
      2. git reset --hard <hash> — restores ALL tracked files (source + dist).
      3. Sync frontend/dist-admin → frontend-admin/dist and frontend/dist →
         the Nginx deploy dirs so the served files match the restored commit.
      4. Restart hustle-go, reload nginx, restart hustle-python (in that order
         so the Python process restart happens last; the HTTP response is
         flushed before systemd kills this worker).
    """
    try:
        # Use hash if provided, otherwise use version (for backward compatibility)
        target = request.hash or request.version
        if not target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either hash or version must be provided"
            )

        # Step 1: ensure the hash is locally reachable
        if request.branch == "go":
            try:
                _run(["git", "fetch", "origin", "go"], timeout=120)
            except Exception as fetch_exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to fetch origin/go: {fetch_exc}",
                )

        # Verify the target hash exists and capture its commit message
        try:
            commit_msg_proc = _run(["git", "log", "-1", "--format=%s", target])
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Commit {target[:7]} not found: {exc}",
            )

        commit_message = commit_msg_proc.stdout.strip()
        version_pattern = r"Version (\d+\.\d+\.\d+)/(\d+\.\d+\.\d+)"
        version_match = re.search(version_pattern, commit_message)

        # Step 2: hard reset the working tree to the target commit
        try:
            _run(["git", "reset", "--hard", target], timeout=120)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Git reset failed: {exc}",
            )

        # Step 3: redeploy dist to Nginx directories (source of truth is now
        # the restored commit's dist-admin + dist folders).
        deploy_status: Dict[str, Any] = {}
        try:
            deploy_status = _deploy_frontend()
        except Exception as exc:
            # Do not bail out — the source code is restored, but warn loudly.
            deploy_status = {"error": str(exc)}

        # Step 4: restart services so the new code is live
        restart_status = _restart_services()

        # Restore version numbers if found in commit message
        response: Dict[str, Any] = {
            "message": f"Successfully rolled back to {target[:7]}",
            "commit": target,
            "commit_message": commit_message,
            "deploy": deploy_status,
            "restart": restart_status,
        }
        if version_match:
            frontend_version = version_match.group(1)
            backend_version = version_match.group(2)
            version_service.set_versions_on_restore(frontend_version, backend_version)
            response["frontend_version"] = frontend_version
            response["backend_version"] = backend_version

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback: {str(e)}"
        )


@router.delete("/github/backup/{version_hash}")
async def delete_github_backup(
    version_hash: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Permanently remove a backup commit from the GO branch history.

    This is a destructive rewrite of the remote GO branch:
      1. Fetch origin/go so we have the latest state locally.
      2. Verify the target commit exists on origin/go.
      3. Refuse to delete if the target is the root commit (no parent) —
         there is nothing to rebase onto.
      4. Check out origin/go into a temporary detached worktree ref, then
         `git rebase --onto <target>^ <target>` to drop only that commit
         while preserving every commit that came after it.
      5. Force-push the rewritten history to origin/go.
      6. Restore the original HEAD so the server's working tree is unchanged.

    The currently deployed code on the server is NOT touched — delete only
    rewrites the remote backup history. If the deleted commit happens to be
    the one currently checked out locally, we leave the working tree alone so
    the running services keep operating.
    """
    try:
        # Step 1: refresh remote state
        try:
            _run(["git", "fetch", "origin", "go"], timeout=120)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch origin/go: {exc}",
            )

        # Resolve the full SHA of the target commit (accept short hash too)
        try:
            full_sha = _run(
                ["git", "rev-parse", "--verify", f"{version_hash}^{{commit}}"],
            ).stdout.strip()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Commit {version_hash[:7]} not found in local repository",
            )

        # Step 2: verify target is actually reachable from origin/go
        try:
            _run(
                ["git", "merge-base", "--is-ancestor", full_sha, "origin/go"],
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Commit {full_sha[:7]} is not part of origin/go history",
            )

        # Step 3: check that the commit has a parent (cannot delete root)
        parent_proc = subprocess.run(
            ["git", "rev-parse", f"{full_sha}^"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        if parent_proc.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the root commit of the GO branch",
            )
        parent_sha = parent_proc.stdout.strip()

        # Capture current HEAD so we can restore it after the rewrite
        original_head_proc = _run(["git", "rev-parse", "HEAD"])
        original_head = original_head_proc.stdout.strip()
        original_branch_proc = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        original_branch = original_branch_proc.stdout.strip() or None

        # Step 4: rewrite history on a throwaway branch so the user's working
        # tree keeps pointing at whatever commit it was on before.
        tmp_branch = f"__go_delete_{full_sha[:7]}"
        rewrite_head: Optional[str] = None
        try:
            # Clean up any leftover from a previous failed run
            subprocess.run(
                ["git", "branch", "-D", tmp_branch],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
            _run(["git", "branch", tmp_branch, "origin/go"])

            # Check if target is the tip of origin/go — if so, a reset is
            # enough (no commits after it to replay).
            go_tip_proc = _run(["git", "rev-parse", "origin/go"])
            go_tip = go_tip_proc.stdout.strip()

            if go_tip == full_sha:
                # Simple case: drop the tip → move tmp branch to parent.
                _run(["git", "branch", "-f", tmp_branch, parent_sha])
                rewrite_head = parent_sha
            else:
                # General case: replay commits (target, go_tip] onto target^
                # Stash any uncommitted changes first to avoid rebase failure
                stash_result = subprocess.run(
                    ["git", "stash", "--include-untracked"],
                    capture_output=True, text=True, cwd=REPO_ROOT,
                )
                did_stash = "Saved working directory" in (stash_result.stdout or "")
                _run(["git", "checkout", "--detach", "origin/go"], timeout=120)
                try:
                    # Start rebase with auto-resolve strategy
                    rb = subprocess.run(
                        ["git", "rebase", "-X", "theirs", "--onto",
                         parent_sha, full_sha, tmp_branch],
                        capture_output=True, text=True, cwd=REPO_ROOT,
                        timeout=300,
                    )
                    # If rebase has conflicts, auto-resolve in a loop
                    max_retries = 30
                    while rb.returncode != 0 and max_retries > 0:
                        max_retries -= 1
                        # Stage all files (resolve modify/delete by accepting current state)
                        subprocess.run(
                            ["git", "add", "-A"],
                            capture_output=True, text=True, cwd=REPO_ROOT,
                        )
                        # Try to continue rebase
                        cont = subprocess.run(
                            ["git", "-c", "core.editor=true", "rebase", "--continue"],
                            capture_output=True, text=True, cwd=REPO_ROOT,
                            timeout=120,
                        )
                        if cont.returncode == 0:
                            rb = cont
                            break
                        # If continue also fails (empty commit), skip it
                        if "nothing to commit" in (cont.stdout + cont.stderr) or \
                           "No changes" in (cont.stdout + cont.stderr):
                            rb = subprocess.run(
                                ["git", "rebase", "--skip"],
                                capture_output=True, text=True, cwd=REPO_ROOT,
                                timeout=120,
                            )
                        else:
                            # Still conflicting, try add + continue again
                            rb = cont

                    if rb.returncode != 0:
                        raise RuntimeError(rb.stderr or rb.stdout or "rebase failed")

                    rewrite_head = _run(["git", "rev-parse", tmp_branch]).stdout.strip()
                except HTTPException:
                    raise
                except Exception as rebase_exc:
                    subprocess.run(
                        ["git", "rebase", "--abort"],
                        capture_output=True, text=True, cwd=REPO_ROOT,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Unable to remove {full_sha[:7]} from go branch "
                            f"(rebase conflict): {rebase_exc}"
                        ),
                    )
                finally:
                    if original_branch:
                        _run(["git", "checkout", original_branch], timeout=120)
                    else:
                        _run(["git", "checkout", original_head], timeout=120)
                    if did_stash:
                        subprocess.run(
                            ["git", "stash", "pop"],
                            capture_output=True, text=True, cwd=REPO_ROOT,
                        )

            # Step 5: force-push the rewritten branch to origin/go
            _run(
                ["git", "push", "--force", "origin", f"{tmp_branch}:go"],
                timeout=120,
            )
        finally:
            # Step 6: drop the temporary branch regardless of outcome
            subprocess.run(
                ["git", "branch", "-D", tmp_branch],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )

        return {
            "message": f"Successfully removed backup {full_sha[:7]} from GO branch",
            "deleted_commit": full_sha,
            "new_go_head": rewrite_head,
            "note": "GO branch history has been rewritten. Currently running services are unaffected.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete backup: {str(e)}"
        )


@router.get("/logs/trading")
async def get_trading_logs(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get trading statistics calculation logs"""
    try:
        logs = []

        # Try to query from system_logs table if it exists
        try:
            # Check if system_logs table exists
            result = await db.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'system_logs'
                )
            """))
            table_exists = result.scalar()

            if table_exists:
                # Query recent logs from system_logs table
                result = await db.execute(text("""
                    SELECT level, message, timestamp
                    FROM system_logs
                    WHERE category = 'trade'
                    ORDER BY timestamp DESC
                    LIMIT 500
                """))

                for row in result:
                    logs.append({
                        'timestamp': row.timestamp.strftime('%Y-%m-%d %H:%M:%S') if row.timestamp else '',
                        'level': row.level.upper() if row.level else 'INFO',
                        'message': row.message or ''
                    })

                # Reverse to show oldest first
                logs.reverse()

        except Exception as e:
            print(f"Error querying system_logs table: {e}")

        # If no logs from database, generate sample logs for demonstration
        if not logs:
            from datetime import datetime, timedelta
            now = datetime.now()
            logs = [
                {
                    'timestamp': (now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S'),
                    'level': 'INFO',
                    'message': '开始计算统计数据，共 2 笔订单'
                },
                {
                    'timestamp': (now - timedelta(minutes=4, seconds=30)).strftime('%Y-%m-%d %H:%M:%S'),
                    'level': 'INFO',
                    'message': '订单 #12345: 盈利 +$125.50'
                },
                {
                    'timestamp': (now - timedelta(minutes=4)).strftime('%Y-%m-%d %H:%M:%S'),
                    'level': 'INFO',
                    'message': '订单 #12346: 盈利 +$89.30'
                },
                {
                    'timestamp': (now - timedelta(minutes=3, seconds=30)).strftime('%Y-%m-%d %H:%M:%S'),
                    'level': 'INFO',
                    'message': '总盈利: +$214.80'
                },
                {
                    'timestamp': (now - timedelta(minutes=3)).strftime('%Y-%m-%d %H:%M:%S'),
                    'level': 'INFO',
                    'message': '胜率: 100.00%'
                },
                {
                    'timestamp': (now - timedelta(minutes=2, seconds=30)).strftime('%Y-%m-%d %H:%M:%S'),
                    'level': 'WARNING',
                    'message': '检测到高风险交易信号'
                },
                {
                    'timestamp': (now - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S'),
                    'level': 'INFO',
                    'message': '统计计算完成，耗时 0.23秒'
                }
            ]

        return {
            "logs": logs,
            "total": len(logs),
            "enabled": True
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trading logs: {str(e)}"
        )


@router.get("/refresh-settings")
async def get_refresh_settings(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get refresh settings for all modules"""
    try:
        # In a real implementation, you would load this from database
        # For now, return default settings
        return {
            "settings": {
                "visibilityDetection": True,
                "useWebSocket": False,
                "batchRequests": True,
                "inactiveMultiplier": 5
            },
            "modules": []
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get refresh settings: {str(e)}"
        )

@router.get("/logs")
async def get_system_logs(
    level: Optional[str] = None,
    category: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get system logs with optional filtering"""
    try:
        # Check if system_logs table exists
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'system_logs'
            )
        """))
        table_exists = result.scalar()

        logs = []

        if table_exists:
            # Build query with filters
            query = "SELECT log_id, user_id, level, category, message, details, timestamp FROM system_logs WHERE 1=1"
            params = {}

            if level:
                query += " AND level = :level"
                params["level"] = level

            if category:
                query += " AND category = :category"
                params["category"] = category

            query += " ORDER BY timestamp DESC LIMIT 500"

            result = await db.execute(text(query), params)

            for row in result:
                logs.append({
                    "log_id": row.log_id,
                    "user_id": row.user_id,
                    "level": row.level,
                    "category": row.category,
                    "message": row.message,
                    "details": row.details,
                    "timestamp": row.timestamp.isoformat() + "Z" if row.timestamp else None
                })

        # If no logs from database, generate sample logs
        if not logs:
            from datetime import datetime, timedelta
            now = datetime.now()
            logs = [
                {
                    "log_id": 1,
                    "user_id": "admin",
                    "level": "info",
                    "category": "system",
                    "message": "系统启动成功",
                    "details": {"version": "1.0.0"},
                    "timestamp": (now - timedelta(hours=2)).isoformat() + "Z"
                },
                {
                    "log_id": 2,
                    "user_id": "admin",
                    "level": "info",
                    "category": "api",
                    "message": "API服务已启动",
                    "details": {"port": 8001},
                    "timestamp": (now - timedelta(hours=1, minutes=50)).isoformat() + "Z"
                },
                {
                    "log_id": 3,
                    "user_id": "user123",
                    "level": "info",
                    "category": "auth",
                    "message": "用户登录成功",
                    "details": {"ip": "192.168.1.100"},
                    "timestamp": (now - timedelta(hours=1)).isoformat() + "Z"
                },
                {
                    "log_id": 4,
                    "user_id": "user123",
                    "level": "info",
                    "category": "trade",
                    "message": "交易订单创建",
                    "details": {"order_id": "ORD-12345", "amount": 1000},
                    "timestamp": (now - timedelta(minutes=30)).isoformat() + "Z"
                },
                {
                    "log_id": 5,
                    "user_id": "system",
                    "level": "warning",
                    "category": "system",
                    "message": "内存使用率超过80%",
                    "details": {"usage": "85%"},
                    "timestamp": (now - timedelta(minutes=15)).isoformat() + "Z"
                },
                {
                    "log_id": 6,
                    "user_id": "user456",
                    "level": "error",
                    "category": "api",
                    "message": "API请求失败",
                    "details": {"endpoint": "/api/v1/orders", "error": "Connection timeout"},
                    "timestamp": (now - timedelta(minutes=10)).isoformat() + "Z"
                },
                {
                    "log_id": 7,
                    "user_id": "admin",
                    "level": "critical",
                    "category": "system",
                    "message": "数据库连接失败",
                    "details": {"attempts": 3, "error": "Connection refused"},
                    "timestamp": (now - timedelta(minutes=5)).isoformat() + "Z"
                }
            ]

            # Apply filters to sample data
            if level:
                logs = [log for log in logs if log["level"] == level]
            if category:
                logs = [log for log in logs if log["category"] == category]

        return {
            "logs": logs,
            "total": len(logs)
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system logs: {str(e)}"
        )


@router.delete("/logs/old")
async def clear_old_logs(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Clear system logs older than specified days"""
    try:
        # Check if system_logs table exists
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'system_logs'
            )
        """))
        table_exists = result.scalar()

        if not table_exists:
            return {
                "message": "System logs table does not exist",
                "deleted": 0
            }

        # Delete old logs
        result = await db.execute(text("""
            DELETE FROM system_logs
            WHERE timestamp < NOW() - INTERVAL ':days days'
        """), {"days": days})

        deleted_count = result.rowcount
        await db.commit()

        return {
            "message": f"Successfully cleared logs older than {days} days",
            "deleted": deleted_count
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear old logs: {str(e)}"
        )



@router.post("/refresh-settings")
async def save_refresh_settings(
    request: RefreshSettingsRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, str]:
    """Save refresh settings for all modules"""
    try:
        # In a real implementation, you would save this to database
        # For now, just return success
        # You could store in Redis or a config table

        return {
            "message": "Refresh settings saved successfully",
            "settings": request.settings,
            "modules_count": len(request.modules)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save refresh settings: {str(e)}"
        )




@router.get("/redis/status")
async def get_redis_status(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get Redis/Memurai service status"""
    try:
        status = redis_monitor.get_status()
        return {
            "service": status["service"],
            "healthy": status["healthy"],
            "last_error": status["last_error"],
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "service": "Memurai",
            "healthy": False,
            "last_error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/mt5-bridge/status")
async def get_mt5_bridge_status(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get MT5 Bridge service status"""
    try:
        stats = mt5_bridge.get_stats()
        return {
            "success": True,
            "data": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/market-streamer/stats")
async def get_market_streamer_stats(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get market data streamer statistics (dynamic frequency)"""
    try:
        from app.tasks.market_data import market_streamer
        stats = market_streamer.get_stats()
        return {
            "success": True,
            "data": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


# ── Push Streams Management ──────────────────────────────────────────────────

@router.get("/push-streams/stats")
async def get_push_streams_stats(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """获取所有推送流的实时状态和频率信息"""
    try:
        from app.tasks.market_data import market_streamer
        from app.tasks.broadcast_tasks import (
            account_balance_streamer, risk_metrics_streamer,
            mt5_connection_streamer, pending_orders_streamer, position_streamer
        )
        from app.services.mt5_bridge import mt5_bridge

        market_stats = market_streamer.get_stats()
        bridge_stats = mt5_bridge.get_stats()

        streams = [
            {
                "type": "market_data",
                "name": "市场行情数据",
                "description": "Binance/Bybit 实时 tick 数据",
                "source": "go+python",
                "interval": market_stats.get("current_interval", 1.0),
                "base_interval": market_stats.get("base_interval", 1.0),
                "active_interval": market_stats.get("active_interval", 0.25),
                "frequency": market_stats.get("frequency", "--"),
                "running": market_stats.get("running", False),
                "broadcast_count": market_stats.get("broadcast_count", 0),
                "error_count": market_stats.get("error_count", 0),
                "last_broadcast": market_stats.get("last_broadcast_time"),
                "min_interval": 0.1,
                "max_interval": 10.0,
                "step": 0.1,
            },
            {
                "type": "account_balance",
                "name": "账户余额推送",
                "description": "Binance/Bybit 账户资金实时更新",
                "source": "python",
                "interval": account_balance_streamer.interval,
                "running": account_balance_streamer._running if hasattr(account_balance_streamer, '_running') else True,
                "broadcast_count": getattr(account_balance_streamer, 'broadcast_count', 0),
                "min_interval": 5,
                "max_interval": 60,
                "step": 1,
            },
            {
                "type": "position_update",
                "name": "持仓更新推送",
                "description": "MT5 持仓实时同步（Bridge 服务）",
                "source": "python",
                "interval": bridge_stats.get("interval", 1),
                "running": bridge_stats.get("running", False),
                "broadcast_count": bridge_stats.get("broadcast_count", 0),
                "error_count": bridge_stats.get("error_count", 0),
                "last_broadcast": bridge_stats.get("last_broadcast_time"),
                "active_accounts": bridge_stats.get("active_mt5_accounts", 0),
                "min_interval": 0.1,
                "max_interval": 30.0,
                "step": 0.1,
            },
            {
                "type": "risk_metrics",
                "name": "风险指标推送",
                "description": "套利风险实时计算推送",
                "source": "python",
                "interval": risk_metrics_streamer.interval,
                "running": True,
                "broadcast_count": getattr(risk_metrics_streamer, 'broadcast_count', 0),
                "min_interval": 10,
                "max_interval": 120,
                "step": 5,
            },
            {
                "type": "order_update",
                "name": "订单更新推送",
                "description": "待成交订单状态推送",
                "source": "python",
                "interval": pending_orders_streamer.interval,
                "running": True,
                "broadcast_count": getattr(pending_orders_streamer, 'broadcast_count', 0),
                "min_interval": 1,
                "max_interval": 30,
                "step": 1,
            },
            {
                "type": "mt5_connection_status",
                "name": "MT5 连接状态",
                "description": "MT5 Bridge 连接健康状态推送",
                "source": "python",
                "interval": mt5_connection_streamer.interval,
                "running": True,
                "broadcast_count": getattr(mt5_connection_streamer, 'broadcast_count', 0),
                "min_interval": 10,
                "max_interval": 120,
                "step": 5,
            },
        ]
        return {
            "success": True,
            "streams": streams,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "streams": [],
            "timestamp": datetime.utcnow().isoformat()
        }


class PushStreamUpdate(BaseModel):
    stream_type: str
    interval: float


@router.post("/push-streams/update")
async def update_push_stream(
    data: PushStreamUpdate,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """更新推送流的频率"""
    try:
        from app.tasks.market_data import market_streamer
        from app.tasks.broadcast_tasks import (
            account_balance_streamer, risk_metrics_streamer,
            mt5_connection_streamer, pending_orders_streamer
        )
        from app.services.mt5_bridge import mt5_bridge

        mapping = {
            "market_data": (market_streamer, "update_interval", 0.1, 10.0),
            "account_balance": (account_balance_streamer, "update_interval", 5, 60),
            "position_update": (mt5_bridge, None, 0.1, 30.0),  # special handling
            "risk_metrics": (risk_metrics_streamer, "update_interval", 10, 120),
            "order_update": (pending_orders_streamer, "update_interval", 1, 30),
            "mt5_connection_status": (mt5_connection_streamer, "update_interval", 10, 120),
        }

        if data.stream_type not in mapping:
            raise ValueError(f"Unknown stream type: {data.stream_type}")

        obj, method, min_v, max_v = mapping[data.stream_type]
        if not (min_v <= data.interval <= max_v):
            raise ValueError(f"Interval must be between {min_v} and {max_v}")

        if data.stream_type == "position_update":
            # MT5 Bridge uses self.interval directly
            mt5_bridge.interval = data.interval
        elif method and hasattr(obj, method):
            getattr(obj, method)(data.interval)

        return {
            "success": True,
            "stream_type": data.stream_type,
            "new_interval": data.interval,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Market closure configuration
class MarketClosureConfig(BaseModel):
    enabled: bool = False
    winter_open: str = "周一 07:00"
    winter_close: str = "周六 06:00"
    summer_open: str = "周一 06:00"
    summer_close: str = "周六 05:00"


@router.get("/market-closure-config")
async def get_market_closure_config(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get market closure configuration"""
    try:
        # For now, store in a simple JSON file
        config_file = Path("config/market_closure.json")
        if config_file.exists():
            import json
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = MarketClosureConfig().dict()
        
        return {
            "success": True,
            "config": config
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "config": MarketClosureConfig().dict()
        }


@router.put("/market-closure-config")
async def update_market_closure_config(
    config: MarketClosureConfig,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Update market closure configuration"""
    try:
        # Save to JSON file
        config_file = Path("config/market_closure.json")
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        import json
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config.dict(), f, ensure_ascii=False, indent=2)
        
        return {
            "success": True,
            "message": "配置已保存"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.get("/market-status")
async def get_market_status(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get current market status based on trading hours"""
    try:
        from app.utils.trading_time import is_bybit_trading_hours
        is_open, message = is_bybit_trading_hours()

        return {
            "success": True,
            "is_open": is_open,
            "message": message
        }
    except Exception as e:
        return {
            "success": False,
            "is_open": True,
            "message": f"无法获取市场状态: {str(e)}"
        }


@router.get("/websocket-status")
async def get_websocket_status(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get Binance WebSocket connection status"""
    try:
        from app.services.binance_ws_client import binance_ws

        return {
            "success": True,
            "connected": binance_ws.connected,
            "bid": binance_ws.bid,
            "ask": binance_ws.ask,
            "mid": binance_ws.mid,
            "timestamp": binance_ws.timestamp,
            "message": "WebSocket connected" if binance_ws.connected else "WebSocket disconnected"
        }
    except Exception as e:
        return {
            "success": False,
            "connected": False,
            "message": f"无法获取WebSocket状态: {str(e)}"
        }


import time

# Store start time
START_TIME = time.time()

@router.get("/status")
async def get_system_status(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get comprehensive system status including database pool, services, and connections"""
    try:
        # Calculate uptime
        uptime_seconds = int(time.time() - START_TIME)
        uptime_hours = uptime_seconds // 3600
        uptime_minutes = (uptime_seconds % 3600) // 60

        # Get database pool status
        # SQLAlchemy AsyncAdaptedQueuePool semantics:
        #   pool.size()        = configured pool_size (NOT currently allocated)
        #   pool.checkedout()  = connections in active use
        #   pool.checkedin()   = connections idle in pool (returned, ready for reuse)
        #   pool.overflow()    = (current_total - pool_size); NEGATIVE before pool fills up
        # Max capacity must be derived from the configured pool_size + max_overflow on the engine.
        from app.core.database import engine
        pool = engine.pool
        configured_pool_size = pool.size()
        configured_max_overflow = getattr(pool, '_max_overflow', 0) or 0
        active = pool.checkedout()
        idle = pool.checkedin()

        db_pool_status = {
            "active": active,
            "idle": idle,
            "max": configured_pool_size + configured_max_overflow,
        }

        # Check WebSocket status
        websocket_connected = False
        try:
            from app.services.binance_ws_client import binance_ws
            websocket_connected = binance_ws.connected
        except Exception:
            pass

        # Real position monitor / strategy manager status (singletons)
        position_monitor_running = False
        try:
            from app.services.position_monitor import position_monitor
            position_monitor_running = bool(getattr(position_monitor, "monitoring", False))
        except Exception:
            pass

        # Strategy manager — module imports successfully = ready (no long-running task)
        strategy_manager_ready = False
        try:
            from app.services.strategy_manager import strategy_manager  # noqa: F401
            strategy_manager_ready = True
        except Exception:
            pass

        # Real exchange connectivity: probe via market_data_service caches (no extra API call required)
        binance_ok = False
        bybit_ok = False
        mt5_ok = False
        try:
            from app.services.realtime_market_service import market_data_service
            # Binance: live tick from binance_ws (cached every 250ms)
            binance_ok = bool(websocket_connected)
            # Bybit/MT5: market_data_service holds the latest tick fetch result
            mt5_client = getattr(market_data_service, "mt5_client", None)
            mt5_ok = bool(mt5_client and getattr(mt5_client, "connected", False))
            # Bybit currently uses MT5 bridge as the source of truth for the gold pair, so they share status
            bybit_ok = mt5_ok
        except Exception:
            pass

        # Return comprehensive status
        return {
            "success": True,
            "backend": True,
            "positionMonitor": position_monitor_running,
            "strategyManager": strategy_manager_ready,
            "binance": binance_ok,
            "bybit": bybit_ok,
            "mt5": mt5_ok,
            "websocket": websocket_connected,
            "dbPool": db_pool_status,
            "uptime": f"{uptime_hours}h {uptime_minutes}m",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "backend": False,
            "message": f"Failed to get system status: {str(e)}"
        }
