#!/usr/bin/env python3
"""导入现有的音频文件到数据库"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.audio_file import AudioFile


async def import_existing_sounds():
    """导入现有的音频文件到数据库"""
    # 音频文件目录
    sounds_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', '..', 'frontend', 'public', 'sounds'
    ))

    if not os.path.exists(sounds_dir):
        print(f"音频文件目录不存在: {sounds_dir}")
        return

    async with AsyncSessionLocal() as db:
        # 获取所有音频文件
        audio_files = []
        for filename in os.listdir(sounds_dir):
            if filename.endswith(('.mp3', '.wav', '.ogg', '.opus')):
                file_path = os.path.join(sounds_dir, filename)
                file_size = os.path.getsize(file_path)

                # 检查数据库中是否已存在
                result = await db.execute(
                    select(AudioFile).where(AudioFile.file_name == filename)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    print(f"文件已存在: {filename}")
                    continue

                # 创建新记录
                audio_file = AudioFile(
                    file_name=filename,
                    file_path=file_path,
                    file_size=str(file_size),
                    is_synced=False
                )
                db.add(audio_file)
                audio_files.append(filename)
                print(f"导入文件: {filename} ({file_size} bytes)")

        await db.commit()
        print(f"\n成功导入 {len(audio_files)} 个音频文件")


if __name__ == "__main__":
    asyncio.run(import_existing_sounds())
