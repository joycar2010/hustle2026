"""
RBAC 初始化脚本 - 创建完整的角色和权限数据
"""
import asyncio
import asyncpg
import uuid
from datetime import datetime

# 权限定义
PERMISSIONS = [
    # 用户管理权限
    {"code": "user:list", "name": "查看用户列表", "type": "api", "path": "/api/v1/users"},
    {"code": "user:detail", "name": "查看用户详情", "type": "api", "path": "/api/v1/users/{id}"},
    {"code": "user:create", "name": "创建用户", "type": "api", "path": "/api/v1/users"},
    {"code": "user:update", "name": "更新用户", "type": "api", "path": "/api/v1/users/{id}"},
    {"code": "user:delete", "name": "删除用户", "type": "api", "path": "/api/v1/users/{id}"},

    # 角色管理权限
    {"code": "role:list", "name": "查看角色列表", "type": "api", "path": "/api/v1/rbac/roles"},
    {"code": "role:detail", "name": "查看角色详情", "type": "api", "path": "/api/v1/rbac/roles/{id}"},
    {"code": "role:create", "name": "创建角色", "type": "api", "path": "/api/v1/rbac/roles"},
    {"code": "role:update", "name": "更新角色", "type": "api", "path": "/api/v1/rbac/roles/{id}"},
    {"code": "role:delete", "name": "删除角色", "type": "api", "path": "/api/v1/rbac/roles/{id}"},
    {"code": "role:assign_permission", "name": "分配角色权限", "type": "api", "path": "/api/v1/rbac/roles/{id}/permissions"},

    # 权限管理权限
    {"code": "permission:list", "name": "查看权限列表", "type": "api", "path": "/api/v1/rbac/permissions"},
    {"code": "permission:create", "name": "创建权限", "type": "api", "path": "/api/v1/rbac/permissions"},
    {"code": "permission:update", "name": "更新权限", "type": "api", "path": "/api/v1/rbac/permissions/{id}"},
    {"code": "permission:delete", "name": "删除权限", "type": "api", "path": "/api/v1/rbac/permissions/{id}"},

    # 安全组件权限
    {"code": "security:list", "name": "查看安全组件", "type": "api", "path": "/api/v1/security/components"},
    {"code": "security:enable", "name": "启用安全组件", "type": "api", "path": "/api/v1/security/components/{id}/enable"},
    {"code": "security:disable", "name": "禁用安全组件", "type": "api", "path": "/api/v1/security/components/{id}/disable"},
    {"code": "security:config", "name": "配置安全组件", "type": "api", "path": "/api/v1/security/components/{id}/config"},

    # SSL证书权限
    {"code": "ssl:list", "name": "查看SSL证书", "type": "api", "path": "/api/v1/ssl/certificates"},
    {"code": "ssl:upload", "name": "上传SSL证书", "type": "api", "path": "/api/v1/ssl/certificates"},
    {"code": "ssl:deploy", "name": "部署SSL证书", "type": "api", "path": "/api/v1/ssl/certificates/{id}/deploy"},
    {"code": "ssl:delete", "name": "删除SSL证书", "type": "api", "path": "/api/v1/ssl/certificates/{id}"},

    # 交易权限
    {"code": "trading:execute", "name": "执行交易", "type": "api", "path": "/api/v1/trading/execute"},
    {"code": "trading:list", "name": "查看交易记录", "type": "api", "path": "/api/v1/trading/list"},

    # 策略权限
    {"code": "strategy:list", "name": "查看策略列表", "type": "api", "path": "/api/v1/strategies"},
    {"code": "strategy:create", "name": "创建策略", "type": "api", "path": "/api/v1/strategies"},
    {"code": "strategy:update", "name": "更新策略", "type": "api", "path": "/api/v1/strategies/{id}"},
    {"code": "strategy:delete", "name": "删除策略", "type": "api", "path": "/api/v1/strategies/{id}"},

    # 菜单权限
    {"code": "menu:dashboard", "name": "仪表盘菜单", "type": "menu", "path": "/dashboard"},
    {"code": "menu:trading", "name": "交易菜单", "type": "menu", "path": "/trading"},
    {"code": "menu:strategies", "name": "策略菜单", "type": "menu", "path": "/strategies"},
    {"code": "menu:positions", "name": "持仓菜单", "type": "menu", "path": "/positions"},
    {"code": "menu:accounts", "name": "账户菜单", "type": "menu", "path": "/accounts"},
    {"code": "menu:system", "name": "系统管理菜单", "type": "menu", "path": "/system"},
    {"code": "menu:rbac", "name": "权限管理菜单", "type": "menu", "path": "/rbac"},
    {"code": "menu:security", "name": "安全组件菜单", "type": "menu", "path": "/security"},
    {"code": "menu:ssl", "name": "SSL证书菜单", "type": "menu", "path": "/ssl"},
]

# 角色权限分配
ROLE_PERMISSIONS = {
    "super_admin": "all",  # 所有权限
    "system_admin": [
        "user:list", "user:detail", "user:create", "user:update", "user:delete",
        "role:list", "role:detail", "role:create", "role:update", "role:delete", "role:assign_permission",
        "permission:list", "permission:create", "permission:update", "permission:delete",
        "menu:system", "menu:rbac",
    ],
    "security_admin": [
        "security:list", "security:enable", "security:disable", "security:config",
        "ssl:list", "ssl:upload", "ssl:deploy", "ssl:delete",
        "menu:security", "menu:ssl",
    ],
    "trader": [
        "trading:execute", "trading:list",
        "strategy:list", "strategy:create", "strategy:update", "strategy:delete",
        "menu:dashboard", "menu:trading", "menu:strategies", "menu:positions", "menu:accounts",
    ],
    "observer": [
        "trading:list", "strategy:list",
        "menu:dashboard", "menu:trading", "menu:strategies", "menu:positions", "menu:accounts",
    ],
}

async def init_rbac():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/postgres')

    try:
        print("Starting RBAC initialization...")

        # 1. 插入权限（如果不存在）
        print("\n1. Creating permissions...")
        permission_ids = {}
        for perm in PERMISSIONS:
            # 检查权限是否存在
            existing = await conn.fetchval(
                "SELECT permission_id FROM permissions WHERE permission_code = $1",
                perm["code"]
            )

            if existing:
                permission_ids[perm["code"]] = existing
                print(f"  - {perm['code']}: already exists")
            else:
                perm_id = uuid.uuid4()
                await conn.execute("""
                    INSERT INTO permissions (permission_id, permission_name, permission_code, resource_type, resource_path, is_active, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, true, $6, $6)
                """, perm_id, perm["name"], perm["code"], perm["type"], perm.get("path"), datetime.utcnow())
                permission_ids[perm["code"]] = perm_id
                print(f"  + {perm['code']}: created")

        # 2. 获取所有角色
        print("\n2. Loading roles...")
        roles = await conn.fetch("SELECT role_id, role_code FROM roles")
        role_map = {r["role_code"]: r["role_id"] for r in roles}
        print(f"  Found {len(roles)} roles")

        # 3. 分配权限给角色
        print("\n3. Assigning permissions to roles...")
        for role_code, perms in ROLE_PERMISSIONS.items():
            if role_code not in role_map:
                print(f"  ! Role {role_code} not found, skipping")
                continue

            role_id = role_map[role_code]

            # 清除现有权限分配
            deleted = await conn.execute(
                "DELETE FROM role_permissions WHERE role_id = $1",
                role_id
            )

            # 分配新权限
            if perms == "all":
                # 超级管理员获得所有权限
                perm_list = list(permission_ids.values())
            else:
                perm_list = [permission_ids[p] for p in perms if p in permission_ids]

            for perm_id in perm_list:
                await conn.execute("""
                    INSERT INTO role_permissions (id, role_id, permission_id, granted_at)
                    VALUES ($1, $2, $3, $4)
                """, uuid.uuid4(), role_id, perm_id, datetime.utcnow())

            print(f"  + {role_code}: assigned {len(perm_list)} permissions")

        print("\nRBAC initialization completed successfully!")

        # 显示统计
        perm_count = await conn.fetchval("SELECT COUNT(*) FROM permissions")
        role_count = await conn.fetchval("SELECT COUNT(*) FROM roles")
        rp_count = await conn.fetchval("SELECT COUNT(*) FROM role_permissions")

        print(f"\nStatistics:")
        print(f"  - Roles: {role_count}")
        print(f"  - Permissions: {perm_count}")
        print(f"  - Role-Permission assignments: {rp_count}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(init_rbac())
