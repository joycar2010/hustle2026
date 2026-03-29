import asyncio
import sys

# 添加项目路径
sys.path.insert(0, 'C:\app\hustle2026\backend')

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.risk_settings import RiskSettings
from app.models.user import User

async def check_users():
    # 使用异步驱动
    DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        # 查询用户信息
        result = await db.execute(
            select(User).where(User.username.in_(['cq987', 'admin']))
        )
        users = result.scalars().all()
        
        print('=== 用户信息 ===')
        for user in users:
            print(f'用户名: {user.username}, user_id: {user.user_id}')
        
        print('\n=== 风险设置 ===')
        # 查询风险设置
        for user in users:
            result = await db.execute(
                select(RiskSettings).where(RiskSettings.user_id == user.user_id)
            )
            risk_settings = result.scalar_one_or_none()
            
            if risk_settings:
                print(f'\n用户: {user.username}')
                print(f'  正向开仓阈值 (forward_open_price): {risk_settings.forward_open_price}')
                print(f'  正向平仓阈值 (forward_close_price): {risk_settings.forward_close_price}')
                print(f'  反向开仓阈值 (reverse_open_price): {risk_settings.reverse_open_price}')
                print(f'  反向平仓阈值 (reverse_close_price): {risk_settings.reverse_close_price}')
            else:
                print(f'\n用户: {user.username} - 没有风险设置记录')
    
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(check_users())
