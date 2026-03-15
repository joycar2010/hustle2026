"""
清除数据库中的行情记录和点差记录，并压缩数据库
"""
import sys
import os
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text
from app.core.config import settings
from app.core.database import Base
from app.models.market_data import MarketData, SpreadRecord


def cleanup_and_vacuum():
    """清除所有行情和点差记录，并压缩数据库"""
    engine = create_engine(settings.DATABASE_URL)

    try:
        with engine.connect() as conn:
            # 开始事务
            trans = conn.begin()

            try:
                # 清除所有行情记录
                result1 = conn.execute(text("DELETE FROM market_data"))
                print(f"✅ 已删除 {result1.rowcount} 条行情记录")

                # 清除所有点差记录
                result2 = conn.execute(text("DELETE FROM spread_records"))
                print(f"✅ 已删除 {result2.rowcount} 条点差记录")

                # 提交事务
                trans.commit()
                print("✅ 事务已提交")

            except Exception as e:
                trans.rollback()
                print(f"❌ 删除失败，已回滚: {e}")
                raise

        # 压缩数据库（VACUUM需要在事务外执行）
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            print("🔄 开始压缩数据库...")
            conn.execute(text("VACUUM FULL market_data"))
            print("✅ market_data 表已压缩")

            conn.execute(text("VACUUM FULL spread_records"))
            print("✅ spread_records 表已压缩")

            # 分析表以更新统计信息
            conn.execute(text("ANALYZE market_data"))
            conn.execute(text("ANALYZE spread_records"))
            print("✅ 表统计信息已更新")

        print("\n✅ 数据库清理和压缩完成！")

    except Exception as e:
        print(f"\n❌ 操作失败: {e}")
        sys.exit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    print("=" * 60)
    print("数据库清理工具")
    print("=" * 60)
    print(f"数据库: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'Unknown'}")
    print("=" * 60)

    # 确认操作
    confirm = input("\n⚠️  警告：此操作将删除所有行情和点差记录！\n是否继续？(yes/no): ")

    if confirm.lower() == "yes":
        cleanup_and_vacuum()
    else:
        print("❌ 操作已取消")
