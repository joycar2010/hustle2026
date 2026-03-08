#!/usr/bin/env python3
"""创建audio_files表"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from app.core.database import AsyncSessionLocal


async def create_audio_files_table():
    """创建音频文件表"""
    sql = """
    CREATE TABLE IF NOT EXISTS audio_files (
        file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        file_name VARCHAR(255) NOT NULL UNIQUE,
        file_path VARCHAR(500) NOT NULL,
        file_key VARCHAR(255),
        file_size VARCHAR(50),
        is_synced BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        synced_at TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_audio_files_file_name ON audio_files(file_name);
    CREATE INDEX IF NOT EXISTS idx_audio_files_is_synced ON audio_files(is_synced);
    """

    async with AsyncSessionLocal() as db:
        await db.execute(text(sql))
        await db.commit()
        print("音频文件表创建成功")


if __name__ == "__main__":
    asyncio.run(create_audio_files_table())
