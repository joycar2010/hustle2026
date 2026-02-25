"""
模型与数据库类型一致性验证工具

用于验证 SQLAlchemy 模型定义与 PostgreSQL 数据库实际结构是否匹配
"""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.strategy_performance import StrategyPerformance
from app.models.strategy import StrategyConfig
import logging

logger = logging.getLogger(__name__)


async def validate_strategy_performance_model(db: AsyncSession) -> dict:
    """
    验证 StrategyPerformance 模型的字段类型与数据库是否一致

    Returns:
        dict: 验证结果，包含 is_valid, issues, details
    """
    result = {
        "is_valid": True,
        "issues": [],
        "details": {}
    }

    try:
        # 1. 检查模型定义
        mapper = inspect(StrategyPerformance)
        strategy_id_column = mapper.columns['strategy_id']

        model_type = str(strategy_id_column.type)
        model_fk = list(strategy_id_column.foreign_keys)[0] if strategy_id_column.foreign_keys else None

        result["details"]["model"] = {
            "column": "strategy_id",
            "type": model_type,
            "foreign_key": str(model_fk.target_fullname) if model_fk else None,
            "nullable": strategy_id_column.nullable
        }

        # 2. 检查数据库实际结构
        query = text("""
            SELECT
                column_name,
                data_type,
                udt_name,
                is_nullable
            FROM information_schema.columns
            WHERE table_name = 'strategy_performance'
            AND column_name = 'strategy_id'
        """)

        db_result = await db.execute(query)
        db_row = db_result.fetchone()

        if db_row:
            result["details"]["database"] = {
                "column": db_row[0],
                "data_type": db_row[1],
                "udt_name": db_row[2],
                "is_nullable": db_row[3]
            }

            # 3. 类型匹配验证
            db_type = db_row[2]  # udt_name (uuid, int4, etc.)

            # UUID 类型匹配
            if db_type == 'uuid' and 'UUID' not in model_type:
                result["is_valid"] = False
                result["issues"].append(
                    f"类型不匹配: 数据库为 UUID，模型为 {model_type}"
                )

            # Integer 类型匹配
            if db_type in ('int4', 'integer') and 'INTEGER' not in model_type.upper():
                result["is_valid"] = False
                result["issues"].append(
                    f"类型不匹配: 数据库为 INTEGER，模型为 {model_type}"
                )
        else:
            result["is_valid"] = False
            result["issues"].append("数据库中未找到 strategy_performance.strategy_id 列")

        # 4. 检查外键约束
        fk_query = text("""
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.table_name = 'strategy_performance'
            AND tc.constraint_type = 'FOREIGN KEY'
            AND kcu.column_name = 'strategy_id'
        """)

        fk_result = await db.execute(fk_query)
        fk_row = fk_result.fetchone()

        if fk_row:
            result["details"]["database_fk"] = {
                "constraint_name": fk_row[0],
                "column": fk_row[1],
                "references_table": fk_row[2],
                "references_column": fk_row[3]
            }

            # 验证外键目标
            expected_fk = "strategy_configs.config_id"
            actual_fk = f"{fk_row[2]}.{fk_row[3]}"

            if actual_fk != expected_fk:
                result["is_valid"] = False
                result["issues"].append(
                    f"外键不匹配: 期望 {expected_fk}，实际 {actual_fk}"
                )

        logger.info(f"模型验证结果: {result}")
        return result

    except Exception as e:
        logger.error(f"模型验证失败: {e}", exc_info=True)
        result["is_valid"] = False
        result["issues"].append(f"验证过程出错: {str(e)}")
        return result


async def validate_all_models(db: AsyncSession) -> dict:
    """
    验证所有关键模型的一致性

    Returns:
        dict: 所有模型的验证结果
    """
    results = {}

    # 验证 StrategyPerformance
    results["strategy_performance"] = await validate_strategy_performance_model(db)

    # 可以添加更多模型验证...

    return results


# CLI 使用示例
if __name__ == "__main__":
    import asyncio
    from app.core.database import async_session_maker

    async def main():
        async with async_session_maker() as session:
            result = await validate_strategy_performance_model(session)

            print("\n" + "="*60)
            print("模型验证结果")
            print("="*60)
            print(f"\n状态: {'✓ 通过' if result['is_valid'] else '✗ 失败'}")

            if result['issues']:
                print("\n问题列表:")
                for issue in result['issues']:
                    print(f"  - {issue}")

            print("\n详细信息:")
            print(f"  模型定义: {result['details'].get('model')}")
            print(f"  数据库结构: {result['details'].get('database')}")
            print(f"  数据库外键: {result['details'].get('database_fk')}")
            print("="*60 + "\n")

    asyncio.run(main())
