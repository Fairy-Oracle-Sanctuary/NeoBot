import hashlib
import hmac
import json

import redis.asyncio as redis
from ..config_loader import global_config as config
from ..utils.logger import logger
from ..utils.singleton import Singleton

# 未配置签名密钥时的告警只输出一次，避免刷屏
_warned_no_signing_secret = False

class RedisManager(Singleton):
    """
    Redis 连接管理器（异步单例）
    """
    _redis = None

    def __init__(self):
        """
        初始化 Redis 管理器
        """
        # 调用父类 __init__ 确保单例初始化
        super().__init__()

    async def initialize(self):
        """
        异步初始化 Redis 连接并进行健康检查
        """
        if self._redis is not None:
            return

        client = None
        try:
            redis_config = config.redis
            host = redis_config.host
            port = redis_config.port
            db = redis_config.db
            password = redis_config.password
            
            logger.info(f"正在尝试连接 Redis: {host}:{port}, DB: {db}")

            client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True,
                ssl=False
            )
            if await client.ping():
                self._redis = client
                logger.success("Redis 连接成功！")
            else:
                logger.error("Redis 连接失败: PING 命令无响应")
                await client.aclose()
        except Exception as e:
            logger.exception(f"Redis 初始化时发生未知错误: {e}")
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
            self._redis = None

    @property
    def signing_secret(self) -> str:
        """
        pubsub 消息签名密钥：优先使用独立的 signing_secret 配置，
        否则回退到 Redis 密码（同一 Redis 下的机器人共享同一密钥）。
        """
        try:
            return (getattr(config.redis, "signing_secret", "") or config.redis.password or "")
        except Exception:
            return ""

    def sign_pubsub(self, payload: dict) -> str:
        """
        对 pubsub 消息负载计算 HMAC-SHA256 签名。

        Args:
            payload: 待发布的消息负载（不含 _sig 字段）

        Returns:
            str: 签名字符串；未配置签名密钥时返回空字符串
        """
        secret = self.signing_secret
        if not secret:
            return ""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

    def verify_pubsub(self, payload: dict, signature: str) -> bool:
        """
        校验 pubsub 消息负载的 HMAC 签名，防止任意可访问 Redis 的进程伪造消息。

        Args:
            payload: 收到的消息负载（已剔除 _sig 字段）
            signature: 消息附带的签名字符串

        Returns:
            bool: 校验是否通过
        """
        global _warned_no_signing_secret
        secret = self.signing_secret
        if not secret:
            # 未配置密钥：仅接受无签名消息以兼容旧部署，并给出一次性提示
            if not _warned_no_signing_secret:
                _warned_no_signing_secret = True
                logger.warning("[Redis] 未配置 pubsub 签名密钥，广播/跨平台消息未做签名校验（建议设置 redis.signing_secret）")
            return True
        if not signature:
            logger.warning("[Redis] 收到未签名的 pubsub 消息，拒绝处理")
            return False
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @property
    def redis(self):
        """
        获取 Redis 连接实例
        """
        if self._redis is None:
            raise ConnectionError("Redis 未初始化或连接失败，请先调用 initialize()")
        return self._redis

    async def get(self, name):
        """
        获取指定键的值
        """
        return await self.redis.get(name)

    async def set(self, name, value, ex=None):
        """
        设置指定键的值
        """
        return await self.redis.set(name, value, ex=ex)

    async def execute_lua_script(self, script: str, keys: list, args: list):
        """
        以原子方式执行 Lua 脚本

        Args:
            script (str): 要执行的 Lua 脚本字符串
            keys (list): 脚本中使用的 Redis 键 (KEYS[1], KEYS[2], ...)
            args (list): 传递给脚本的参数 (ARGV[1], ARGV[2], ...)

        Returns:
            Any: 脚本的返回值
        """
        try:
            # redis-py 内部会自动处理脚本的缓存 (EVAL/EVALSHA)
            lua_script = self.redis.register_script(script)
            return await lua_script(keys=keys, args=args)
        except Exception as e:
            logger.error(f"执行 Lua 脚本失败: {e}")
            logger.debug(f"脚本内容: {script}")
            raise


# 全局 Redis 管理器实例
redis_manager = RedisManager()
