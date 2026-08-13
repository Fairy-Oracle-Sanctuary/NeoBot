from typing import Dict, List, Optional, TYPE_CHECKING
import threading
from ..utils.logger import ModuleLogger

if TYPE_CHECKING:
    from ..bot import Bot

class BotManager:
    """
    Bot 实例管理器
    
    负责统一管理所有活跃的 Bot 实例（包括正向 WS 和反向 WS 连接的 Bot）。
    提供注册、注销和获取 Bot 实例的方法。
    """
    def __init__(self):
        self._bots: Dict[str, "Bot"] = {}  # type: ignore[assignment]  # key: bot_id (str), value: Bot instance
        self._lock = threading.RLock()
        self.logger = ModuleLogger("BotManager")

    def register_bot(self, bot: "Bot") -> None:
        """
        注册一个 Bot 实例
        """
        if not bot or not bot.self_id:
            self.logger.warning("尝试注册无效的 Bot 实例")
            return
            
        bot_id = str(bot.self_id)
        with self._lock:
            self._bots[bot_id] = bot
            self.logger.info(f"Bot 实例已注册: {bot_id}")

    def unregister_bot(self, bot_id: str) -> None:
        """
        注销一个 Bot 实例
        """
        with self._lock:
            if bot_id in self._bots:
                del self._bots[bot_id]
                self.logger.info(f"Bot 实例已注销: {bot_id}")

    def get_bot(self, bot_id: str) -> Optional["Bot"]:
        """
        根据 ID 获取 Bot 实例
        """
        with self._lock:
            return self._bots.get(str(bot_id))

    def get_all_bots(self) -> List["Bot"]:
        """
        获取所有活跃的 Bot 实例
        """
        with self._lock:
            return list(self._bots.values())

# 全局单例实例
bot_manager = BotManager()
