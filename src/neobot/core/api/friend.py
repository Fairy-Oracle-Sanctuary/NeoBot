"""
好友与陌生人相关 API 模块

该模块定义了 `FriendAPI` Mixin 类，提供了所有与好友、陌生人信息
等相关的 OneBot v11 API 封装。
"""
import orjson
from typing import List, Dict, Any
from .base import BaseAPI
from neobot.models.objects import FriendInfo, StrangerInfo
from ..managers.redis_manager import redis_manager


class FriendAPI(BaseAPI):
    """
    `FriendAPI` Mixin 类，提供了所有与好友、陌生人操作相关的 API 方法。
    """

    async def send_like(self, user_id: int, times: int = 1) -> Dict[str, Any]:
        """
        向指定用户发送 "戳一戳" (点赞)。

        Args:
            user_id (int): 目标用户的 QQ 号。
            times (int, optional): 点赞次数，建议不超过 10 次。Defaults to 1.

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("send_like", {"user_id": user_id, "times": times})

    async def get_stranger_info(self, user_id: int, no_cache: bool = False) -> StrangerInfo:
        """
        获取陌生人的信息。

        Args:
            user_id (int): 目标用户的 QQ 号。
            no_cache (bool, optional): 是否不使用缓存，直接从服务器获取。Defaults to False.

        Returns:
            StrangerInfo: 包含陌生人信息的 `StrangerInfo` 数据对象。
        """
        cache_key = f"neobot:cache:get_stranger_info:{user_id}"
        if not no_cache:
            cached_data = await redis_manager.redis.get(cache_key)
            if cached_data:
                return StrangerInfo(**orjson.loads(cached_data))

        res = await self.call_api("get_stranger_info", {"user_id": user_id, "no_cache": no_cache})
        await redis_manager.redis.set(cache_key, orjson.dumps(res), ex=3600)  # 缓存 1 小时
        return StrangerInfo(**res)

    async def get_friend_list(self, no_cache: bool = False) -> List[FriendInfo]:
        """
        获取机器人账号的好友列表。

        Args:
            no_cache (bool, optional): 是否不使用缓存，直接从服务器获取最新信息。Defaults to False.

        Returns:
            List[FriendInfo]: 包含所有好友信息的 `FriendInfo` 对象列表。
        """
        cache_key = f"neobot:cache:get_friend_list:{self.self_id}"
        if not no_cache:
            cached_data = await redis_manager.redis.get(cache_key)
            if cached_data:
                return [FriendInfo(**item) for item in orjson.loads(cached_data)]

        res = await self.call_api("get_friend_list")
        await redis_manager.redis.set(cache_key, orjson.dumps(res), ex=3600)  # 缓存 1 小时
        return [FriendInfo(**item) for item in res]

    async def set_friend_add_request(self, flag: str, approve: bool = True, remark: str = "") -> Dict[str, Any]:
        """
        处理收到的加好友请求。

        Args:
            flag (str): 请求的标识，需要从 `request` 事件中获取。
            approve (bool, optional): 是否同意该好友请求。Defaults to True.
            remark (str, optional): 在同意请求时，为该好友设置的备注。Defaults to "".

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("set_friend_add_request", {"flag": flag, "approve": approve, "remark": remark})

    async def get_friends_with_category(self) -> Dict[str, Any]:
        """
        获取带分类的好友列表。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("get_friends_with_category")

    async def get_unidirectional_friend_list(self) -> Dict[str, Any]:
        """
        获取单向好友列表。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("get_unidirectional_friend_list")

    async def friend_poke(self, user_id: int) -> Dict[str, Any]:
        """
        发送好友戳一戳。

        Args:
            user_id (int): 目标用户的 QQ 号。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("friend_poke", {"user_id": user_id})

    async def mark_private_msg_as_read(self, user_id: int, time: int = 0) -> Dict[str, Any]:
        """
        标记私聊消息为已读。

        Args:
            user_id (int): 目标用户的 QQ 号。
            time (int, optional): 标记此时间戳之前的消息为已读。Defaults to 0 (全部标记)。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        params = {"user_id": user_id}
        if time > 0:
            params["time"] = time
        return await self.call_api("mark_private_msg_as_read", params)

    async def get_friend_msg_history(self, user_id: int, count: int = 20) -> Dict[str, Any]:
        """
        获取私聊消息历史记录。

        Args:
            user_id (int): 目标用户的 QQ 号。
            count (int, optional): 要获取的消息数量。Defaults to 20.

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("get_friend_msg_history", {"user_id": user_id, "count": count})

    async def forward_friend_single_msg(self, user_id: int, message_id: str) -> Dict[str, Any]:
        """
        转发单条好友消息。

        Args:
            user_id (int): 目标用户的 QQ 号。
            message_id (str): 要转发的消息 ID。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("forward_friend_single_msg", {"user_id": user_id, "message_id": message_id})


