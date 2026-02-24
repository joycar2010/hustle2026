"""System management API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.core.database import get_db
from app.core.security import get_current_user_id

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
    """Backup entire database"""
    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}_UTC.sql"

        # Note: This is a placeholder. In production, you would use pg_dump
        # via subprocess or a proper backup solution
        return {
            "message": "Database backup initiated",
            "filename": filename,
            "note": "Backup functionality requires pg_dump configuration"
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
        filename = request.filename
        # Note: This is a placeholder. In production, you would use pg_restore
        return {
            "message": "Database restore initiated",
            "filename": filename,
            "note": "Restore functionality requires pg_restore configuration"
        }
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

        return {
            "frontend_version": "1.0.0",
            "frontend_build_time": "2026-02-19 12:00:00",
            "backend_version": "1.0.0",
            "python_version": "3.9+",
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
        # In a real implementation, this would read from a backups directory
        # For now, return a mock list
        import os
        from pathlib import Path
        
        backup_dir = Path("backups")
        backups = []
        
        if backup_dir.exists():
            for file in backup_dir.glob("*.sql"):
                stat = file.stat()
                backups.append({
                    "filename": file.name,
                    "size": f"{stat.st_size / 1024 / 1024:.2f} MB",
                    "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
        
        # Sort by creation time (newest first)
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
    """Get Git commit history"""
    try:
        import subprocess

        # Fetch latest commits from remote to sync with GitHub
        fetch_result = subprocess.run(
            ["git", "fetch", "origin"],
            capture_output=True,
            text=True,
            cwd=".."
        )

        # Don't fail if fetch fails (might be offline), just log it
        if fetch_result.returncode != 0:
            print(f"Warning: Git fetch failed: {fetch_result.stderr}")

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

        # Get last 20 commits from current branch
        result = subprocess.run(
            ["git", "log", current_branch, "--pretty=format:%H|%an|%ae|%ad|%s", "--date=format:%Y-%m-%d %H:%M:%S", "-20"],
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
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, str]:
    """Push current version to GitHub"""
    try:
        import subprocess

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

        # Check if there are changes to commit
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if status_result.stdout.strip():
            # There are uncommitted changes - commit them
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " UTC"
            if remark:
                commit_message = f"Backup: {timestamp} - {remark}"
            else:
                commit_message = f"Backup: {timestamp}"

            # Add all changes
            add_result = subprocess.run(
                ["git", "add", "."],
                capture_output=True,
                text=True,
                cwd=".."
            )

            if add_result.returncode != 0:
                raise Exception(f"Git add failed: {add_result.stderr}")

            # Commit changes
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True,
                text=True,
                cwd=".."
            )

            if commit_result.returncode != 0:
                raise Exception(f"Git commit failed: {commit_result.stderr}")

        # Push to remote with current branch
        # Use force push for backup branches to overwrite remote if needed
        push_args = ["git", "push"]
        if current_branch.startswith("backup-"):
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

        return {
            "message": f"Successfully pushed to GitHub branch: {current_branch}",
            "branch": current_branch,
            "output": push_result.stdout
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to push to GitHub: {str(e)}"
        )


@router.post("/github/rollback")
async def rollback_version(
    request: RollbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, str]:
    """Rollback to a specific version"""
    try:
        import subprocess

        # Use hash if provided, otherwise use version (for backward compatibility)
        target = request.hash or request.version
        if not target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either hash or version must be provided"
            )

        # Reset to the specified commit
        reset_result = subprocess.run(
            ["git", "reset", "--hard", target],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if reset_result.returncode != 0:
            raise Exception(f"Git reset failed: {reset_result.stderr}")

        return {
            "message": f"Successfully rolled back to {target[:7]}",
            "note": "Please restart the system for changes to take effect"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback: {str(e)}"
        )


@router.delete("/github/version/{version_hash}")
async def delete_version(
    version_hash: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, str]:
    """Delete/revert a specific version"""
    try:
        import subprocess

        # Use git revert to create a new commit that undoes the changes
        revert_result = subprocess.run(
            ["git", "revert", "--no-edit", version_hash],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if revert_result.returncode != 0:
            raise Exception(f"Git revert failed: {revert_result.stderr}")

        return {
            "message": f"Successfully reverted version {version_hash[:7]}",
            "note": "A new commit has been created to undo the changes"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete version: {str(e)}"
        )


@router.get("/logs/trading")
async def get_trading_logs(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Get trading statistics calculation logs"""
    try:
        import logging
        import io

        # Get the logger used in trading.py
        logger = logging.getLogger('app.api.v1.trading')

        # Try to read recent logs from memory handler if available
        # For now, return a sample structure
        # In production, you might want to use a log aggregation service

        logs = []

        # Check if there's a file handler attached to the logger
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                try:
                    with open(handler.baseFilename, 'r', encoding='utf-8') as f:
                        lines = f.readlines()[-500:]  # Get last 500 lines
                        for line in lines:
                            if line.strip():
                                # Parse log line
                                parts = line.split(' ', 3)
                                if len(parts) >= 4:
                                    logs.append({
                                        'timestamp': f"{parts[0]} {parts[1]}",
                                        'level': parts[2],
                                        'message': parts[3].strip()
                                    })
                except Exception as e:
                    print(f"Error reading log file: {e}")

        # If no logs from file, return empty list
        # The frontend will show sample data
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

