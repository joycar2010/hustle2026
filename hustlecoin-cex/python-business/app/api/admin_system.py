import os
import sys
import subprocess
import threading
import time
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import MetaData, Table, insert, text, update

from app.config import settings
from app.db.session import get_db
from app.db.models import AiCoinConfig
from app.db.models_auth import User
from app.db.models_monitor import ServerMonitorSubscription
from app.db.models_notify import NotificationTemplate
from app.middleware.permissions import require_super_admin
from app.services.aicoin_config import (
    AiCoinConfigStorageError,
    clean_aicoin_key,
    clean_aicoin_secret,
    choose_active_aicoin_row,
    is_aicoin_masked,
    redact_aicoin_error,
    read_aicoin_config_rows,
    resolve_aicoin_credentials,
)

router = APIRouter(prefix="/api/admin/system", tags=["admin-system"])

_start_time = time.time()
_BRANCH = "coin"
_SSH_KEY = os.path.expanduser("~/.ssh/cex-trading-key2.pem")
_RUST_HOST = getattr(settings, "rust_host", None) or os.getenv("CEX_RUST_HOST") or "57.181.214.206"
_RUST_PROBE_HOST = os.getenv("CEX_RUST_PROBE_HOST", "10.0.1.139")
_SSH_USER = "ec2-user"
_RUST_PROJECT_DIR = os.getenv("CEX_RUST_PROJECT_DIR", "/home/ec2-user/coin-project")
_VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "VERSION")


def _local_ops_metrics() -> dict:
    try:
        load = list(os.getloadavg())
    except (AttributeError, OSError):
        load = []
    disk = shutil.disk_usage("/")
    return {
        "host": "18.176.76.127",
        "name": "Python Backend",
        "reachable": True,
        "service": "cex-business",
        "service_status": "active",
        "load": [round(float(v), 2) for v in load],
        "disk_used_pct": round(disk.used * 100 / disk.total, 1) if disk.total else None,
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }
_PYTHON_HOST = os.getenv("CEX_PYTHON_HOST", "18.176.76.127")
_monitor_state: dict[str, bool] = {}
_monitor_state_lock = threading.Lock()


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


def _parallel_ssh_commands(commands: dict[str, tuple[str, str]], total_timeout: float = 16.0) -> dict[str, str]:
    """Run independent remote status probes together.

    Version status is informational. A down Rust host must degrade only its
    own card instead of blocking the entire admin page behind four sequential
    SSH connect timeouts (which previously took close to a minute).
    """
    if not commands:
        return {}
    result: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(commands)), thread_name_prefix="admin-version") as pool:
        futures = {
            pool.submit(_ssh_command, host, command): key
            for key, (host, command) in commands.items()
        }
        try:
            for future in as_completed(futures, timeout=total_timeout):
                key = futures[future]
                try:
                    result[key] = future.result()
                except Exception:
                    result[key] = ""
        except TimeoutError:
            # Any unfinished probe is represented as an unavailable value.
            # The executor threads are daemon-like short-lived subprocess
            # wrappers and will finish/timeout independently.
            pass
    for key in commands:
        result.setdefault(key, "")
    return result


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


# ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ System Info ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬

@router.get("/info")
def system_info(request: Request):
    require_super_admin(request)

    uptime_sec = int(time.time() - _start_time)
    hours, rem = divmod(uptime_sec, 3600)
    minutes, secs = divmod(rem, 60)

    git_commit = ""
    try:
        root = _repo_root()
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL, timeout=5,
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


# ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ Multi-Service Versions ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬

def _monitor_probe(host: str, services: list[str]) -> dict:
    parts = ["printf 'hostname=%s\\n' \"$(hostname)\";", "printf 'load1=%s\\n' \"$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)\";", "printf 'memory=%s\\n' \"$(free -m 2>/dev/null | awk '/^Mem:/{if($2>0) printf \"%.1f\",($3/$2)*100; else print 0}' || echo 0)\";", "printf 'disk=%s\\n' \"$(df -P / 2>/dev/null | awk 'NR==2{gsub(/%/,\"\",$5);print $5}' || echo 0)\";"]
    for service in services:
        safe = ''.join(c if c.isalnum() or c in '_.-' else '_' for c in service)
        parts.append(f"printf 'svc_{safe}=%s\\n' \"$(systemctl is-active {service} 2>/dev/null || echo unknown)\";")
    started = time.monotonic(); raw = _ssh_command(host, ''.join(parts), timeout=5)
    values = {}
    for line in raw.splitlines():
        if '=' in line:
            k, v = line.split('=', 1); values[k] = v.strip()
    statuses = {s: values.get('svc_' + ''.join(c if c.isalnum() or c in '_.-' else '_' for c in s), 'unknown') for s in services}
    reachable = bool(values.get('hostname')); healthy = reachable and all(v == 'active' for v in statuses.values())
    return {'host': host, 'reachable': reachable, 'healthy': healthy, 'status': 'healthy' if healthy else ('unreachable' if not reachable else 'degraded'), 'cpu_load_1m': float(values.get('load1') or 0), 'memory_percent': float(values.get('memory') or 0), 'disk_percent': float(values.get('disk') or 0), 'services': statuses, 'latency_ms': round((time.monotonic() - started) * 1000)}


@router.get("/versions")
def service_versions(request: Request):
    require_super_admin(request)
    root = _repo_root()
    try:
        backend_commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=root, timeout=5).decode().strip()
        frontend_commit = subprocess.check_output(["git", "log", "-1", "--format=%h", "--", "frontend/", "frontend-admin/", "python-business/static/"], cwd=root, timeout=5).decode().strip()
    except Exception:
        backend_commit = frontend_commit = ""
    return {"services": [
        {"service": "Python Backend", "host": "18.176.76.127", "version": _read_version(), "git_commit": backend_commit, "status": "running"},
        {"service": "Frontend", "host": "coin.hustle2026.xyz", "version": _read_version(), "git_commit": frontend_commit or backend_commit, "status": "deployed"},
    ]}

@router.get('/monitoring')
def server_monitoring(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    # The Python probe runs inside this service; SSHing back to its public IP
    # is blocked by the security group and incorrectly reported the healthy
    # backend as unreachable.  Use local metrics for it and SSH only Rust.
    local = _local_ops_metrics()
    python_probe = {'host': _PYTHON_HOST, 'reachable': True, 'healthy': True,
                    'status': 'healthy', 'cpu_load_1m': float((local.get('load') or [0])[0]),
                    'memory_percent': 0.0, 'disk_percent': float(local.get('disk_used_pct') or 0),
                    'services': {'cex-business': 'active'}, 'latency_ms': 0}
    with ThreadPoolExecutor(max_workers=1) as pool:
        rust_probe = pool.submit(_monitor_probe, _RUST_PROBE_HOST, ['cex-engine']).result()
    rust_probe["host"] = _RUST_HOST
    probes = {'rust': rust_probe, 'python': python_probe}
    if any(not p['healthy'] for p in probes.values()):
        try:
            if not db.query(NotificationTemplate).filter(NotificationTemplate.template_name == 'server_fault').first():
                db.add(NotificationTemplate(template_name='server_fault', category='system', title_template='Server fault', content_template='Server {target} ({host}) status: {status}', enable_feishu=True, enable_email=True, enable_marquee=True, priority=1, cooldown_seconds=300, is_enabled=True)); db.commit()
        except Exception:
            db.rollback()
    # Route failures through the notification template system; its Redis throttle
    # prevents repeated dashboard refreshes from spamming operators.
    for name, probe in probes.items():
        if not probe['healthy']:
            try:
                from app.services.notifier import fire_template
                threading.Thread(target=fire_template, args=('server_fault', {'target': name, 'host': probe['host'], 'status': probe['status']}), daemon=True).start()
            except Exception:
                pass
    return {
        'checked_at': datetime.utcnow().isoformat() + 'Z',
        'servers': probes,
        'requested_rust_host': _RUST_HOST,
        'rust_host_note': f'Probe via VPC private address {_RUST_PROBE_HOST}; public display address {_RUST_HOST}',
    }

class MonitorSubscriptionRequest(BaseModel):
    target: str; enabled: bool = True; feishu: bool = True; email: bool = True

@router.get('/monitoring/subscriptions')
def monitor_subscriptions(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request); users = db.query(User).filter(User.is_active.is_(True)).order_by(User.username).all(); rows = {(r.user_id, r.target): r for r in db.query(ServerMonitorSubscription).all()}; result = []
    for user in users:
        for target in ('rust', 'python'):
            row = rows.get((user.id, target)); result.append({'id': row.id if row else None, 'user_id': user.id, 'username': user.username, 'email_address': user.email, 'feishu_open_id': user.feishu_open_id, 'target': target, 'enabled': bool(row.enabled) if row else False, 'feishu': bool(row.feishu) if row else bool(user.feishu_open_id), 'email': bool(row.email) if row else bool(user.email)})
    return result

@router.put('/monitoring/subscriptions/{user_id}')
def update_monitor_subscription(user_id: int, req: MonitorSubscriptionRequest, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    if req.target not in ('rust', 'python'): raise HTTPException(status_code=400, detail='target must be rust or python')
    if not db.query(User).filter(User.id == user_id).first(): raise HTTPException(status_code=404, detail='user not found')
    row = db.query(ServerMonitorSubscription).filter(ServerMonitorSubscription.user_id == user_id, ServerMonitorSubscription.target == req.target).first()
    if not row: row = ServerMonitorSubscription(user_id=user_id, target=req.target); db.add(row)
    row.enabled, row.feishu, row.email = req.enabled, req.feishu, req.email; db.commit(); return {'saved': True, 'user_id': user_id, 'target': req.target, 'enabled': row.enabled, 'feishu': row.feishu, 'email': row.email}


def service_versions(request: Request):
    require_super_admin(request)

    uptime_sec = int(time.time() - _start_time)
    hours, rem = divmod(uptime_sec, 3600)
    minutes, secs = divmod(rem, 60)

    backend_commit = ""
    root = None
    try:
        root = _repo_root()
        backend_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        pass

    ver = _read_version()

    backend_info = {
        "service": "Python Backend",
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
            cwd=root, stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        frontend_deploy_time = subprocess.check_output(
            ["git", "log", "-1", "--format=%ai", "--", "frontend/", "frontend-admin/", "python-business/static/"],
            cwd=root, stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        pass

    frontend_info = {
        "service": "Frontend",
        "host": "coin.hustle2026.xyz",
        "version": ver,
        "git_commit": frontend_commit or backend_commit,
        "last_deploy": frontend_deploy_time[:19] if frontend_deploy_time else "-",
        "status": "deployed",
    }

    rust_probe = _parallel_ssh_commands({
        "status": (_RUST_PROBE_HOST, "systemctl is-active cex-engine 2>/dev/null || echo stopped"),
        "version": (_RUST_PROBE_HOST,
            f"grep '^version' {_RUST_PROJECT_DIR}/rust-engine/Cargo.toml 2>/dev/null"
            " | head -1 | sed 's/.*\"\\(.*\\)\"/\\1/'"),
        "uptime": (_RUST_PROBE_HOST,
            "systemctl show cex-engine --property=ActiveEnterTimestamp --value 2>/dev/null"),
        "binary_time": (_RUST_PROBE_HOST,
            f"stat -c '%y' {_RUST_PROJECT_DIR}/rust-engine/target/release/cex-engine 2>/dev/null"
            " | cut -d. -f1"),
    })
    rust_status = rust_probe["status"]
    rust_version = rust_probe["version"]
    rust_uptime = rust_probe["uptime"]
    rust_binary_time = rust_probe["binary_time"]

    rust_info = {
        "service": "Rust Engine",
        "host": _RUST_HOST,
        "version": rust_version or "unknown",
        "git_commit": rust_binary_time or "-",
        "uptime": rust_uptime or "-",
        # Do not present a missing SSH route as an application failure.  The
        # endpoint remains responsive and the UI can distinguish unavailable
        # telemetry from a stopped Rust service.
        "status": rust_status or "unavailable",
        "status_reason": "SSH probe unavailable" if not rust_status else None,
    }

    return {"services": [frontend_info, backend_info, rust_info]}


@router.get("/server-monitor")
def server_monitor(request: Request):
    """Read-only operations telemetry for the Python and Rust hosts."""
    require_super_admin(request)
    probe = _parallel_ssh_commands({
        "status": (_RUST_PROBE_HOST, "systemctl is-active cex-engine 2>/dev/null || echo stopped"),
        "load": (_RUST_PROBE_HOST, "cut -d' ' -f1-3 /proc/loadavg 2>/dev/null"),
        "disk": (_RUST_PROBE_HOST, "df -P / | tail -1 | awk '{print $5, $4}'"),
    }, total_timeout=8.0)
    load = (probe.get("load") or "").split()
    disk = (probe.get("disk") or "").split()
    rust_reachable = bool(probe.get("status"))
    rust = {
        "host": _RUST_HOST,
        "name": "Rust Engine",
        "reachable": rust_reachable,
        "service": "cex-engine",
        "service_status": probe.get("status") or "unavailable",
        "load": [float(v) for v in load[:3] if v.replace('.', '', 1).isdigit()],
        "disk_used_pct": float(disk[0].rstrip('%')) if disk and disk[0].rstrip('%').replace('.', '', 1).isdigit() else None,
        "disk_free_gb": round(int(disk[1]) / 1024 / 1024, 2) if len(disk) > 1 and disk[1].isdigit() else None,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }
    return {"servers": [_local_ops_metrics(), rust]}


# ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ Git Operations (coin branch, no checkout needed) ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬

class GitPushRequest(BaseModel):
    message: str


class GitCommitRequest(BaseModel):
    commit_hash: str


@router.get("/git-history")
def git_history(request: Request):
    require_super_admin(request)

    try:
        root = _repo_root()
        try:
            ref = subprocess.check_output(["git", "rev-parse", "--verify", "origin/coin"], cwd=root, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        except Exception:
            ref = "HEAD"
        output = subprocess.check_output(
            ["git", "log", ref, "--format=%H|%h|%s|%an|%ai", "-20"],
            cwd=root, stderr=subprocess.DEVNULL, timeout=10,
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

# ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â:ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Â¹ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂªÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âª git-push ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¹Ã…â€œÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â£ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â²ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â°ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â«ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â½ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â´/ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¹Ã…â€œÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¹ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¹Ã…â€œ git ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ .git/index.lock ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â£ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡
# FastAPI ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â«ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¹ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂºÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¿ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¹ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â°ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢,ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ threading.Lock + ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ acquireÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â£ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡
_push_lock = threading.Lock()


def _repo_root() -> str:
    """git ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂºÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¹(ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â²ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¹ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â½ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Â¹ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂºÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â½ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¢ /home/ec2-user;ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ hustlecoin-cex/ ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¹,ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â½ GitHub ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¾ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â´)ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â£ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡"""
    return subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=os.path.dirname(_VERSION_FILE), stderr=subprocess.DEVNULL, timeout=10,
    ).decode().strip()


def _pull_rust_source(root: str) -> bool:
    """ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â½ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â½ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¾ Coin Rust ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂºÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¹ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â½ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â°ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â rust-engine ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂºÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¿ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂºÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂºÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â£ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡
    best-effort:ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â´ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­(ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â°ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â½ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â«ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â½)ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â£ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡"""
    proj = os.path.join(root, "hustlecoin-cex")
    cmd = (
        f'ssh -i {_SSH_KEY} -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10 '
        f'{_SSH_USER}@{_RUST_PROBE_HOST} '
        f'"cd {_RUST_PROJECT_DIR} && tar -cf - --exclude=target --exclude=.git '
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
    """Create a complete, bounded production snapshot and push it to coin."""
    require_super_admin(request)
    if not _push_lock.acquire(blocking=False):
        return {"status": "error", "output": "A backup push is already running"}
    try:
        root = _repo_root()
        project = os.path.join(root, "hustlecoin-cex")
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        message = (req.message or "20260910\u5b8c\u6574\u8dd1\u901a\u7248").strip() or "20260910\u5b8c\u6574\u8dd1\u901a\u7248"

        # Pull the current Rust source over the private VPC route.
        rust_ok = _pull_rust_source(root)
        if not rust_ok:
            return {"status": "error", "output": "Rust source snapshot failed; nothing was pushed"}

        # Database rotation is intentionally disabled. Reuse an existing dump
        # only when present; never invoke pg_dump or delete prior backups here.
        db_copy = None
        backup_root = os.getenv("CEX_BACKUP_ROOT", "/home/ec2-user/coin-backups/postgres")
        dumps = sorted(Path(backup_root).glob("*.dump*"), key=lambda x: x.stat().st_mtime, reverse=True)
        if dumps:
            db_dir = Path(project) / "production-backup" / "database"
            db_dir.mkdir(parents=True, exist_ok=True)
            for old in db_dir.glob("*.dump*"):
                old.unlink(missing_ok=True)
            db_copy = db_dir / "cex_trading-latest.dump"
            shutil.copy2(dumps[0], db_copy)

        # Stage all application source and built assets.  Force-add static/dist
        # trees so a global ignore rule cannot drop the deployable frontend.
        subprocess.check_output(["git", "add"] + [f"hustlecoin-cex/{d}" for d in _REPO_SUBDIRS], cwd=root, stderr=subprocess.STDOUT, timeout=120)
        subprocess.check_output(["git", "add", "-f", "hustlecoin-cex/python-business/static/spa", "hustlecoin-cex/python-business/static/admin-spa", "hustlecoin-cex/production-backup/database"], cwd=root, stderr=subprocess.STDOUT, timeout=60)
        staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=root, timeout=20).decode().splitlines()
        deleted = subprocess.check_output(["git", "diff", "--cached", "--diff-filter=D", "--name-only"], cwd=root, timeout=20).decode().splitlines()
        protected_deleted = [p for p in deleted if "/static/" in p or "/dist/" in p or p.startswith("hustlecoin-cex/frontend")]
        if protected_deleted:
            subprocess.run(["git", "reset", "-q", "--"] + protected_deleted, cwd=root, timeout=30, check=False)
            staged = [p for p in staged if p not in protected_deleted]
        unsafe = [p for p in staged if p.endswith((".env", ".pem", ".key")) or "/.env" in p or "/secrets/" in p]
        if unsafe:
            subprocess.run(["git", "reset", "-q", "--"] + unsafe, cwd=root, timeout=30, check=False)
        subprocess.run(["git", "tag", f"backup-{timestamp}"], cwd=root, timeout=10, check=False)
        commit = subprocess.run(["git", "commit", "-m", message], cwd=root, capture_output=True, text=True, timeout=180, check=False)
        if commit.returncode not in (0, 1):
            return {"status": "error", "output": (commit.stdout + commit.stderr)[-800:]}
        result = subprocess.check_output(["git", "push", "origin", f"HEAD:{_BRANCH}"], cwd=root, stderr=subprocess.STDOUT, timeout=240).decode(errors="replace")
        head = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=root, timeout=10).decode().strip()
        return {"status": "success", "output": result[-800:], "version": _read_version(), "rust_synced": True, "database_backup": db_copy.name if db_copy else None, "git_commit": head, "message": message}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.output.decode(errors="replace")[-800:] if e.output else str(e)}
    except Exception as e:
        return {"status": "error", "output": str(e)[:800]}
    finally:
        _push_lock.release()


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
            ["git", "push", "origin", f"HEAD:{_BRANCH}"],
            stderr=subprocess.STDOUT, timeout=60,
        ).decode()
        return {"status": "success", "output": result[:500]}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.output.decode()[:500] if e.output else str(e)}


# ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ Database Management ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬

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
    return {"status": "disabled", "output": "PostgreSQL compressed rotation is disabled by policy; existing backups were preserved"}


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


# ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ Role Permissions ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬

@router.get("/roles")
def list_roles(request: Request):
    require_super_admin(request)

    return [
        {
            "role": "SUPER_ADMIN",
            "description": "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂºÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¹Ã…â€œÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“ - ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â",
            "permissions": ["users", "engine", "system", "database", "ssl", "proxy", "audit", "ai"],
        },
        {
            "role": "ADMIN",
            "description": "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¹Ã…â€œÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“ - ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¿ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â",
            "permissions": ["engine", "ssl", "proxy", "audit"],
        },
        {
            "role": "USER",
            "description": "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¹ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· - ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â»ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂªÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®",
            "permissions": ["own_data"],
        },
    ]


# ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ AiCoin Config ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬

class AiCoinConfigUpdate(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None


def _active_aicoin_config(db: Session) -> tuple[dict | None, frozenset[str]]:
    """Return the selected row and the columns available in the live table.

    This intentionally uses the same resolver path as market consumers.  The
    old admin implementation queried the ORM model directly, which emitted a
    ``SELECT`` for optional columns and failed on pre-migration tables.  A
    mapping is sufficient for the read endpoint and lets the writer issue a
    Core update limited to columns known to exist.
    """
    try:
        rows, columns = read_aicoin_config_rows(db)
    except AiCoinConfigStorageError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="AiCoin configuration schema is not ready; run database migrations",
        ) from exc
    return choose_active_aicoin_row(rows), columns


@router.get("/aicoin-config")
def get_aicoin_config(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    cfg, _ = _active_aicoin_config(db)
    if not cfg:
        return {"api_key": "", "api_secret": ""}
    api_key = clean_aicoin_key(cfg.get("api_key"))
    api_secret = clean_aicoin_secret(cfg.get("api_secret"))
    return {
        "api_key": api_key,
        "api_secret": "****" if api_secret else "",
    }


@router.put("/aicoin-config")
def update_aicoin_config(req: AiCoinConfigUpdate, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    cfg, columns = _active_aicoin_config(db)
    values: dict[str, str | bool] = {}
    if req.api_key is not None:
        # Treat a legacy/UI mask as "keep existing", just like the Secret
        # field.  An explicit empty string remains a valid clear operation.
        key = req.api_key.strip()
        if key != "****":
            values["api_key"] = key
    if req.api_secret is not None:
        # The browser sends the displayed mask when the operator changes only
        # the key.  Compare the normalized value (and all supported mask
        # aliases) before deciding whether this is an explicit replacement;
        # padded `` **** `` must never become the stored Secret.
        secret = req.api_secret.strip()
        if not is_aicoin_masked(secret):
            values["api_secret"] = secret

    try:
        # Reflect the live table for writes as well.  Using the declarative
        # table here would attach its ``onupdate``/server-default expressions
        # for optional columns (notably ``updated_at``), causing an UPDATE
        # against a legacy table to reference columns that do not exist.
        live_table = Table(
            AiCoinConfig.__tablename__,
            MetaData(),
            autoload_with=db.get_bind(),
        )
        if cfg is not None:
            # A masked secret means "keep the existing value"; an empty
            # explicit value is still allowed to clear it.
            if values:
                db.execute(
                    update(live_table)
                    .where(live_table.c.id == int(cfg["id"]))
                    .values(**values)
                )
        else:
            # Keep INSERT valid on a legacy table that has only the three
            # required columns.  Newer optional columns retain server/defaults.
            values.setdefault("api_key", "")
            values.setdefault("api_secret", "")
            if "is_active" in columns:
                values["is_active"] = True
            db.execute(insert(live_table).values(**values))
        db.commit()
    except Exception as exc:  # noqa: BLE001 - return actionable control-plane error
        db.rollback()
        raise HTTPException(status_code=503, detail="AiCoin configuration could not be saved") from exc

    from app.api.market import _reset_aicoin
    _reset_aicoin()
    # The admin market router maintains its own client cache.  Reset both
    # caches so a saved credential takes effect for every AiCoin consumer.
    from app.api.admin_market import _reset_aicoin as _reset_admin_market_aicoin
    _reset_admin_market_aicoin()

    return {"message": "AiCoin config updated"}


@router.post("/aicoin-test")
async def test_aicoin(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    credentials = resolve_aicoin_credentials(db)
    if not credentials.configured:
        raise HTTPException(status_code=400, detail="AiCoin API Key/Secret ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂªÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â½ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â®")

    from app.services.aicoin_client import AiCoinClient
    try:
        client = AiCoinClient(credentials.api_key, credentials.api_secret)
        coins = await client.get_coin_list()
        return {"status": "ok", "coin_count": len(coins)}
    except Exception as e:
        safe = redact_aicoin_error(e)
        raise HTTPException(status_code=502, detail=f"AiCoin API ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¿ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â½ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¤ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â´ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥: {safe}")






