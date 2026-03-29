import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/postgres')

    print("=== Roles ===")
    roles = await conn.fetch("SELECT role_id, role_name, role_code, is_system, is_active FROM roles ORDER BY role_name")
    for r in roles:
        print(f"{r['role_code']} - System: {r['is_system']}, Active: {r['is_active']}")
    print(f"Total roles: {len(roles)}\n")

    print("=== Permissions ===")
    perms = await conn.fetch("SELECT permission_id, permission_name, permission_code, resource_type FROM permissions ORDER BY permission_name LIMIT 20")
    for p in perms:
        print(f"{p['permission_code']} - Type: {p['resource_type']}")

    perm_count = await conn.fetchval("SELECT COUNT(*) FROM permissions")
    print(f"Total permissions: {perm_count}\n")

    print("=== Role-Permission Assignments ===")
    rp_count = await conn.fetchval("SELECT COUNT(*) FROM role_permissions")
    print(f"Total role-permission assignments: {rp_count}")

    await conn.close()

asyncio.run(main())
