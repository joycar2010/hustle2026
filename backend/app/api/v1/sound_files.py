"""Sound files management API"""
import os
import logging
from typing import List
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.services.feishu_service import get_feishu_service
from app.core.security import get_current_user
from app.models.audio_file import AudioFile

logger = logging.getLogger(__name__)

router = APIRouter()

# 声音文件存储目录
# 使用相对于当前工作目录的路径（假设从backend目录运行）
SOUNDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "frontend", "public", "sounds"))


@router.get("/sounds")
async def list_sound_files(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取所有可用的声音文件列表（从数据库）"""
    try:
        # 从数据库查询所有音频文件
        result = await db.execute(select(AudioFile))
        audio_files = result.scalars().all()

        sound_files = []
        for audio_file in audio_files:
            sound_files.append({
                "file_id": str(audio_file.file_id),
                "filename": audio_file.file_name,
                "path": f"/sounds/{audio_file.file_name}",
                "size": int(audio_file.file_size) if audio_file.file_size else 0,
                "file_key": audio_file.file_key,
                "is_synced": audio_file.is_synced,
                "created_at": audio_file.created_at.isoformat() if audio_file.created_at else None,
                "synced_at": audio_file.synced_at.isoformat() if audio_file.synced_at else None
            })

        return {
            "success": True,
            "sounds": sound_files
        }
    except Exception as e:
        logger.error(f"获取声音文件列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sounds/upload")
async def upload_sound_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """上传声音文件并保存到数据库"""
    try:
        # 验证文件类型
        allowed_extensions = ['.mp3', '.wav', '.ogg', '.opus']
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型。允许的类型: {', '.join(allowed_extensions)}"
            )

        # 确保目录存在
        os.makedirs(SOUNDS_DIR, exist_ok=True)

        # 保存文件到本地
        file_path = os.path.join(SOUNDS_DIR, file.filename)
        content = await file.read()
        file_size = len(content)

        with open(file_path, "wb") as f:
            f.write(content)

        logger.info(f"声音文件已保存到本地: {file_path}")

        # 检查数据库中是否已存在同名文件
        result = await db.execute(
            select(AudioFile).where(AudioFile.file_name == file.filename)
        )
        existing_file = result.scalar_one_or_none()

        if existing_file:
            # 更新现有记录
            existing_file.file_path = file_path
            existing_file.file_size = str(file_size)
            existing_file.updated_at = datetime.utcnow()
            audio_file = existing_file
        else:
            # 创建新记录
            audio_file = AudioFile(
                file_name=file.filename,
                file_path=file_path,
                file_size=str(file_size),
                is_synced=False
            )
            db.add(audio_file)

        await db.commit()
        await db.refresh(audio_file)

        return {
            "success": True,
            "message": "文件上传成功",
            "filename": file.filename,
            "path": f"/sounds/{file.filename}",
            "file_id": str(audio_file.file_id)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传声音文件失败: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sounds/{filename}")
async def delete_sound_file(
    filename: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除声音文件"""
    try:
        # 从数据库查询文件
        result = await db.execute(
            select(AudioFile).where(AudioFile.file_name == filename)
        )
        audio_file = result.scalar_one_or_none()

        if not audio_file:
            raise HTTPException(status_code=404, detail="文件不存在")

        # 删除本地文件
        file_path = os.path.join(SOUNDS_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"声音文件已删除: {file_path}")

        # 从数据库删除记录
        await db.delete(audio_file)
        await db.commit()

        return {
            "success": True,
            "message": "文件删除成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除声音文件失败: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sounds/import-existing")
async def import_existing_sounds(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """导入现有的音频文件到数据库"""
    try:
        if not os.path.exists(SOUNDS_DIR):
            return {
                "success": True,
                "message": "音频文件目录不存在",
                "imported": 0
            }

        imported_count = 0
        for filename in os.listdir(SOUNDS_DIR):
            if filename.endswith(('.mp3', '.wav', '.ogg', '.opus')):
                file_path = os.path.join(SOUNDS_DIR, filename)
                file_size = os.path.getsize(file_path)

                # 检查数据库中是否已存在
                result = await db.execute(
                    select(AudioFile).where(AudioFile.file_name == filename)
                )
                existing = result.scalar_one_or_none()

                if not existing:
                    # 创建新记录
                    audio_file = AudioFile(
                        file_name=filename,
                        file_path=file_path,
                        file_size=str(file_size),
                        is_synced=False
                    )
                    db.add(audio_file)
                    imported_count += 1
                    logger.info(f"导入音频文件: {filename}")

        await db.commit()

        return {
            "success": True,
            "message": f"成功导入 {imported_count} 个音频文件",
            "imported": imported_count
        }
    except Exception as e:
        logger.error(f"导入音频文件失败: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sounds/sync-to-feishu")
async def sync_all_sounds_to_feishu(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """将所有本地声音文件同步到飞书云文档"""
    try:
        feishu = get_feishu_service()
        if not feishu:
            raise HTTPException(status_code=400, detail="飞书服务未配置")

        # 从数据库查询所有音频文件
        result = await db.execute(select(AudioFile))
        audio_files = result.scalars().all()

        if not audio_files:
            return {
                "success": True,
                "message": "没有声音文件需要同步，请先导入现有文件",
                "results": []
            }

        results = []
        for audio_file in audio_files:
            try:
                file_path = os.path.join(SOUNDS_DIR, audio_file.file_name)
                if not os.path.exists(file_path):
                    results.append({
                        "filename": audio_file.file_name,
                        "success": False,
                        "error": "本地文件不存在"
                    })
                    continue

                upload_result = await feishu.upload_audio_file(file_path)
                if upload_result.get("success"):
                    file_key = upload_result.get("file_key")
                    # 更新数据库记录
                    audio_file.file_key = file_key
                    audio_file.is_synced = True
                    audio_file.synced_at = datetime.utcnow()
                    audio_file.updated_at = datetime.utcnow()

                    results.append({
                        "filename": audio_file.file_name,
                        "success": True,
                        "file_key": file_key
                    })
                else:
                    results.append({
                        "filename": audio_file.file_name,
                        "success": False,
                        "error": upload_result.get("error")
                    })
            except Exception as e:
                results.append({
                    "filename": audio_file.file_name,
                    "success": False,
                    "error": str(e)
                })

        await db.commit()

        success_count = sum(1 for r in results if r["success"])

        return {
            "success": True,
            "message": f"同步完成: {success_count}/{len(results)} 个文件成功",
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步声音文件到飞书失败: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
