# -*- coding: utf-8 -*-
"""
跨平台消息互通插件配置模块
"""
import os
from typing import Dict, Any
from neobot.plugin_api import ModuleLogger, global_config
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

# 创建模块专用日志记录器
logger = ModuleLogger("CrossPlatformConfig")

class CrossPlatformConfig:
    def __init__(self):
        self.CROSS_PLATFORM_MAP: Dict[int, Dict[str, Any]] = {}
        self.CROSS_PLATFORM_CHANNEL = "neobot_cross_platform"
        self.ENABLE_CROSS_PLATFORM = True
        
        # DeepSeek API 配置 - 从环境变量或配置文件加载
        self.DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
        self.DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "")
        self.DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        
        # 是否启用翻译功能
        self.ENABLE_TRANSLATION = True
        
        # 从全局配置加载
        self.load_from_global_config()

    def load_from_global_config(self):
        """从全局配置加载跨平台配置"""
        if global_config and hasattr(global_config, 'cross_platform'):
            cross_platform_config = global_config.cross_platform
            if cross_platform_config:
                self.ENABLE_CROSS_PLATFORM = getattr(cross_platform_config, 'enabled', True)
                self.CROSS_PLATFORM_MAP = {}
                
                if hasattr(cross_platform_config, 'translation') and cross_platform_config.translation:
                    translation_config = cross_platform_config.translation
                    self.ENABLE_TRANSLATION = getattr(translation_config, 'enabled', True)
                    if translation_config.api_key:
                        self.DEEPSEEK_API_KEY = translation_config.api_key
                    if translation_config.api_url:
                        self.DEEPSEEK_API_URL = translation_config.api_url
                    if translation_config.model:
                        self.DEEPSEEK_MODEL = translation_config.model
                    logger.info(f"[CrossPlatform] 翻译配置已加载: model={self.DEEPSEEK_MODEL}, enabled={self.ENABLE_TRANSLATION}")
                
                if hasattr(cross_platform_config, 'mappings') and cross_platform_config.mappings:
                    for discord_id, mapping in cross_platform_config.mappings.items():
                        if isinstance(mapping, dict):
                            self.CROSS_PLATFORM_MAP[discord_id] = {
                                "qq_group_id": int(mapping.get("qq_group_id", 0)),
                                "name": mapping.get("name", "")
                            }
                        elif hasattr(mapping, 'qq_group_id'):
                            self.CROSS_PLATFORM_MAP[discord_id] = {
                                "qq_group_id": int(mapping.qq_group_id),
                                "name": getattr(mapping, 'name', "")
                            }
                    logger.success(f"[CrossPlatform] 从全局配置加载了 {len(self.CROSS_PLATFORM_MAP)} 个映射")

    async def reload(self):
        """重新加载配置"""
        try:
            # 优先使用全局配置
            self.load_from_global_config()
            
            # 如果全局配置不可用，尝试从文件加载
            if not self.CROSS_PLATFORM_MAP:
                config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.toml")
                
                if os.path.exists(config_path):
                    
                    with open(config_path, "rb") as f:
                        config_data = tomllib.load(f)
                        
                    cross_platform_config = config_data.get("cross_platform", {})
                    self.ENABLE_CROSS_PLATFORM = cross_platform_config.get("enabled", True)
                    
                    # 重新加载映射配置
                    mappings = cross_platform_config.get("mappings", {})
                    self.CROSS_PLATFORM_MAP.clear()
                    
                    if isinstance(mappings, dict) and mappings:
                        for key, value in mappings.items():
                            if isinstance(value, dict) and "qq_group_id" in value:
                                try:
                                    # 直接将 key 转换为整数
                                    discord_id = int(str(key))
                                    self.CROSS_PLATFORM_MAP[discord_id] = {
                                        "qq_group_id": int(value.get("qq_group_id", 0)),
                                        "name": value.get("name", "")
                                    }
                                except (ValueError, AttributeError):
                                    logger.warning(f"[CrossPlatform] 无效的 Discord 频道 ID: {key}")
                                    continue
                    
                    logger.success(f"[CrossPlatform] 配置已重新加载: {len(self.CROSS_PLATFORM_MAP)} 个映射")
                
        except Exception as e:
            logger.error(f"[CrossPlatform] 重新加载配置失败: {e}")

config = CrossPlatformConfig()
