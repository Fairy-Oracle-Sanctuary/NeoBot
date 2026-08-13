"""
插件管理器模块

负责扫描、加载和管理 `plugins` 目录下的所有插件。
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from typing import Set
from .command_manager import CommandManager

from ..utils.exceptions import SyncHandlerError, PluginLoadError, PluginReloadError, PluginNotFoundError
from ..utils.logger import logger, ModuleLogger
from ..utils.singleton import Singleton
from .command_manager import matcher as command_manager

# 确保logger在模块级别可见
__all__ = ['PluginManager', 'logger']


class PluginManager(Singleton):
    """
    插件管理器类
    """
    def __init__(self, command_manager: "CommandManager" | None = None) -> None:
        """
        初始化插件管理器

        :param command_manager: CommandManager 的实例
        """
        # 检查是否已经初始化
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        # 只有首次初始化时才执行
        self._initialized = True
        
        # 始终创建 logger 和 loaded_plugins
        self.logger = ModuleLogger("PluginManager")
        self.loaded_plugins: Set[str] = set()
        
        if command_manager:
            self._command_manager = command_manager
        else:
            self._command_manager = None
            
    @property
    def command_manager(self):
        """
        获取命令管理器实例
        """
        if not hasattr(self, '_command_manager') or self._command_manager is None:
            raise AttributeError("'PluginManager' object has no attribute '_command_manager'")
        return self._command_manager

    def load_all_plugins(self) -> None:
        """
        扫描并加载 `plugins` 目录下的所有插件。
        """
        # 使用 pathlib 获取更可靠的路径
        # 当前文件：src/neobot/core/managers/plugin_manager.py
        # 目标：src/neobot/plugins/
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 回退三级到项目根目录 (core/managers -> core -> neobot -> src)
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        plugin_dir = os.path.join(root_dir, "neobot", "plugins")
        
        # 使用完整的包名：neobot.plugins
        package_name = "neobot.plugins"

        if not os.path.exists(plugin_dir):
            self.logger.error(f"插件目录不存在：{plugin_dir}")
            return

        self.logger.info(f"正在从 {package_name} 加载插件 (路径：{plugin_dir})...")

        for _, module_name, is_pkg in pkgutil.iter_modules([plugin_dir]):
            full_module_name = f"{package_name}.{module_name}"

            action = "加载"  # 初始化默认值
            try:
                if full_module_name in self.loaded_plugins:
                    self.command_manager.unload_plugin(full_module_name)
                    module = importlib.reload(sys.modules[full_module_name])
                    action = "重载"
                else:
                    module = importlib.import_module(full_module_name)
                    action = "加载"

                if hasattr(module, "__plugin_meta__"):
                    meta = getattr(module, "__plugin_meta__")
                    self.command_manager.plugins[full_module_name] = meta
                
                self.loaded_plugins.add(full_module_name)

                type_str = "包" if is_pkg else "文件"
                self.logger.success(f"   [{type_str}] 成功{action}: {module_name}")
            except SyncHandlerError as e:
                error = PluginLoadError(
                    plugin_name=module_name,
                    message=f"同步处理器错误: {str(e)}",
                    original_error=e
                )
                self.logger.error(f"   插件 {module_name} 加载失败: {error.message} (跳过此插件)")
                self.logger.log_custom_exception(error)
            except Exception as e:
                error = PluginLoadError(
                    plugin_name=module_name,
                    message=f"未知错误: {str(e)}",
                    original_error=e
                )
                self.logger.exception(f"   加载插件 {module_name} 失败: {error.message}")
                self.logger.log_custom_exception(error)

    def reload_plugin(self, full_module_name: str) -> None:
        """
        精确重载单个插件。
        """
        if full_module_name not in self.loaded_plugins:
            self.logger.warning(f"尝试重载一个未被加载的插件: {full_module_name}，将按首次加载处理。")
        
        if full_module_name not in sys.modules:
            reload_error = PluginNotFoundError(
                plugin_name=full_module_name,
                message="模块未在sys.modules中找到"
            )
            self.logger.error(f"重载失败: {reload_error.message}")
            self.logger.log_custom_exception(reload_error)
            return

        try:
            self.command_manager.unload_plugin(full_module_name)
            module = importlib.reload(sys.modules[full_module_name])
            
            if hasattr(module, "__plugin_meta__"):
                meta = getattr(module, "__plugin_meta__")
                self.command_manager.plugins[full_module_name] = meta
            
            self.logger.success(f"插件 {full_module_name} 已成功重载。")
        except SyncHandlerError as e:
            error = PluginReloadError(
                plugin_name=full_module_name,
                message=f"同步处理器错误: {str(e)}",
                original_error=e
            )
            self.logger.error(f"重载插件 {full_module_name} 失败: {error.message}")
            self.logger.log_custom_exception(error)
        except Exception as e:
            error = PluginReloadError(
                plugin_name=full_module_name,
                message=f"未知错误: {str(e)}",
                original_error=e
            )
            self.logger.exception(f"重载插件 {full_module_name} 时发生错误: {error.message}")
            self.logger.log_custom_exception(error)


plugin_manager = PluginManager(command_manager=command_manager)
