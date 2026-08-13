"""
API 基础模块

定义了 API 调用的基础接口和统一处理逻辑。
"""
import copy
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

from ..utils.logger import logger

if TYPE_CHECKING:
    from ..ws import WS
    from neobot.models.message import MessageSegment


class BaseAPI:
    """
    API 基础类，提供了统一的 `call_api` 方法，包含日志记录和异常处理。
    """
    _ws: "WS"
    self_id: int

    def __init__(self, ws_client: "WS", self_id: int):
        self._ws = ws_client
        self.self_id = self_id

    def _process_message(self, message: Union[str, "MessageSegment", List["MessageSegment"], Dict, List[Dict]]) -> Union[str, List[Dict]]:
        """
        将消息转换为 OneBot API 可以接受的格式。
        
        Args:
            message: 消息内容，可以是：
                - str: 纯文本
                - MessageSegment: 单个消息段
                - List[MessageSegment]: 消息段列表
                - Dict: 单个消息段字典
                - List[Dict]: 消息段字典列表
                
        Returns:
            转换后的消息，字符串或消息段字典列表
        """
        from neobot.models.message import MessageSegment
        
        if message is None:
            return ""
        
        if isinstance(message, str):
            return message
        
        # OneBot v11 要求消息段必须包装在数组中（字符串除外），
        # 单个消息段/字典统一转为单元素列表。
        if isinstance(message, dict):
            return [message]
        
        if isinstance(message, MessageSegment):
            return [{"type": message.type, "data": message.data}]
        
        if isinstance(message, list):
            result = []
            for item in message:
                if isinstance(item, MessageSegment):
                    result.append({"type": item.type, "data": item.data})
                elif isinstance(item, dict):
                    result.append(item)
                elif isinstance(item, str):
                    if item:
                        result.append({"type": "text", "data": {"text": item}})
                elif item is not None:
                    result.append(str(item))
            return result
        
        return str(message)

    async def call_api(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        调用 OneBot v11 API，并提供统一的日志和异常处理。

        :param action: API 动作名称
        :param params: API 参数
        :return: API 响应结果的数据部分
        :raises Exception: 当 API 调用失败或发生网络错误时
        """
        if params is None:
            params = {}
        
        try:
            # 日志记录前，对敏感或过长的参数进行处理
            log_params = copy.deepcopy(params)
            
            # 处理各种可能包含base64数据的字段
            def truncate_base64_recursive(obj):
                """递归处理可能包含base64数据的对象"""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        if isinstance(value, str):
                            if value.startswith('data:image/') or value.startswith('data:video/') or value.startswith('data:audio/'):
                                obj[key] = f"{value[:50]}... (base64 truncated)"
                            elif len(value) > 100 and ('/' in value[:50] and '+' in value[:50] and '=' in value[-10:]):
                                # 检查是否是base64编码的字符串
                                obj[key] = f"{value[:50]}... (base64-like truncated)"
                        elif isinstance(value, (dict, list)):
                            truncate_base64_recursive(value)
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, (dict, list)):
                            truncate_base64_recursive(item)
            
            truncate_base64_recursive(log_params)

            # 如果是发送消息的动作，则原子化地增加发送消息总数
            if action in ["send_private_msg", "send_group_msg", "send_msg"]:
                from ..managers.redis_manager import redis_manager
                try:
                    lua_script = "return redis.call('INCR', KEYS[1])"
                    await redis_manager.execute_lua_script(
                        script=lua_script,
                        keys=["neobot:stats:messages_sent"],
                        args=[]
                    )
                except Exception as e:
                    logger.error(f"发送消息计数失败: {e}")

            logger.debug(f"调用API -> action: {action}, params: {log_params}")
            
            response = await self._ws.call_api(action, params)
            
            # 对响应也做类似的处理
            log_response = copy.deepcopy(response)
            truncate_base64_recursive(log_response)
            logger.debug(f"API响应 <- {log_response}")

            if response.get("status") == "failed":
                logger.warning(f"API调用失败: {response}")
            
            return response.get("data")

        except Exception as e:
            logger.error(f"API调用异常: action={action}, params={params}, error={e}")
            raise
