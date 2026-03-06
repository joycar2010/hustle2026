"""Sound files management API"""
import os
import logging
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.feishu_service import get_feishu_service
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# 声音文件存储目录
SOUNDS_DIR = os.path.join("frontend", "public", "sounds")


@router.get("/sounds")
async def list_sound_files(
    current_user: dict = Depends(get_current_user)
):
    """获取所有可用的声音文件列表"""
    try:
        # 确保目录存在
        os.makedirs(SOUNDS_DIR, exist_ok=True)

        # 获取所有音频文件
        sound_files = []
        if os.path.exists(SOUNDS_DIR):
            for filename in os.listdir(SOUNDS_DIR):
                if filename.endswith(('.mp3', '.wav', '.ogg', '.opus')):
                    file_path = os.path.join(SOUNDS_DIR, filename)
                    file_size = os.path.getsize(file_path)
                    sound_files.append({
                        "filename": filename,
                        "path": f"/sounds/{filename}",
                        "size": file_size
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
    current_user: dict = Depends(get_current_user)
):
    """上传声音文件并同步到飞书云文档"""
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
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        logger.info(f"声音文件已保存到本地: {file_path}")

        # 上传到飞书云文档
        feishu = get_feishu_service()
        if feishu:
            try:
                upload_result = await feishu.upload_audio_file(file_path)
                if upload_result.get("success"):
                    file_key = upload_result.get("file_key")
                    logger.info(f"声音文件已上传到飞书: {file_key}")

                    return {
                        "success": True,
                        "message": "文件上传成功并已同步到飞书云文档",
                        "filename": file.filename,
                        "path": f"/sounds/{file.filename}",
                        "feishu_file_key": file_key
                    }
                else:
                    logger.warning(f"上传到飞书失败: {upload_result.get('error')}")
                    return {
                        "success": True,
                        "message": "文件已保存到本地，但上传到飞书失败",
                        "filename": file.filename,
                        "path": f"/sounds/{file.filename}",
                        "feishu_error": upload_result.get("error")
                    }
            except Exception as e:
                logger.error(f"上传到飞书时出错: {e}", exc_info=True)
                return {
                    "success": True,
                    "message": "文件已保存到本地，但上传到飞书时出错",
                    "filename": file.filename,
                    "path": f"/sounds/{file.filename}",
                    "feishu_error": str(e)
                }
        else:
            logger.warning("飞书服务未初始化")
            return {
                "success": True,
                "message": "文件已保存到本地（飞书服务未配置）",
                "filename": file.filename,
                "path": f"/sounds/{file.filename}"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传声音文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sounds/{filename}")
async def delete_sound_file(
    filename: str,
    current_user: dict = Depends(get_current_user)
):
    """删除声音文件"""
    try:
        file_path = os.path.join(SOUNDS_DIR, filename)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        # 删除本地文件
        os.remove(file_path)
        logger.info(f"声音文件已删除: {file_path}")

        return {
            "success": True,
            "message": "文件删除成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除声音文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sounds/sync-to-feishu")
async def sync_all_sounds_to_feishu(
    current_user: dict = Depends(get_current_user)
):
    """将所有本地声音文件同步到飞书云文档"""
    try:
        feishu = get_feishu_service()
        if not feishu:
            raise HTTPException(status_code=400, detail="飞书服务未配置")

        # 确保目录存在
        if not os.path.exists(SOUNDS_DIR):
            return {
                "success": True,
                "message": "没有声音文件需要同步",
                "results": []
            }

        results = []
        for filename in os.listdir(SOUNDS_DIR):
            if filename.endswith(('.mp3', '.wav', '.ogg', '.opus')):
                file_path = os.path.join(SOUNDS_DIR, filename)
                try:
                    upload_result = await feishu.upload_audio_file(file_path)
                    results.append({
                        "filename": filename,
                        "success": upload_result.get("success"),
                        "file_key": upload_result.get("file_key"),
                        "error": upload_result.get("error")
                    })
                except Exception as e:
                    results.append({
                        "filename": filename,
                        "success": False,
                        "error": str(e)
                    })

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
        raise HTTPException(status_code=500, detail=str(e))
