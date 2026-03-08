"""
音频文件管理服务
用于管理飞书音频文件的上传和file_key缓存
"""
import os
import logging
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# 音频文件file_key缓存（文件名 -> file_key）
_audio_file_keys: Dict[str, str] = {}


async def get_audio_file_key(feishu_service, audio_filename: str) -> Optional[str]:
    """
    获取音频文件的飞书file_key，如果未上传则先上传

    Args:
        feishu_service: 飞书服务实例
        audio_filename: 音频文件名（如 "net_asset.mp3"）

    Returns:
        file_key 或 None
    """
    # 检查缓存
    if audio_filename in _audio_file_keys:
        logger.info(f"使用缓存的file_key: {audio_filename}")
        return _audio_file_keys[audio_filename]

    # 查找音频文件路径
    audio_dir = Path("uploads/sounds")
    audio_path = audio_dir / audio_filename

    if not audio_path.exists():
        logger.error(f"音频文件不存在: {audio_path}")
        return None

    # 上传到飞书
    logger.info(f"上传音频文件到飞书: {audio_filename}")
    result = await feishu_service.upload_audio_file(str(audio_path))

    if result.get("success"):
        file_key = result.get("file_key")
        # 缓存file_key
        _audio_file_keys[audio_filename] = file_key
        logger.info(f"音频文件上传成功并缓存: {audio_filename} -> {file_key}")
        return file_key
    else:
        logger.error(f"音频文件上传失败: {result.get('error')}")
        return None


def clear_audio_cache():
    """清除音频file_key缓存"""
    global _audio_file_keys
    _audio_file_keys.clear()
    logger.info("音频file_key缓存已清除")
