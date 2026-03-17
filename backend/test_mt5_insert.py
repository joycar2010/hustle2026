import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models.mt5_client import MT5Client
from app.models.account import Account

DATABASE_URL = "postgresql+asyncpg://postgres:Aq987456!@localhost:5432/hustle"

async def test_insert():
    engine = create_async_engine(DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create MT5 client
        client = MT5Client(
            account_id=uuid.UUID("1ce0146d-b2cb-467d-8b34-ff951e696563"),
            client_name="Test Client 1",
            mt5_path="C:\\Program Files\\MetaTrader 5\\terminal64.exe",
            mt5_login="3971962",
            mt5_password="Aq987456!",
            mt5_server="Bybit-Live-2",
            password_type="primary",
            priority=1,
            created_by=uuid.UUID("0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24")
        )

        session.add(client)
        await session.commit()
        await session.refresh(client)

        print(f"Created client: {client.client_id}")
        return client

if __name__ == "__main__":
    asyncio.run(test_insert())
