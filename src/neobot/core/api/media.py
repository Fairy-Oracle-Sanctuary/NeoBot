"""
媒体API模块

封装了与图片、语音等媒体文件相关的API。
"""
from typing import Dict, Any

from .base import BaseAPI


class MediaAPI(BaseAPI):
    """
    媒体相关API
    """

    async def can_send_image(self) -> Dict[str, Any]:
        """
        检查是否可以发送图片

        :return: OneBot v11标准响应
        """
        return await self.call_api(action="can_send_image")

    async def can_send_record(self) -> Dict[str, Any]:
        """
        检查是否可以发送语音

        :return: OneBot v11标准响应
        """
        return await self.call_api(action="can_send_record")

    async def get_image(self, file: str) -> Dict[str, Any]:
        """
        获取图片信息

        :param file: 图片文件名或路径
        :return: OneBot v11标准响应
        """
        return await self.call_api(action="get_image", params={"file": file})

    async def get_file(self, file_id: str) -> Dict[str, Any]:
        """
        获取文件信息

        :param file_id: 文件ID
        :return: OneBot v11标准响应
        """
        return await self.call_api(action="get_file", params={"file_id": file_id})

