import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models_rbac import Role, Permission, RolePermission, UserRoleAssignment
from app.db.models_auth import User
from app.db.session import get_db
from app.middleware.permissions import require_admin, require_super_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/rbac", tags=["admin-rbac"])


# ─── Request schemas ───

class CreateRoleRequest(BaseModel):
    role_name: str
    role_code: str
    description: str | None = None
    is_active: bool = True


class UpdateRoleRequest(BaseModel):
    role_name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AssignPermissionRequest(BaseModel):
    permission_id: int


class AssignRoleRequest(BaseModel):
    role_id: int


# ─── Role CRUD ───

@router.get("/roles")
def list_roles(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rows = (
        db.query(
            Role,
            func.count(RolePermission.id).label("perm_count"),
        )
        .outerjoin(RolePermission, Role.id == RolePermission.role_id)
        .group_by(Role.id)
        .order_by(Role.id)
        .all()
    )
    return [
        {
            "id": r.id,
            "role_name": r.role_name,
            "role_code": r.role_code,
            "description": r.description or "",
            "is_active": r.is_active,
            "is_system": r.is_system,
            "permission_count": cnt,
            "created_at": str(r.created_at) if r.created_at else None,
        }
        for r, cnt in rows
    ]


@router.post("/roles")
def create_role(req: CreateRoleRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    if db.query(Role).filter(Role.role_code == req.role_code).first():
        raise HTTPException(status_code=400, detail="角色编码已存在")
    role = Role(
        role_name=req.role_name,
        role_code=req.role_code,
        description=req.description,
        is_active=req.is_active,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return {"message": "角色创建成功", "id": role.id}


@router.put("/roles/{role_id}")
def update_role(role_id: int, req: UpdateRoleRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if req.role_name is not None:
        role.role_name = req.role_name
    if req.description is not None:
        role.description = req.description
    if req.is_active is not None:
        role.is_active = req.is_active
    db.commit()
    return {"message": "角色更新成功"}


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_system:
        raise HTTPException(status_code=400, detail="系统角色不可删除")
    user_count = db.query(UserRoleAssignment).filter(UserRoleAssignment.role_id == role_id).count()
    if user_count > 0:
        raise HTTPException(status_code=400, detail=f"该角色已分配给 {user_count} 个用户，请先解除分配")
    db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
    db.delete(role)
    db.commit()
    return {"message": "角色删除成功"}


# ─── Role ↔ Permission ───

@router.get("/roles/{role_id}/permissions")
def get_role_permissions(role_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    ids = (
        db.query(RolePermission.permission_id)
        .filter(RolePermission.role_id == role_id)
        .all()
    )
    return [row[0] for row in ids]


@router.post("/roles/{role_id}/permissions")
def assign_permission(role_id: int, req: AssignPermissionRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    exists = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == role_id, RolePermission.permission_id == req.permission_id)
        .first()
    )
    if exists:
        return {"message": "权限已存在"}
    db.add(RolePermission(role_id=role_id, permission_id=req.permission_id))
    db.commit()
    return {"message": "权限分配成功"}


@router.delete("/roles/{role_id}/permissions/{permission_id}")
def revoke_permission(role_id: int, permission_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rp = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
        .first()
    )
    if not rp:
        raise HTTPException(status_code=404, detail="权限分配不存在")
    db.delete(rp)
    db.commit()
    return {"message": "权限移除成功"}


# ─── Permissions ───

@router.get("/permissions")
def list_permissions(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    perms = db.query(Permission).order_by(Permission.resource_type, Permission.sort_order, Permission.id).all()
    return [
        {
            "id": p.id,
            "permission_name": p.permission_name,
            "permission_code": p.permission_code,
            "resource_type": p.resource_type,
            "resource_path": p.resource_path or "",
            "http_method": p.http_method or "",
            "description": p.description or "",
            "sort_order": p.sort_order,
            "is_active": p.is_active,
        }
        for p in perms
    ]


# ─── User ↔ Role ───

@router.get("/users/{user_id}/roles")
def get_user_roles(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    ids = (
        db.query(UserRoleAssignment.role_id)
        .filter(UserRoleAssignment.user_id == user_id)
        .all()
    )
    return [row[0] for row in ids]


@router.post("/users/{user_id}/roles")
def assign_user_role(user_id: int, req: AssignRoleRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    if not db.query(User).filter(User.id == user_id).first():
        raise HTTPException(status_code=404, detail="用户不存在")
    exists = (
        db.query(UserRoleAssignment)
        .filter(UserRoleAssignment.user_id == user_id, UserRoleAssignment.role_id == req.role_id)
        .first()
    )
    if exists:
        return {"message": "角色已分配"}
    db.add(UserRoleAssignment(user_id=user_id, role_id=req.role_id))
    db.commit()
    return {"message": "角色分配成功"}


@router.delete("/users/{user_id}/roles/{role_id}")
def revoke_user_role(user_id: int, role_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    ur = (
        db.query(UserRoleAssignment)
        .filter(UserRoleAssignment.user_id == user_id, UserRoleAssignment.role_id == role_id)
        .first()
    )
    if not ur:
        raise HTTPException(status_code=404, detail="角色分配不存在")
    db.delete(ur)
    db.commit()
    return {"message": "角色移除成功"}


# ─── Seed ───

SEED_PERMISSIONS = [
    # ── Menu permissions (17) ──
    ("menu", "menu:admin:dashboard", "总控面板", "/admin/dashboard", None, "管理后台首页", 1),
    ("menu", "menu:admin:users", "用户管理", "/admin/users", None, "用户账号/绑定/引擎控制", 2),
    ("menu", "menu:admin:global_rules", "通用规则", "/admin/global-rules", None, "系统默认规则管理", 3),
    ("menu", "menu:admin:coins", "币种管理", "/admin/coins", None, "新币标记/下架/开仓控制", 4),
    ("menu", "menu:admin:market", "行情检测", "/admin/market-monitor", None, "K线/涨幅榜/公告/黑名单审核", 5),
    ("menu", "menu:admin:ws_monitor", "WS监控", "/admin/ws-monitor", None, "WebSocket实时连接监控", 6),
    ("menu", "menu:admin:notifications", "通知服务", "/admin/notifications", None, "飞书/邮件/广播/模板", 7),
    ("menu", "menu:admin:ssl", "SSL证书", "/admin/ssl", None, "证书上传/部署/扫描", 8),
    ("menu", "menu:admin:proxies", "代理管理", "/admin/proxies", None, "代理池+IPIPGO订单", 9),
    ("menu", "menu:admin:system", "系统管理", "/admin/system", None, "版本/数据库/角色权限", 10),
    ("menu", "menu:admin:audit", "审计日志", "/admin/audit", None, "操作日志查询", 11),
    ("menu", "menu:admin:ai_support", "AI客服", "/admin/ai-support", None, "FAQ知识库+AI配置", 12),
    ("menu", "menu:coin:dashboard", "用户端-总览", "/dashboard", None, "交易主控台", 13),
    ("menu", "menu:coin:spreads", "用户端-利差监控", "/spreads", None, "利差/K线/涨幅榜", 14),
    ("menu", "menu:coin:positions", "用户端-当前持仓", "/positions", None, "持仓实时查看", 15),
    ("menu", "menu:coin:history", "用户端-平仓历史", "/history", None, "历史交易记录", 16),
    ("menu", "menu:coin:accounts", "用户端-账户管理", "/accounts", None, "主账户/子账户管理", 17),
    # ── API permissions (32) ──
    ("api", "user:list", "查看用户列表", "/api/admin/users", "GET", "获取所有用户信息", 1),
    ("api", "user:create", "创建用户", "/api/admin/users", "POST", "新建系统用户", 2),
    ("api", "user:update", "编辑用户", "/api/admin/users/{id}", "PUT", "修改用户资料", 3),
    ("api", "user:delete", "删除用户", "/api/admin/users/{id}", "DELETE", "停用/删除用户", 4),
    ("api", "user:reset_password", "重置密码", "/api/admin/users/{id}/reset-password", "POST", "重置用户密码", 5),
    ("api", "user:bind_account", "绑定账户", "/api/admin/users/{id}/sub-accounts", "POST", "主/子账户CRUD", 6),
    ("api", "engine:control", "引擎启停", "/api/admin/engine/users/{id}", "POST", "启动/停止用户引擎", 7),
    ("api", "engine:view", "查看持仓/日志", "/api/engine/positions", "GET", "持仓/交易日志查看", 8),
    ("api", "engine:trade", "交易操作", "/api/engine", "POST", "推送/移除/划转/还币", 9),
    ("api", "global_rules:view", "查看规则", "/api/admin/global-rules", "GET", "查看系统默认规则", 10),
    ("api", "global_rules:update", "修改规则", "/api/admin/global-rules", "PUT", "修改系统默认规则", 11),
    ("api", "global_rules:broadcast", "分发规则", "/api/admin/global-rules/broadcast", "POST", "广播规则给所有用户", 12),
    ("api", "coins:list", "查看币种", "/api/coins", "GET", "获取币种列表", 13),
    ("api", "coins:manage", "管理币种", "/api/coins/{symbol}", "PATCH", "标记新币/下架/开仓控制", 14),
    ("api", "coins:sync", "同步交易量", "/api/coins/sync-volume", "POST", "同步币种交易量数据", 15),
    ("api", "market:view", "行情查看", "/api/market", "GET", "K线/涨幅榜查看", 16),
    ("api", "market:announcements", "公告监控", "/api/admin/market/announcements", "GET", "查看币安公告", 17),
    ("api", "market:blacklist_review", "黑名单审核", "/api/admin/market/blacklist-confirm", "POST", "确认/忽略待审核黑名单", 18),
    ("api", "notify:feishu_config", "飞书配置", "/api/admin/notifications/feishu-config", "PUT", "飞书全局+用户级配置", 19),
    ("api", "notify:feishu_test", "飞书测试", "/api/admin/notifications/feishu-test", "POST", "发送飞书测试消息", 20),
    ("api", "notify:email_config", "邮件配置", "/api/admin/notifications/email-config", "PUT", "邮件SMTP配置管理", 21),
    ("api", "notify:email_test", "邮件测试", "/api/admin/notifications/email-test", "POST", "发送测试邮件", 22),
    ("api", "notify:broadcast", "站内广播", "/api/admin/notifications/broadcast", "POST", "推送站内广播通知", 23),
    ("api", "notify:templates", "模板管理", "/api/admin/notifications/templates", "POST", "CRUD通知模板", 24),
    ("api", "ssl:manage", "SSL证书管理", "/api/admin/ssl-certs", "POST", "上传/部署/删除/扫描", 25),
    ("api", "proxy:manage", "代理管理", "/api/admin/proxies", "POST", "CRUD+绑定+健康检查", 26),
    ("api", "proxy:ipipgo", "IPIPGO订单", "/api/admin/ipipgo/orders", "GET", "查看/同步IPIPGO", 27),
    ("api", "system:info", "系统信息", "/api/admin/system/info", "GET", "版本/数据库统计", 28),
    ("api", "system:git", "代码管理", "/api/admin/system/git-push", "POST", "推送/回滚代码", 29),
    ("api", "system:database", "数据库管理", "/api/admin/system/database", "POST", "备份/清理/查看表", 30),
    ("api", "system:rbac", "角色权限管理", "/api/admin/rbac", "POST", "RBAC完整CRUD", 31),
    ("api", "audit:view", "审计日志", "/api/admin/audit", "GET", "查看操作日志", 32),
    ("api", "ai:faq", "FAQ管理", "/api/admin/ai/faq", "POST", "CRUD FAQ知识库", 33),
    ("api", "ai:config", "AI配置", "/api/admin/ai/config", "PUT", "AI客服配置", 34),
    # ── Button permissions (10) ──
    ("button", "btn:user:create", "创建用户按钮", None, None, "用户管理页新建", 1),
    ("button", "btn:user:delete", "删除用户按钮", None, None, "高危：删除用户", 2),
    ("button", "btn:engine:start", "启动引擎", None, None, "引擎控制启动", 3),
    ("button", "btn:engine:stop", "停止引擎", None, None, "引擎控制停止", 4),
    ("button", "btn:rules:broadcast", "分发规则", None, None, "高危：广播覆盖所有用户", 5),
    ("button", "btn:ssl:deploy", "部署证书", None, None, "影响nginx配置", 6),
    ("button", "btn:system:git_push", "代码推送", None, None, "远程git push", 7),
    ("button", "btn:system:backup", "数据库备份", None, None, "DB dump操作", 8),
    ("button", "btn:system:cleanup", "清理数据", None, None, "删除旧记录", 9),
    ("button", "btn:notify:broadcast", "发送广播", None, None, "站内实时通知", 10),
]

SEED_ROLES = [
    {
        "role_name": "超级管理员",
        "role_code": "super_admin",
        "description": "系统最高权限，拥有所有功能访问权",
        "is_system": True,
        "permissions": "__all__",
    },
    {
        "role_name": "系统管理员",
        "role_code": "system_admin",
        "description": "管理全部业务功能，无RBAC管理权限",
        "is_system": False,
        "permissions": "__all_except__:system:rbac",
    },
    {
        "role_name": "交易管理员",
        "role_code": "trade_admin",
        "description": "管理用户、引擎、币种、行情、通知",
        "is_system": False,
        "permissions": [
            "menu:admin:dashboard", "menu:admin:users", "menu:admin:global_rules",
            "menu:admin:coins", "menu:admin:market", "menu:admin:ws_monitor",
            "menu:admin:notifications",
            "menu:coin:dashboard", "menu:coin:spreads", "menu:coin:positions",
            "menu:coin:history", "menu:coin:accounts",
            "user:list", "user:create", "user:update", "user:reset_password", "user:bind_account",
            "engine:control", "engine:view", "engine:trade",
            "global_rules:view", "global_rules:update", "global_rules:broadcast",
            "coins:list", "coins:manage", "coins:sync",
            "market:view", "market:announcements", "market:blacklist_review",
            "notify:feishu_config", "notify:feishu_test", "notify:email_config",
            "notify:email_test", "notify:broadcast", "notify:templates",
            "btn:user:create", "btn:engine:start", "btn:engine:stop",
            "btn:rules:broadcast", "btn:notify:broadcast",
        ],
    },
    {
        "role_name": "运维管理员",
        "role_code": "ops_admin",
        "description": "管理SSL、代理、系统运维、审计日志",
        "is_system": False,
        "permissions": [
            "menu:admin:dashboard", "menu:admin:ssl", "menu:admin:proxies",
            "menu:admin:system", "menu:admin:audit", "menu:admin:ai_support",
            "ssl:manage", "proxy:manage", "proxy:ipipgo",
            "system:info", "system:git", "system:database",
            "audit:view", "ai:faq", "ai:config",
            "btn:ssl:deploy", "btn:system:git_push", "btn:system:backup", "btn:system:cleanup",
        ],
    },
    {
        "role_name": "观察员",
        "role_code": "observer",
        "description": "只读权限，仅查看面板和数据",
        "is_system": False,
        "permissions": [
            "menu:admin:dashboard",
            "menu:coin:dashboard", "menu:coin:spreads", "menu:coin:positions", "menu:coin:history",
            "engine:view", "global_rules:view", "coins:list", "market:view", "audit:view",
        ],
    },
]


@router.post("/seed")
def seed_rbac(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    perm_map: dict[str, int] = {}
    created_perms = 0
    for rtype, code, name, path, method, desc, sort in SEED_PERMISSIONS:
        existing = db.query(Permission).filter(Permission.permission_code == code).first()
        if existing:
            perm_map[code] = existing.id
        else:
            p = Permission(
                permission_name=name,
                permission_code=code,
                resource_type=rtype,
                resource_path=path,
                http_method=method,
                description=desc,
                sort_order=sort,
            )
            db.add(p)
            db.flush()
            perm_map[code] = p.id
            created_perms += 1

    all_perm_ids = set(perm_map.values())
    created_roles = 0
    for role_def in SEED_ROLES:
        existing = db.query(Role).filter(Role.role_code == role_def["role_code"]).first()
        if existing:
            role = existing
        else:
            role = Role(
                role_name=role_def["role_name"],
                role_code=role_def["role_code"],
                description=role_def["description"],
                is_system=role_def["is_system"],
            )
            db.add(role)
            db.flush()
            created_roles += 1

        perm_spec = role_def["permissions"]
        if perm_spec == "__all__":
            target_ids = all_perm_ids
        elif isinstance(perm_spec, str) and perm_spec.startswith("__all_except__:"):
            exclude_code = perm_spec[len("__all_except__:"):]
            exclude_id = perm_map.get(exclude_code)
            target_ids = all_perm_ids - ({exclude_id} if exclude_id else set())
        else:
            target_ids = {perm_map[c] for c in perm_spec if c in perm_map}

        current_ids = {
            row[0]
            for row in db.query(RolePermission.permission_id)
            .filter(RolePermission.role_id == role.id)
            .all()
        }
        to_add = target_ids - current_ids
        for pid in to_add:
            db.add(RolePermission(role_id=role.id, permission_id=pid))

    db.commit()
    return {
        "message": "RBAC 初始化完成",
        "created_permissions": created_perms,
        "created_roles": created_roles,
        "total_permissions": len(perm_map),
        "total_roles": len(SEED_ROLES),
    }
