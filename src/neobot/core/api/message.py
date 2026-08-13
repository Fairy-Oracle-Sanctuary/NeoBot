"""
消息相关 API 模块

该模块定义了 `MessageAPI` Mixin 类，提供了所有与消息发送、撤回、
转发等相关的 OneBot v11 API 封装。
"""
from typing import Union, List, Dict, Any, TYPE_CHECKING
from .base import BaseAPI

if TYPE_CHECKING:
    from neobot.models.message import MessageSegment
    from neobot.models.events.base import OneBotEvent


class MessageAPI(BaseAPI):
    """
    `MessageAPI` Mixin 类，提供了所有与消息操作相关的 API 方法。
    """

    async def send_group_msg(
        self,
        group_id: int,
        message: Union[str, "MessageSegment", List["MessageSegment"]],
        auto_escape: bool = False,
        no_mirror: bool = False,
    ) -> Dict[str, Any]:
        """
        发送群消息。

        Args:
            group_id (int): 目标群组的群号。
            message (Union[str, MessageSegment, List[MessageSegment]]): 要发送的消息内容。
                可以是纯文本字符串、单个消息段对象或消息段列表。
            auto_escape (bool, optional): 仅当 `message` 为字符串时有效，
                是否对消息内容进行 CQ 码转义。Defaults to False.

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        params = {
            "group_id": group_id,
            "message": self._process_message(message),
            "auto_escape": auto_escape,
        }
        if no_mirror:
            # 跨平台回传的消息不触发 QQ→Discord 镜像，避免回显
            params["_no_mirror"] = True
        return await self.call_api("send_group_msg", params)

    async def send_private_msg(self, user_id: int, message: Union[str, "MessageSegment", List["MessageSegment"]], auto_escape: bool = False) -> Dict[str, Any]:
        """
        发送私聊消息。

        Args:
            user_id (int): 目标用户的 QQ 号。
            message (Union[str, MessageSegment, List[MessageSegment]]): 要发送的消息内容。
            auto_escape (bool, optional): 是否对消息内容进行 CQ 码转义。Defaults to False.

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api(
            "send_private_msg", {"user_id": user_id, "message": self._process_message(message), "auto_escape": auto_escape}
        )

    async def send(self, event: "OneBotEvent", message: Union[str, "MessageSegment", List["MessageSegment"]], auto_escape: bool = False) -> Dict[str, Any]:
        """
        智能发送消息。

        该方法会根据传入的事件对象 `event` 自动判断是私聊还是群聊，
        并调用相应的发送函数。如果事件是消息事件，则优先使用 `reply` 方法。

        Args:
            event (OneBotEvent): 触发该发送行为的事件对象。
            message (Union[str, MessageSegment, List[MessageSegment]]): 要发送的消息内容。
            auto_escape (bool, optional): 是否对消息内容进行 CQ 码转义。Defaults to False.

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        # 如果是消息事件，直接调用 reply
        if hasattr(event, "reply"):
            await event.reply(message, auto_escape)
            return {"status": "ok", "msg": "Replied via event.reply()"}

        # 尝试从事件中获取 user_id 或 group_id
        user_id = getattr(event, "user_id", None)
        group_id = getattr(event, "group_id", None)

        if group_id:
            return await self.send_group_msg(group_id, message, auto_escape)
        elif user_id:
            return await self.send_private_msg(user_id, message, auto_escape)
        
        return {"status": "failed", "msg": "Unknown message target"}

    async def delete_msg(self, message_id: int) -> Dict[str, Any]:
        """
        撤回一条消息。

        Args:
            message_id (int): 要撤回的消息的 ID。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("delete_msg", {"message_id": message_id})

    async def get_msg(self, message_id: int) -> Dict[str, Any]:
        """
        获取一条消息的详细信息。

        Args:
            message_id (int): 要获取的消息的 ID。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据，包含消息详情。
        """
        return await self.call_api("get_msg", {"message_id": message_id})

    async def get_forward_msg(self, id: str) -> List[Dict[str, Any]]:
        """
        获取合并转发消息的内容。

        Args:
            id (str): 合并转发消息的 ID。

        Returns:
            List[Dict[str, Any]]: 转发消息的节点列表。
        """
        forward_data = await self.call_api("get_forward_msg", {"id": id})
        nodes = forward_data.get("data")

        if not isinstance(nodes, list):
            data = forward_data.get('data', {})
            if isinstance(data, dict):
                nodes = data.get('messages')

            if not isinstance(nodes, list):
                raise ValueError("在 get_forward_msg 响应中找不到消息节点列表")

        return nodes

    async def send_group_forward_msg(self, group_id: int, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        发送群聊合并转发消息。

        Args:
            group_id (int): 目标群组的群号。
            messages (List[Dict[str, Any]]): 消息节点列表。
                推荐使用 `bot.build_forward_node` 来构建节点。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("send_group_forward_msg", {"group_id": group_id, "messages": messages})

    async def send_private_forward_msg(self, user_id: int, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        发送私聊合并转发消息。

        Args:
            user_id (int): 目标用户的 QQ 号。
            messages (List[Dict[str, Any]]): 消息节点列表。

        Returns:
            Dict[str, Any]: OneBot API 的响应数据。
        """
        return await self.call_api("send_private_forward_msg", {"user_id": user_id, "messages": messages})
