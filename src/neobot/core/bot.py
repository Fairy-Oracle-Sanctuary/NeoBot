"""
Bot 核心抽象模块

该模块定义了 `Bot` 类，它是与 OneBot v11 API 进行交互的主要接口。
`Bot` 类通过继承 `api` 目录下的各个 Mixin 类，将不同类别的 API 调用
整合在一起，提供了一个统一、便捷的调用入口。

主要职责包括：
- 封装 WebSocket 通信，提供 `call_api` 方法。
- 提供高级消息发送功能，如 `send_forwarded_messages`。
- 整合所有细分的 API 调用（消息、群组、好友等）。
"""
from typing import TYPE_CHECKING, Dict, Any, List, Union, Optional
from neobot.models.events.base import OneBotEvent
from neobot.models.message import MessageSegment
from neobot.models.objects import GroupInfo, StrangerInfo

if TYPE_CHECKING:
    from .ws import WS
    from .utils.executor import CodeExecutor

from .api import MessageAPI, GroupAPI, FriendAPI, AccountAPI, MediaAPI


class Bot(MessageAPI, GroupAPI, FriendAPI, AccountAPI, MediaAPI):
    """
    机器人核心类，封装了所有与 OneBot API 的交互。

    通过 Mixin 模式继承了所有 API 功能，使得结构清晰且易于扩展。
    实例由 `WS` 客户端在连接成功后创建，并传递给所有事件处理器和插件。
    """

    def __init__(self, ws_client: "WS"):
        """
        初始化 Bot 实例。

        Args:
            ws_client (WS): WebSocket 客户端实例，负责底层的 API 请求和响应处理。
        """
        super().__init__(ws_client, ws_client.self_id or 0)
        self.code_executor: Optional["CodeExecutor"] = None
        self.nickname: str = ""

    async def get_group_list(self, no_cache: bool = False) -> List[GroupInfo]:
        # GroupAPI.get_group_list 不支持 no_cache 参数，这里忽略它
        result = await super().get_group_list()
        # 确保结果是 GroupInfo 对象列表
        return [GroupInfo(**group) if isinstance(group, dict) else group for group in result]

    async def get_stranger_info(self, user_id: int, no_cache: bool = False) -> StrangerInfo:
        result = await super().get_stranger_info(user_id=user_id, no_cache=no_cache)
        # 确保结果是 StrangerInfo 对象
        if isinstance(result, dict):
            return StrangerInfo(**result)
        return result


    def build_forward_node(self, user_id: int, nickname: str, message: Union[str, "MessageSegment", List["MessageSegment"]]) -> Dict[str, Any]:
        """
        构建一个用于合并转发的消息节点 (Node)。

        这是一个辅助方法，用于方便地创建符合 OneBot v11 规范的消息节点，
        以便在 `send_forwarded_messages` 中使用。

        Args:
            user_id (int): 发送者的 QQ 号。
            nickname (str): 发送者在消息中显示的昵称。
            message (Union[str, MessageSegment, List[MessageSegment]]): 该节点的消息内容，
                可以是纯文本、单个消息段或消息段列表。

        Returns:
            Dict[str, Any]: 构造好的消息节点字典。
        """
        return {
            "type": "node",
            "data": {
                "uin": user_id,
                "name": nickname,
                "content": self._process_message(message)
            }
        }

    async def send_forwarded_messages(self, target: Union[int, "OneBotEvent"], nodes: List[Dict[str, Any]]):
        """
        发送合并转发消息。

        该方法实现了智能判断，可以根据 `target` 的类型自动发送群聊合并转发
        或私聊合并转发消息。

        Args:
            target (Union[int, OneBotEvent]): 发送目标。
                - 如果是 `OneBotEvent` 对象，则自动判断是群聊还是私聊。
                - 如果是 `int`，则默认为群号，发送群聊合并转发。
            nodes (List[Dict[str, Any]]): 消息节点列表。
                推荐使用 `build_forward_node` 方法来构建列表中的每个节点。

        Raises:
            ValueError: 如果事件对象中既没有 `group_id` 也没有 `user_id`。
        """
        # CommandContext 等平台上下文同样带 group_id/user_id，按事件处理
        if isinstance(target, OneBotEvent) or hasattr(target, "platform"):
            group_id = getattr(target, "group_id", None)
            user_id = getattr(target, "user_id", None)
            
            if group_id:
                # 直接发送群聊合并转发
                await self.send_group_forward_msg(group_id, nodes)
            elif user_id:
                # 发送私聊合并转发
                await self.send_private_forward_msg(user_id, nodes)
            else:
                raise ValueError("Event has neither group_id nor user_id")

        else:
            # 默认行为是发送到群聊
            group_id = target
            await self.send_group_forward_msg(group_id, nodes)
