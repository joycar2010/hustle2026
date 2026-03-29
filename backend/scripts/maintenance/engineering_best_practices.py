"""
删除用户功能的工程化最佳实践

项目：Python + SQLAlchemy 2.0 + PostgreSQL + FastAPI
"""

# ============================================
# 1. 模块导入规范
# ============================================

"""
问题：ModuleNotFoundError: No module named 'app.models.trade'

根因：
- trade.py 文件不存在于 app/models/ 目录
- 代码中存在对不存在模块的导入

解决方案：
1. 使用条件导入处理可选模块
2. 在 __init__.py 中统一管理模块导出
3. 使用 importlib 动态检查模块是否存在
"""

# 示例：安全的模块导入
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 仅用于类型检查，不会在运行时导入
    from app.models.trade import Trade

# 运行时条件导入
def safe_import_model(model_name: str):
    """安全导入模型，不存在时返回 None"""
    try:
        module = __import__(f'app.models.{model_name}', fromlist=[model_name.capitalize()])
        return getattr(module, model_name.capitalize())
    except (ImportError, AttributeError):
        return None

# 使用示例
Trade = safe_import_model('trade')
if Trade:
    # 使用 Trade 模型
    pass

# ============================================
# 2. 数据库类型校验工具
# ============================================

"""
问题：SQLAlchemy 模型定义与数据库实际类型不一致

解决方案：自动化类型校验工具
"""

import asyncpg
from sqlalchemy import inspect
from typing import Dict, List, Tuple

async def validate_model_schema(
    model_class,
    db_url: str
) -> Dict[str, List[str]]:
    """
    验证 SQLAlchemy 模型与数据库结构的一致性

    Args:
        model_class: SQLAlchemy 模型类
        db_url: 数据库连接 URL

    Returns:
        包含不一致项的字典
    """
    issues = {
        "type_mismatch": [],
        "missing_columns": [],
        "extra_columns": [],
        "fk_mismatch": []
    }

    # 获取模型定义
    mapper = inspect(model_class)
    table_name = mapper.tables[0].name
    model_columns = {col.name: col for col in mapper.columns}

    # 连接数据库
    conn = await asyncpg.connect(db_url)

    try:
        # 获取数据库列信息
        db_columns = await conn.fetch("""
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_name = $1
        """, table_name)

        db_col_dict = {row['column_name']: row for row in db_columns}

        # 比较列类型
        for col_name, col in model_columns.items():
            if col_name not in db_col_dict:
                issues["missing_columns"].append(
                    f"列 {col_name} 在数据库中不存在"
                )
                continue

            db_col = db_col_dict[col_name]
            model_type = str(col.type).upper()
            db_type = db_col['udt_name'].upper()

            # 类型映射检查
            type_mapping = {
                'UUID': 'UUID',
                'INTEGER': 'INT4',
                'VARCHAR': 'VARCHAR',
                'TIMESTAMP': 'TIMESTAMP',
                'BOOLEAN': 'BOOL'
            }

            expected_db_type = type_mapping.get(model_type.split('(')[0], None)
            if expected_db_type and expected_db_type != db_type:
                issues["type_mismatch"].append(
                    f"列 {col_name}: 模型类型 {model_type}, 数据库类型 {db_type}"
                )

        # 检查数据库中多余的列
        for db_col_name in db_col_dict:
            if db_col_name not in model_columns:
                issues["extra_columns"].append(
                    f"列 {db_col_name} 在模型中不存在"
                )

        # 检查外键约束
        fk_rows = await conn.fetch("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.table_name = $1
            AND tc.constraint_type = 'FOREIGN KEY'
        """, table_name)

        for fk_row in fk_rows:
            col_name = fk_row['column_name']
            if col_name in model_columns:
                col = model_columns[col_name]
                if col.foreign_keys:
                    fk = list(col.foreign_keys)[0]
                    expected_target = str(fk.target_fullname)
                    actual_target = f"{fk_row['foreign_table_name']}.{fk_row['foreign_column_name']}"

                    if expected_target != actual_target:
                        issues["fk_mismatch"].append(
                            f"列 {col_name}: 模型外键 {expected_target}, 数据库外键 {actual_target}"
                        )

    finally:
        await conn.close()

    return issues

# 使用示例
"""
from app.models.strategy_performance import StrategyPerformance

issues = await validate_model_schema(
    StrategyPerformance,
    "postgresql://postgres:postgres@localhost:5432/postgres"
)

if any(issues.values()):
    print("发现模型与数据库不一致:")
    for category, problems in issues.items():
        if problems:
            print(f"\n{category}:")
            for problem in problems:
                print(f"  - {problem}")
"""

# ============================================
# 3. 删除操作的幂等性设计
# ============================================

"""
问题：重复删除请求可能导致错误或不一致状态

解决方案：幂等性删除设计
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from uuid import UUID
from typing import Optional

async def idempotent_delete_user(
    user_id: UUID,
    db: AsyncSession
) -> dict:
    """
    幂等性删除用户

    Returns:
        {
            "deleted": bool,  # 是否执行了删除
            "existed": bool,  # 用户是否存在过
            "message": str
        }
    """
    # 检查用户是否存在
    result = await db.execute(
        select(User).where(User.user_id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        # 用户不存在，可能已被删除
        return {
            "deleted": False,
            "existed": False,
            "message": "用户不存在或已被删除"
        }

    # 执行删除逻辑
    # ... (删除关联数据)

    await db.delete(user)
    await db.commit()

    return {
        "deleted": True,
        "existed": True,
        "message": "用户删除成功"
    }

# ============================================
# 4. 批量删除性能优化
# ============================================

"""
问题：逐条删除关联数据性能差

解决方案：批量删除 + 事务优化
"""

async def batch_delete_users(
    user_ids: List[UUID],
    db: AsyncSession,
    batch_size: int = 100
) -> dict:
    """
    批量删除用户（带性能优化）

    Args:
        user_ids: 要删除的用户 ID 列表
        db: 数据库会话
        batch_size: 每批处理的数量

    Returns:
        删除结果统计
    """
    from app.models.strategy import Strategy
    from app.models.strategy_performance import StrategyPerformance

    deleted_count = 0
    failed_count = 0
    errors = []

    # 分批处理
    for i in range(0, len(user_ids), batch_size):
        batch = user_ids[i:i + batch_size]

        try:
            # 1. 批量获取策略 ID
            strategies_result = await db.execute(
                select(Strategy.id).where(Strategy.user_id.in_(batch))
            )
            strategy_ids = [row[0] for row in strategies_result.all()]

            # 2. 批量删除策略性能记录
            if strategy_ids:
                await db.execute(
                    delete(StrategyPerformance).where(
                        StrategyPerformance.strategy_id.in_(strategy_ids)
                    )
                )

            # 3. 批量删除用户（级联删除其他关联数据）
            await db.execute(
                delete(User).where(User.user_id.in_(batch))
            )

            await db.commit()
            deleted_count += len(batch)

        except Exception as e:
            await db.rollback()
            failed_count += len(batch)
            errors.append({
                "batch": batch,
                "error": str(e)
            })

    return {
        "deleted": deleted_count,
        "failed": failed_count,
        "errors": errors
    }

# ============================================
# 5. 生产环境注意事项
# ============================================

"""
1. 数据备份
   - 删除前自动备份用户数据
   - 保留删除日志用于审计

2. 软删除 vs 硬删除
   - 考虑使用软删除（is_deleted 标志）
   - 定期清理软删除数据

3. 事务隔离级别
   - 使用 READ COMMITTED 或更高级别
   - 避免删除过程中的脏读

4. 删除权限控制
   - 多重权限验证
   - 操作日志记录
   - 敏感操作需要二次确认

5. 性能监控
   - 监控删除操作耗时
   - 设置超时限制
   - 大批量删除使用后台任务
"""

# 软删除示例
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    username = Column(String(50), nullable=False)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(TIMESTAMP, nullable=True)
    deleted_by = Column(UUID(as_uuid=True), nullable=True)

async def soft_delete_user(
    user_id: UUID,
    deleted_by: UUID,
    db: AsyncSession
):
    """软删除用户"""
    result = await db.execute(
        select(User).where(
            User.user_id == user_id,
            User.is_deleted == False
        )
    )
    user = result.scalar_one_or_none()

    if user:
        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        user.deleted_by = deleted_by
        await db.commit()

# ============================================
# 6. 单元测试示例
# ============================================

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_delete_user_success(
    async_client: AsyncClient,
    admin_token: str,
    test_user_id: UUID
):
    """测试成功删除用户"""
    response = await async_client.delete(
        f"/api/v1/users/{test_user_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )

    assert response.status_code == 204

    # 验证用户已被删除
    get_response = await async_client.get(
        f"/api/v1/users/{test_user_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert get_response.status_code == 404

@pytest.mark.asyncio
async def test_delete_user_cascade(
    async_client: AsyncClient,
    admin_token: str,
    test_user_with_data: dict
):
    """测试级联删除关联数据"""
    user_id = test_user_with_data["user_id"]
    strategy_id = test_user_with_data["strategy_id"]

    # 删除用户
    response = await async_client.delete(
        f"/api/v1/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )

    assert response.status_code == 204

    # 验证关联数据也被删除
    # (需要直接查询数据库或提供查询 API)

print("工程化最佳实践文档已生成")
