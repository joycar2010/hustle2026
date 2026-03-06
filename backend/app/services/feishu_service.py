"""Feishu (Lark) notification service"""
import aiohttp
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def get_beijing_time():
    """Get current time in Beijing timezone (UTC+8) as naive datetime"""
    beijing_tz = ZoneInfo("Asia/Shanghai")
    beijing_time = datetime.now(beijing_tz)
    return beijing_time.replace(tzinfo=None)


class FeishuService:
    """
    飞书机器人通知服务

    使用生鲜商品配送语规避敏感词汇
    """

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.tenant_access_token = None
        self.token_expires_at = None
        self.base_url = "https://open.feishu.cn/open-apis"

    async def get_tenant_access_token(self) -> str:
        """获取tenant_access_token"""
        # 如果token未过期，直接返回
        if self.tenant_access_token and self.token_expires_at:
            if get_beijing_time() < self.token_expires_at:
                return self.tenant_access_token

        # 获取新token
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                data = await response.json()

                if data.get("code") != 0:
                    raise Exception(f"获取飞书token失败: {data.get('msg')}")

                self.tenant_access_token = data["tenant_access_token"]
                # token有效期2小时，提前5分钟刷新
                expires_in = data.get("expire", 7200) - 300
                self.token_expires_at = get_beijing_time() + timedelta(seconds=expires_in)

                logger.info("飞书token获取成功")
                return self.tenant_access_token

    async def send_text_message(
        self,
        receive_id: str,
        content: str,
        receive_id_type: str = "open_id"
    ) -> Dict[str, Any]:
        """
        发送文本消息

        Args:
            receive_id: 接收者ID（open_id, user_id, union_id, email, chat_id）
            content: 消息内容
            receive_id_type: ID类型
        """
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}/im/v1/messages"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        params = {
            "receive_id_type": receive_id_type
        }

        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": content})
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, params=params, json=payload) as response:
                data = await response.json()

                if data.get("code") != 0:
                    logger.error(f"飞书消息发送失败: {data.get('msg')}")
                    return {"success": False, "error": data.get("msg")}

                logger.info(f"飞书消息发送成功: {receive_id}")
                return {"success": True, "message_id": data.get("data", {}).get("message_id")}

    async def send_card_message(
        self,
        receive_id: str,
        title: str,
        content: str,
        receive_id_type: str = "open_id",
        color: str = "blue"  # blue, green, orange, red
    ) -> Dict[str, Any]:
        """
        发送卡片消息（更美观）

        Args:
            receive_id: 接收者ID
            title: 卡片标题
            content: 卡片内容
            receive_id_type: ID类型
            color: 卡片颜色
        """
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}/im/v1/messages"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        params = {
            "receive_id_type": receive_id_type
        }

        # 构造卡片内容
        card_content = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content
                    }
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"发送时间: {get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')} (北京时间)"
                        }
                    ]
                }
            ]
        }

        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card_content)
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, params=params, json=payload) as response:
                data = await response.json()

                if data.get("code") != 0:
                    logger.error(f"飞书卡片消息发送失败: {data.get('msg')}")
                    return {"success": False, "error": data.get("msg")}

                logger.info(f"飞书卡片消息发送成功: {receive_id}")
                return {"success": True, "message_id": data.get("data", {}).get("message_id")}

    async def send_batch_message(
        self,
        receive_ids: List[str],
        content: str,
        receive_id_type: str = "open_id"
    ) -> Dict[str, Any]:
        """批量发送消息"""
        results = []
        for receive_id in receive_ids:
            result = await self.send_text_message(receive_id, content, receive_id_type)
            results.append({
                "receive_id": receive_id,
                "success": result.get("success", False),
                "error": result.get("error")
            })

        success_count = sum(1 for r in results if r["success"])
        return {
            "success": success_count > 0,
            "total": len(receive_ids),
            "success_count": success_count,
            "failed_count": len(receive_ids) - success_count,
            "results": results
        }

    async def get_user_info(self, user_id: str, user_id_type: str = "open_id") -> Dict[str, Any]:
        """获取用户信息"""
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}/contact/v3/users/{user_id}"

        headers = {
            "Authorization": f"Bearer {token}"
        }

        params = {
            "user_id_type": user_id_type
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                data = await response.json()

                if data.get("code") != 0:
                    logger.error(f"获取飞书用户信息失败: {data.get('msg')}")
                    return {"success": False, "error": data.get("msg")}

                return {"success": True, "user": data.get("data", {}).get("user")}

    async def get_user_by_mobile(self, mobile: str) -> Dict[str, Any]:
        """通过手机号获取用户信息"""
        token = await self.get_tenant_access_token()

        # 先通过手机号获取 user_id
        url = f"{self.base_url}/contact/v3/users/batch_get_id"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        params = {
            "user_id_type": "open_id"
        }

        payload = {
            "mobiles": [mobile]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, params=params, json=payload) as response:
                data = await response.json()

                if data.get("code") != 0:
                    logger.error(f"通过手机号获取用户ID失败: {data.get('msg')}")
                    return {"success": False, "error": data.get("msg")}

                user_list = data.get("data", {}).get("user_list", [])
                if not user_list:
                    logger.warning(f"未找到手机号对应的用户: {mobile}")
                    return {"success": False, "error": "未找到用户"}

                user_id = user_list[0].get("user_id")

                # 获取用户详细信息
                return await self.get_user_info(user_id, "open_id")

    async def upload_audio_file(self, audio_file_path: str) -> Dict[str, Any]:
        """
        上传音频文件到飞书

        Args:
            audio_file_path: 音频文件路径

        Returns:
            包含file_key的字典
        """
        import os

        token = await self.get_tenant_access_token()

        # 读取文件
        if not os.path.exists(audio_file_path):
            logger.error(f"音频文件不存在: {audio_file_path}")
            return {"success": False, "error": "文件不存在"}

        file_name = os.path.basename(audio_file_path)

        # 准备上传
        upload_url = f"{self.base_url}/im/v1/files"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        form_data = aiohttp.FormData()
        form_data.add_field("file_type", "opus")  # 音频类型
        form_data.add_field("file_name", file_name)

        # 读取文件内容
        with open(audio_file_path, 'rb') as f:
            file_content = f.read()
            form_data.add_field("file", file_content, filename=file_name)

        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url, headers=headers, data=form_data) as response:
                data = await response.json()

                if data.get("code") != 0:
                    logger.error(f"飞书音频文件上传失败: {data.get('msg')}")
                    return {"success": False, "error": data.get("msg")}

                file_key = data.get("data", {}).get("file_key")
                logger.info(f"飞书音频文件上传成功: {file_key}")
                return {"success": True, "file_key": file_key}

    async def send_audio_message(
        self,
        receive_id: str,
        file_key: str,
        receive_id_type: str = "open_id"
    ) -> Dict[str, Any]:
        """
        发送音频消息

        Args:
            receive_id: 接收者ID
            file_key: 音频文件的file_key
            receive_id_type: ID类型
        """
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}/im/v1/messages"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        params = {
            "receive_id_type": receive_id_type
        }

        payload = {
            "receive_id": receive_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key})
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, params=params, json=payload) as response:
                data = await response.json()

                if data.get("code") != 0:
                    logger.error(f"飞书音频消息发送失败: {data.get('msg')}")
                    return {"success": False, "error": data.get("msg")}

                logger.info(f"飞书音频消息发送成功: {receive_id}")
                return {"success": True, "message_id": data.get("data", {}).get("message_id")}


# 全局飞书服务实例
feishu_service: Optional[FeishuService] = None


def init_feishu_service(app_id: str, app_secret: str):
    """初始化飞书服务"""
    global feishu_service
    feishu_service = FeishuService(app_id, app_secret)
    logger.info("飞书服务初始化成功")


def get_feishu_service() -> Optional[FeishuService]:
    """获取飞书服务实例"""
    return feishu_service
