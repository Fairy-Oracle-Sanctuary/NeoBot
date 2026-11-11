"""
插件管理器模块

负责扫描、加载和管理 `plugins` 目录下的所有插件。
"""
from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
import sys
import time
from typing import List, Optional, Set, Tuple

from .command_manager import CommandManager

from ..utils.exceptions import SyncHandlerError, PluginLoadError, PluginReloadError, PluginNotFoundError
from ..utils.logger import logger, ModuleLogger
from ..utils.singleton import Singleton
from .command_manager import matcher as command_manager

# 注意:不要在本模块顶层 import neobot.plugin_api —— core 包早期初始化期间
# (api -> managers -> plugin_manager 链路)会触发 plugin_api -> core.bot -> core.api
# 的循环导入。检查器与 manifest 均为惰性 import(见 _check_contract_boundary / _store_manifest)。

# 确保logger在模块级别可见
__all__ = ['PluginManager', 'logger']


class PluginManager(Singleton):
    """
    插件管理器类
    """
    #: 慢插件告警阈值(秒)
    SLOW_PLUGIN_THRESHOLD = 0.2

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
        # 旧式插件直接 import 内部模块的聚合记录 [(模块名, [违规模块...]), ...]
        self._legacy_import_violations: List[Tuple[str, List[str]]] = []
        # 插件加载耗时记录 [(模块名, 耗时秒)]，加载完成后汇总输出，慢插件告警
        self._load_timings: List[Tuple[str, float]] = []

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

    def _check_contract_boundary(
        self, module_name: str, module: object
    ) -> List[str]:
        """
        对已加载插件做 import 边界检查(插件 API 契约)。

        - 新式契约插件(manifest 声明 api_version)违规 -> 抛 PluginLoadError 拒绝加载;
        - 旧式插件违规 -> 记入聚合告警,保持兼容继续加载。

        :return: 违规的内部模块路径列表(无违规时为空列表)。
        """
        from ...plugin_api._checker import scan_module_file
        from ...plugin_api.manifest import is_contract_plugin

        file_path = getattr(module, "__file__", None)
        violations = scan_module_file(file_path) if file_path else []

        if not violations:
            return []

        if is_contract_plugin(module):
            # 契约插件违规:卸载已注册的处理器并拒绝加载
            self.command_manager.unload_plugin(module_name)
            raise PluginLoadError(
                plugin_name=module_name,
                message=(
                    f"插件 {module_name} 违反插件 API 契约:直接 import 了内部模块 "
                    f"{violations}。插件只允许使用 neobot.plugin_api 命名空间,"
                    f"请参考 docs/plugin-api.md 迁移。"
                ),
            )

        self._legacy_import_violations.append((module_name, violations))
        return violations

    def _store_manifest(self, module_name: str, module: object) -> None:
        """解析插件清单并注册到 CommandManager(供 /help 等使用)。"""
        from ...plugin_api.manifest import resolve_manifest, to_stored_dict

        meta = resolve_manifest(module)
        stored = to_stored_dict(meta)
        if stored is not None:
            self.command_manager.plugins[module_name] = stored

    def _log_legacy_violations(self) -> None:
        """启动结束时聚合输出旧式插件的契约违规警告,避免逐条刷屏。"""
        if not self._legacy_import_violations:
            return
        names = sorted(name for name, _ in self._legacy_import_violations)
        self.logger.warning(
            f"{len(names)} 个插件仍直接 import 框架内部模块(neobot.core.* / "
            f"neobot.adapters.*): {names}。内部模块不保证 API 稳定,将在未来版本移除;"
            f"请迁移到 neobot.plugin_api 契约命名空间,见 docs/plugin-api.md。"
        )
        self.logger.debug(
            "契约违规明细: "
            + "; ".join(f"{n} -> {v}" for n, v in self._legacy_import_violations)
        )
        self._legacy_import_violations.clear()

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

        # 无论后续是否提前 return,都先重置耗时记录,避免单例残留上次运行的旧数据
        self._load_timings = []

        if not os.path.exists(plugin_dir):
            self.logger.error(f"插件目录不存在：{plugin_dir}")
            return

        self.logger.info(f"正在从 {package_name} 加载插件 (路径：{plugin_dir})...")

        total_start = time.perf_counter()

        for _, module_name, is_pkg in pkgutil.iter_modules([plugin_dir]):
            full_module_name = f"{package_name}.{module_name}"

            plugin_start = time.perf_counter()
            action = "加载"  # 初始化默认值
            try:
                if full_module_name in self.loaded_plugins:
                    self.command_manager.unload_plugin(full_module_name)
                    module = importlib.reload(sys.modules[full_module_name])
                    action = "重载"
                else:
                    module = importlib.import_module(full_module_name)
                    action = "加载"

                self._check_contract_boundary(full_module_name, module)
                self._store_manifest(full_module_name, module)

                self.loaded_plugins.add(full_module_name)

                type_str = "包" if is_pkg else "文件"
                elapsed = time.perf_counter() - plugin_start
                self._load_timings.append((full_module_name, elapsed))
                self.logger.success(
                    f"   [{type_str}] 成功{action}: {module_name} (耗时 {elapsed * 1000:.0f}ms)"
                )
            except SyncHandlerError as e:
                error = PluginLoadError(
                    plugin_name=module_name,
                    message=f"同步处理器错误: {str(e)}",
                    original_error=e
                )
                self.logger.error(f"   插件 {module_name} 加载失败: {error.message} (跳过此插件)")
                self.logger.log_custom_exception(error)
            except PluginLoadError as e:
                # 契约边界违规等加载期错误:单独记录,不吞成"未知错误"
                self.logger.error(f"   插件 {module_name} 加载失败: {e.message} (跳过此插件)")
                self.logger.log_custom_exception(e)
            except Exception as e:
                from ...plugin_api.manifest import PluginManifestError

                if isinstance(e, PluginManifestError):
                    # manifest 声明不合法:给出直接指向字段的错误信息
                    error = PluginLoadError(
                        plugin_name=module_name,
                        message=f"插件清单声明不合法: {str(e)}",
                        original_error=e
                    )
                else:
                    error = PluginLoadError(
                        plugin_name=module_name,
                        message=f"未知错误: {str(e)}",
                        original_error=e
                    )
                self.logger.exception(f"   加载插件 {module_name} 失败: {error.message}")
                self.logger.log_custom_exception(error)

        self._log_legacy_violations()
        self._log_slow_plugins(total_elapsed=time.perf_counter() - total_start)

    def _log_slow_plugins(self, total_elapsed: float) -> None:
        """加载完成后输出总耗时；超过阈值的慢插件逐条告警。"""
        self.logger.info(f"插件加载完成：共 {len(self._load_timings)} 个成功，总耗时 {total_elapsed:.2f}s")
        if not self._load_timings:
            return
        slow = [(name, elapsed) for name, elapsed in self._load_timings if elapsed >= self.SLOW_PLUGIN_THRESHOLD]
        if not slow:
            return
        slow.sort(key=lambda x: -x[1])
        detail = ", ".join(f"{name} {elapsed * 1000:.0f}ms" for name, elapsed in slow)
        self.logger.warning(
            f"{len(slow)} 个插件加载耗时超过 {self.SLOW_PLUGIN_THRESHOLD:.2f}s，可能拖慢启动: {detail}"
        )

    def reload_plugin(self, full_module_name: str) -> bool:
        """
        精确重载单个插件。

        :return: 重载成功为 True；模块不存在或重载过程抛错为 False。
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
            return False

        try:
            self.command_manager.unload_plugin(full_module_name)
            module = importlib.reload(sys.modules[full_module_name])

            self._check_contract_boundary(full_module_name, module)
            self._store_manifest(full_module_name, module)

            self.logger.success(f"插件 {full_module_name} 已成功重载。")
            return True
        except SyncHandlerError as e:
            error = PluginReloadError(
                plugin_name=full_module_name,
                message=f"同步处理器错误: {str(e)}",
                original_error=e
            )
            self.logger.error(f"重载插件 {full_module_name} 失败: {error.message}")
            self.logger.log_custom_exception(error)
        except PluginLoadError as e:
            # 契约边界违规:重载被拒绝。清理残留状态,保持"未加载"一致性:
            # 处理器已由 unload_plugin 移除,这里同步移除 loaded_plugins 与 sys.modules,
            # 下次加载会走完整首次导入路径。
            self.loaded_plugins.discard(full_module_name)
            sys.modules.pop(full_module_name, None)
            self.logger.error(f"重载插件 {full_module_name} 失败: {e.message}")
            self.logger.log_custom_exception(e)
        except Exception as e:
            error = PluginReloadError(
                plugin_name=full_module_name,
                message=f"未知错误: {str(e)}",
                original_error=e
            )
            self.logger.exception(f"重载插件 {full_module_name} 时发生错误: {error.message}")
            self.logger.log_custom_exception(error)
        return False

    def _owning_plugin(self, module_name: str) -> Optional[str]:
        """返回模块自身或包含它的已加载插件包名。"""
        if module_name in self.loaded_plugins:
            return module_name
        parts = module_name.split(".")
        for index in range(len(parts) - 1, 0, -1):
            parent = ".".join(parts[:index])
            if parent in self.loaded_plugins:
                return parent
        return None

    async def _invoke_lifecycle_hooks(self, module_name: str, kind: str) -> None:
        """调用某模块的启动或关闭钩子。单个钩子失败不影响其余钩子。"""
        from ...plugin_api.lifecycle import hooks_for

        label = "启动" if kind == "startup" else "关闭"
        for hook in hooks_for(module_name, kind):
            try:
                result = hook()
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                self.logger.exception(
                    f"插件 {module_name} {label}钩子 {getattr(hook, '__name__', hook)} 失败: {e}"
                )

    async def run_startup_hooks(self) -> None:
        """调用所有已加载插件的启动钩子。应在 Redis 初始化之后调用。"""
        for name in sorted(self.loaded_plugins):
            await self._invoke_lifecycle_hooks(name, "startup")

    async def run_shutdown_hooks(self) -> None:
        """调用所有已加载插件的关闭钩子（进程退出时）。"""
        for name in sorted(self.loaded_plugins):
            await self._invoke_lifecycle_hooks(name, "shutdown")

    async def reload_plugin_async(self, full_module_name: str) -> bool:
        """
        热重载插件，并在重载前后调用生命周期钩子。

        关闭钩子在 ``importlib.reload`` 之前执行，这样旧模块里的后台任务句柄还在。
        重载的是某个已加载插件包的子模块时，会重启该插件包的钩子
        （例如 discord_cross 的 Redis 订阅），子模块自身重载失败时仍会把包拉起来。
        被重载模块本身重载失败时，不再调用它的启动钩子。
        """
        parent = self._owning_plugin(full_module_name)
        restart_parent = parent is not None and parent != full_module_name
        if restart_parent and parent is not None:
            await self._invoke_lifecycle_hooks(parent, "shutdown")
        await self._invoke_lifecycle_hooks(full_module_name, "shutdown")

        ok = self.reload_plugin(full_module_name)

        if restart_parent and parent is not None:
            await self._invoke_lifecycle_hooks(parent, "startup")
        if ok:
            await self._invoke_lifecycle_hooks(full_module_name, "startup")
        else:
            self.logger.error(f"插件 {full_module_name} 重载失败，已跳过其启动钩子")
        return ok


plugin_manager = PluginManager(command_manager=command_manager)
