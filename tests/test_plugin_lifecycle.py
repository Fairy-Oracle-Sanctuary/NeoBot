"""插件生命周期钩子：启动、关闭、热重载。"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neobot.core.managers.command_manager import CommandManager
from neobot.core.managers.plugin_manager import PluginManager
from neobot.plugin_api.lifecycle import (
    clear_module_hooks,
    hooks_for,
    on_shutdown,
    on_startup,
)


@pytest.fixture
def plugin_manager():
    command_manager = MagicMock(spec=CommandManager)
    command_manager.plugins = {}
    manager = PluginManager(command_manager)
    original_command_manager = manager._command_manager
    original_loaded = set(manager.loaded_plugins)
    manager._command_manager = command_manager
    yield manager
    manager._command_manager = original_command_manager
    manager.loaded_plugins.clear()
    manager.loaded_plugins.update(original_loaded)


@pytest.fixture
def scratch_modules():
    names: list[str] = []
    yield names
    for name in names:
        clear_module_hooks(name)


def _bind(func, module_name: str):
    func.__module__ = module_name
    return func


class TestLifecycleRegistry:
    def test_reregister_replaces_same_function_name(self, scratch_modules):
        module_name = "neobot.plugins._lc_replace"
        scratch_modules.append(module_name)

        def start_v1():
            return 1

        def start_v2():
            return 2

        start_v1.__name__ = "start"
        start_v2.__name__ = "start"
        on_startup(_bind(start_v1, module_name))
        on_startup(_bind(start_v2, module_name))

        hooks = hooks_for(module_name, "startup")
        assert len(hooks) == 1
        assert hooks[0]() == 2

    def test_distinct_hooks_are_kept_in_order(self, scratch_modules):
        module_name = "neobot.plugins._lc_multi"
        scratch_modules.append(module_name)

        def first():
            return None

        def second():
            return None

        on_startup(_bind(first, module_name))
        on_startup(_bind(second, module_name))
        assert [hook.__name__ for hook in hooks_for(module_name, "startup")] == [
            "first",
            "second",
        ]


class TestPluginManagerLifecycle:
    async def test_startup_and_shutdown_only_loaded_plugins(
        self, plugin_manager, scratch_modules
    ):
        loaded = "neobot.plugins._lc_loaded"
        skipped = "neobot.plugins._lc_skipped"
        scratch_modules.extend([loaded, skipped])
        order: list[str] = []

        async def start_loaded():
            order.append("start-loaded")

        async def start_skipped():
            order.append("start-skipped")

        async def stop_loaded():
            order.append("stop-loaded")

        on_startup(_bind(start_loaded, loaded))
        on_startup(_bind(start_skipped, skipped))
        on_shutdown(_bind(stop_loaded, loaded))

        plugin_manager.loaded_plugins.add(loaded)
        await plugin_manager.run_startup_hooks()
        await plugin_manager.run_shutdown_hooks()

        assert order == ["start-loaded", "stop-loaded"]

    async def test_startup_error_does_not_block_other_plugins(
        self, plugin_manager, scratch_modules
    ):
        bad = "neobot.plugins._lc_bad"
        good = "neobot.plugins._lc_good"
        scratch_modules.extend([bad, good])
        order: list[str] = []

        async def start_bad():
            order.append("bad")
            raise RuntimeError("startup failed")

        async def start_good():
            order.append("good")

        on_startup(_bind(start_bad, bad))
        on_startup(_bind(start_good, good))
        plugin_manager.loaded_plugins.update({bad, good})

        await plugin_manager.run_startup_hooks()
        assert order == ["bad", "good"] or order == ["good", "bad"]
        assert "good" in order and "bad" in order

    async def test_reload_stops_then_reloads_then_starts(
        self, plugin_manager, scratch_modules
    ):
        module_name = "neobot.plugins._lc_reload"
        scratch_modules.append(module_name)
        order: list[str] = []

        async def shutdown():
            order.append("shutdown")

        async def startup():
            order.append("startup")

        on_shutdown(_bind(shutdown, module_name))
        on_startup(_bind(startup, module_name))
        plugin_manager.loaded_plugins.add(module_name)

        def fake_reload(name):
            order.append(f"reload:{name}")
            return True

        original_reload = plugin_manager.reload_plugin
        plugin_manager.reload_plugin = fake_reload
        try:
            ok = await plugin_manager.reload_plugin_async(module_name)
        finally:
            plugin_manager.reload_plugin = original_reload

        assert ok is True
        assert order == [
            "shutdown",
            f"reload:{module_name}",
            "startup",
        ]

    async def test_failed_reload_skips_startup_but_restarts_parent_package(
        self, plugin_manager, scratch_modules
    ):
        parent = "neobot.plugins._lc_pkg"
        child = "neobot.plugins._lc_pkg.handlers"
        scratch_modules.extend([parent, child])
        order: list[str] = []

        async def shutdown():
            order.append("parent-shutdown")

        async def startup():
            order.append("parent-startup")

        on_shutdown(_bind(shutdown, parent))
        on_startup(_bind(startup, parent))
        plugin_manager.loaded_plugins.add(parent)

        def fake_reload(name):
            order.append(f"reload:{name}")
            return False

        original_reload = plugin_manager.reload_plugin
        plugin_manager.reload_plugin = fake_reload
        try:
            ok = await plugin_manager.reload_plugin_async(child)
        finally:
            plugin_manager.reload_plugin = original_reload

        assert ok is False
        assert order == [
            "parent-shutdown",
            f"reload:{child}",
            "parent-startup",
        ]

    async def test_submodule_reload_restarts_owning_package(
        self, plugin_manager, scratch_modules
    ):
        parent = "neobot.plugins._lc_pkg_ok"
        child = "neobot.plugins._lc_pkg_ok.forwarder"
        scratch_modules.extend([parent, child])
        order: list[str] = []

        async def shutdown():
            order.append("parent-shutdown")

        async def startup():
            order.append("parent-startup")

        on_shutdown(_bind(shutdown, parent))
        on_startup(_bind(startup, parent))
        plugin_manager.loaded_plugins.add(parent)

        def fake_reload(name):
            order.append(f"reload:{name}")
            return True

        original_reload = plugin_manager.reload_plugin
        plugin_manager.reload_plugin = fake_reload
        try:
            await plugin_manager.reload_plugin_async(child)
        finally:
            plugin_manager.reload_plugin = original_reload

        assert order == [
            "parent-shutdown",
            f"reload:{child}",
            "parent-startup",
        ]


def test_background_plugins_declare_lifecycle_hooks():
    """原先由 main.py 点名启动的插件改为自行声明生命周期钩子。"""
    plugins = Path(__file__).resolve().parents[1] / "src" / "neobot" / "plugins"
    for filename in ("wanfeng_review.py", "wanfeng_members.py"):
        source = (plugins / filename).read_text(encoding="utf-8")
        assert "on_startup" in source
        assert "on_shutdown" in source
    package = (plugins / "discord_cross" / "__init__.py").read_text(encoding="utf-8")
    assert "on_startup" in package
    assert "on_shutdown" in package


def test_package_init_maps_to_package_module_name():
    import main

    def plugin_path(*parts: str) -> str:
        return os.path.join(main.PLUGIN_DIR, *parts)

    assert main.plugin_module_name_from_path(plugin_path("wanfeng_review.py")) == (
        "neobot.plugins.wanfeng_review"
    )
    assert main.plugin_module_name_from_path(plugin_path("discord_cross", "__init__.py")) == (
        "neobot.plugins.discord_cross"
    )
    assert main.plugin_module_name_from_path(plugin_path("__init__.py")) is None
