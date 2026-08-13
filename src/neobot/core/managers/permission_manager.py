"""
权限管理器模块

该模块负责管理用户权限，支持 admin、op、user 三个权限级别。
以 permissions.json 文件作为主要数据源，Redis 用于加速访问。
"""
import orjson
import os
import json
from typing import Dict, Set

from ..utils.logger import logger
from ..utils.singleton import Singleton
from .redis_manager import redis_manager
from ..permission import Permission


# 用于从字符串名称查找权限对象的字典
_PERMISSIONS: Dict[str, Permission] = {
    p.value: p for p in Permission
}


class PermissionManager(Singleton):
    """
    权限管理器类

    以 permissions.json 文件作为权限数据的主要来源，Redis 用于高速缓存访问。
    所有写操作会同时更新文件和Redis缓存，确保数据一致性。
    """
    _REDIS_KEY = "neobot:permissions"  # 用于存储用户权限的 Redis Hash 键
    _REDIS_ADMINS_KEY = "neobot:admins"  # 用于存储管理员列表的 Redis 键

    def __init__(self):
        """
        初始化权限管理器
        """
        if hasattr(self, '_initialized') and self._initialized:
            return

        # 权限数据文件路径，作为主要数据源
        self.data_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "data",
            "permissions.json"
        )
        
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        
        # 如果文件不存在，创建默认文件
        if not os.path.exists(self.data_file):
            default_data = {"users": {}}
            with open(self.data_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(default_data, indent=2, ensure_ascii=False))
            logger.info(f"已创建默认权限文件: {self.data_file}")
        
        logger.info("权限管理器初始化完成")
        super().__init__()

    async def initialize(self):
        """
        异步初始化，以 permissions.json 文件内容为主，同步到 Redis 缓存
        """
        try:
            # 总是以文件内容为主，强制同步到 Redis
            logger.info("以 permissions.json 文件内容为准，同步到 Redis 缓存...")
            await self._sync_file_to_redis()
            
            # 检查 Redis 中的数据量
            perm_count = await redis_manager.redis.hlen(self._REDIS_KEY)
            admin_count = await redis_manager.redis.scard(self._REDIS_ADMINS_KEY)
            logger.info(f"Redis 缓存已同步，权限数据: {perm_count} 条，管理员: {admin_count} 位。")
        except Exception as e:
            logger.error(f"初始化权限数据时发生错误: {e}")

    async def _sync_file_to_redis(self):
        """
        将 permissions.json 文件内容同步到 Redis 缓存
        """
        try:
            # 清空 Redis 中的现有数据
            await redis_manager.redis.delete(self._REDIS_KEY)
            await redis_manager.redis.delete(self._REDIS_ADMINS_KEY)
            
            # 从文件加载数据
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = orjson.loads(f.read())
                    users = data.get("users", {})
                    
                    if users:
                        # 分离普通权限和管理员权限
                        normal_perms = {}
                        admin_ids = set()
                        
                        for user_id, level_name in users.items():
                            if level_name == Permission.ADMIN.value:
                                admin_ids.add(user_id)
                            else:
                                normal_perms[user_id] = level_name
                        
                        # 使用 pipeline 批量写入普通权限
                        if normal_perms:
                            async with redis_manager.redis.pipeline(transaction=True) as pipe:
                                for user_id, level_name in normal_perms.items():
                                    pipe.hset(self._REDIS_KEY, user_id, level_name)
                                await pipe.execute()
                            
                        # 使用 pipeline 批量写入管理员
                        if admin_ids:
                            await redis_manager.redis.sadd(self._REDIS_ADMINS_KEY, *admin_ids)
                        
                        logger.success(f"成功同步 {len(users)} 条权限数据到 Redis (普通权限: {len(normal_perms)}, 管理员: {len(admin_ids)})")
                    else:
                        logger.info("permissions.json 文件中没有权限数据，已清空 Redis 缓存。")
            else:
                logger.warning(f"权限文件 {self.data_file} 不存在，已清空 Redis 缓存。")
                
        except ValueError as e:
            logger.error(f"解析 permissions.json 失败: {e}")
        except Exception as e:
            logger.error(f"同步文件到 Redis 失败: {e}")

    async def _migrate_from_file_to_redis(self):
        """
        从 permissions.json 加载权限数据并存入 Redis Hash
        """
        perms_to_migrate = {}
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = orjson.loads(f.read())
                    perms_to_migrate = data.get("users", {})
            
            if perms_to_migrate:
                # 使用 pipeline 批量写入，提高效率
                async with redis_manager.redis.pipeline(transaction=True) as pipe:
                    for user_id, level_name in perms_to_migrate.items():
                        pipe.hset(self._REDIS_KEY, user_id, level_name)
                    await pipe.execute()
                logger.success(f"成功从文件迁移 {len(perms_to_migrate)} 条权限数据到 Redis。")
            else:
                logger.info("permissions.json 文件为空或不存在，无需迁移。")

        except ValueError as e:
            logger.error(f"解析 permissions.json 失败，无法迁移: {e}")
        except Exception as e:
            logger.error(f"迁移权限数据到 Redis 失败: {e}")

    async def _migrate_admins_from_file_to_redis(self):
        """
        从 permissions.json 加载管理员列表并存入 Redis
        """
        admins_to_migrate = set()
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = orjson.loads(f.read())
                    # 从 users 字段中查找权限为 admin 的用户
                    users = data.get("users", {})
                    for user_id, level_name in users.items():
                        if level_name == Permission.ADMIN.value:
                            admins_to_migrate.add(user_id)
                    
                    # 同时兼容旧版的 admins 字段（如果存在的话）
                    old_admins = data.get("admins", [])
                    for admin_id in old_admins:
                        admins_to_migrate.add(str(admin_id))
            
            if admins_to_migrate:
                await redis_manager.redis.sadd(self._REDIS_ADMINS_KEY, *admins_to_migrate)
                logger.success(f"成功从文件迁移 {len(admins_to_migrate)} 位管理员到 Redis。")
            else:
                logger.info("permissions.json 文件中没有管理员数据，无需迁移。")

        except ValueError as e:
            logger.error(f"解析 permissions.json 失败，无法迁移管理员数据: {e}")
        except Exception as e:
            logger.error(f"迁移管理员数据到 Redis 失败: {e}")

    async def _save_to_file_backup(self):
        """
        将 Redis 中的权限数据和管理员列表完整备份到 permissions.json
        """
        try:
            all_perms = await redis_manager.redis.hgetall(self._REDIS_KEY)
            # 由于Redis连接已设置decode_responses=True，所以直接使用字符串
            users_data = {k: v for k, v in all_perms.items()}
            
            # 获取Redis中的管理员列表并合并到数据中
            all_admins = await redis_manager.redis.smembers(self._REDIS_ADMINS_KEY)
            for admin_id in all_admins:
                users_data[admin_id] = Permission.ADMIN.value  # 管理员拥有最高权限
            
            with open(self.data_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"users": users_data}, indent=2, ensure_ascii=False))
            logger.debug(f"权限数据已备份到 {self.data_file}")
        except Exception as e:
            logger.error(f"备份权限数据到 permissions.json 失败: {e}")

    async def get_user_permission(self, user_id: int) -> Permission:
        """
        获取指定用户的权限对象

        优先检查是否为机器人管理员，然后从 Redis 查询。
        """
        # 检查用户是否为管理员（Redis Set 中的存在性检查）
        try:
            if await redis_manager.redis.sismember(self._REDIS_ADMINS_KEY, str(user_id)):
                return Permission.ADMIN
        except Exception as e:
            logger.error(f"从 Redis 检查管理员权限失败: {e}")

        try:
            level_name = await redis_manager.redis.hget(self._REDIS_KEY, str(user_id))
            if level_name:
                return _PERMISSIONS.get(level_name, Permission.USER)
        except Exception as e:
            logger.error(f"从 Redis 获取用户 {user_id} 权限失败: {e}")
        
        return Permission.USER

    async def set_user_permission(self, user_id: int, permission: Permission) -> None:
        """
        设置指定用户的权限级别，首先更新文件，然后同步到 Redis 缓存
        """
        if not isinstance(permission, Permission):
            raise ValueError(f"无效的权限对象: {permission}")

        try:
            # 首先从文件加载当前数据
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = orjson.loads(f.read())
            else:
                data = {"users": {}}
            
            # 更新权限数据
            data["users"][str(user_id)] = permission.value
            
            # 原子性写入文件
            temp_file = self.data_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
            os.replace(temp_file, self.data_file)  # 原子操作
            
            # 同步到 Redis
            await self._sync_file_to_redis()
            logger.info(f"已设置用户 {user_id} 的权限为 {permission.value}，并同步到 Redis")
        except Exception as e:
            logger.error(f"设置用户 {user_id} 权限失败: {e}")

    async def remove_user(self, user_id: int) -> None:
        """
        从权限设置中移除指定用户，首先更新文件，然后同步到 Redis 缓存
        """
        try:
            # 首先从文件加载当前数据
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = orjson.loads(f.read())
            else:
                data = {"users": {}}
            
            # 从权限数据中移除用户
            user_id_str = str(user_id)
            if user_id_str in data["users"]:
                del data["users"][user_id_str]
            
            # 原子性写入文件
            temp_file = self.data_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
            os.replace(temp_file, self.data_file)  # 原子操作
            
            # 同步到 Redis
            await self._sync_file_to_redis()
            logger.info(f"已从权限设置中移除用户 {user_id}，并同步到 Redis")
        except Exception as e:
            logger.error(f"移除用户 {user_id} 权限失败: {e}")

    async def check_permission(self, user_id: int, required_permission: Permission) -> bool:
        """
        检查用户是否具有指定权限级别
        """
        user_permission = await self.get_user_permission(user_id)
        
        # 增强类型检查，防止将property对象等错误类型传递进来
        if not isinstance(required_permission, Permission):
            logger.error(f"权限检查失败：required_permission 不是 Permission 枚举类型，而是 {type(required_permission).__name__}")
            return False
            
        return user_permission >= required_permission

    async def get_all_user_permissions(self) -> Dict[str, str]:
        """
        获取所有已配置的用户权限（合并普通权限和管理员）
        """
        permissions = {}
        try:
            # 从 Redis 获取基础权限
            all_perms = await redis_manager.redis.hgetall(self._REDIS_KEY)
            # 由于Redis连接已设置decode_responses=True，所以直接使用字符串
            permissions = {k: v for k, v in all_perms.items()}
        except Exception as e:
            logger.error(f"从 Redis 获取所有权限失败: {e}")

        # 获取 Redis 中的管理员列表并添加到权限字典中
        try:
            admins = await redis_manager.redis.smembers(self._REDIS_ADMINS_KEY)
            for admin_id in admins:
                permissions[str(admin_id)] = Permission.ADMIN.value
        except Exception as e:
            logger.error(f"获取管理员列表以合并权限时失败: {e}")
            
        return permissions

    async def is_admin(self, user_id: int) -> bool:
        """
        检查用户是否为管理员
        """
        try:
            return await redis_manager.redis.sismember(self._REDIS_ADMINS_KEY, str(user_id))
        except Exception as e:
            logger.error(f"从 Redis 检查管理员权限失败: {e}")
            return False

    async def add_admin(self, user_id: int) -> bool:
        """
        添加管理员，首先更新文件，然后同步到 Redis 缓存
        """
        try:
            # 首先从文件加载当前数据
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = orjson.loads(f.read())
            else:
                data = {"users": {}}
            
            user_id_str = str(user_id)
            # 检查用户是否已经是管理员
            if data["users"].get(user_id_str) == Permission.ADMIN.value:
                return False  # 用户已经是管理员
            
            # 更新权限数据为管理员
            data["users"][user_id_str] = Permission.ADMIN.value
            
            # 原子性写入文件
            temp_file = self.data_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
            os.replace(temp_file, self.data_file)  # 原子操作
            
            # 同步到 Redis
            await self._sync_file_to_redis()
            logger.info(f"已添加新管理员 {user_id}，并同步到 Redis")
            return True
        except Exception as e:
            logger.error(f"添加管理员 {user_id} 失败: {e}")
            return False

    async def remove_admin(self, user_id: int) -> bool:
        """
        从管理员列表中移除用户，首先更新文件，然后同步到 Redis 缓存
        """
        try:
            # 首先从文件加载当前数据
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = orjson.loads(f.read())
            else:
                data = {"users": {}}
            
            user_id_str = str(user_id)
            # 检查用户是否是管理员
            if data["users"].get(user_id_str) != Permission.ADMIN.value:
                return False  # 用户不是管理员
            
            # 将管理员降级为普通用户（或者可以选择完全移除权限）
            # 这里我们将其设置为USER权限
            data["users"][user_id_str] = Permission.USER.value
            
            # 原子性写入文件
            temp_file = self.data_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
            os.replace(temp_file, self.data_file)  # 原子操作
            
            # 同步到 Redis
            await self._sync_file_to_redis()
            logger.info(f"已从管理员列表中移除用户 {user_id}，并同步到 Redis")
            return True
        except Exception as e:
            logger.error(f"移除管理员 {user_id} 失败: {e}")
            return False

    async def get_all_admins(self) -> Set[int]:
        """
        从 Redis 获取所有管理员的集合
        """
        try:
            admins = await redis_manager.redis.smembers(self._REDIS_ADMINS_KEY)
            return {int(admin_id) for admin_id in admins}
        except Exception as e:
            logger.error(f"从 Redis 获取所有管理员失败: {e}")
            return set()

    async def clear_all(self) -> None:
        """
        清空所有权限设置，首先更新文件，然后同步到 Redis 缓存
        """
        try:
            # 创建空的权限数据
            empty_data: Dict[str, Dict] = {"users": {}}
            
            # 原子性写入文件
            temp_file = self.data_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(empty_data, indent=2, ensure_ascii=False))
            os.replace(temp_file, self.data_file)  # 原子操作
            
            # 同步到 Redis
            await self._sync_file_to_redis()
            logger.info("已清空所有权限设置，并同步到 Redis")
        except Exception as e:
            logger.error(f"清空权限数据失败: {e}")


def require_admin(func):
    """
    一个装饰器，用于限制命令只能由管理员执行。
    """
    from functools import wraps
    from neobot.models.events.message import MessageEvent

    @wraps(func)
    async def wrapper(event: MessageEvent, *args, **kwargs):
        from neobot.core.managers import permission_manager
        pm = permission_manager
        if not await pm.is_admin(event.user_id):
            await event.reply("此命令仅限管理员使用")
            return
        return await func(event, *args, **kwargs)
    return wrapper


permission_manager = PermissionManager()
