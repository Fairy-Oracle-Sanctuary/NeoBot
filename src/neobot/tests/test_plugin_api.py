"""
插件 API 契约 (neobot.plugin_api) 测试。

覆盖:
- 契约命名空间导出完整性与身份一致性(与 core/models 同一对象);
- 契约版本号;
- manifest 声明与校验(define_plugin / resolve_manifest / is_contract_plugin);
- import 边界检查器(scan_plugin_imports);
- PluginManager 集成:新式契约插件加载、契约插件违规拒绝、旧式插件兼容。
"""
import textwrap

import pytest
from unittest.mock import MagicMock, patch

import neobot.plugin_api as api
from neobot.core.managers.command_manager import CommandManager
from neobot.core.managers.plugin_manager import PluginManager
from neobot.core.utils.exceptions import PluginLoadError
from neobot.plugin_api._checker import scan_module_file, scan_plugin_imports
from neobot.plugin_api.manifest import (
    PluginManifest,
    PluginManifestError,
    define_plugin,
    is_contract_plugin,
    resolve_manifest,
)


# ---------------------------------------------------------------- 导出完整性

def test_plugin_api_version():
    """契约版本号存在且格式正确。"""
    assert api.API_VERSION == "1"
    parts = api.__version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_all_exports_resolvable():
    """__all__ 声明的每个符号都能从命名空间解析。"""
    missing = [name for name in api.__all__ if not hasattr(api, name)]
    assert missing == []


def test_contract_identity_with_core():
    """契约导出与 core/models 中的对象是同一身份(薄转发,非拷贝)。"""
    from neobot.core.bot import Bot
    from neobot.core.permission import Permission
    from neobot.models.events.message import MessageEvent
    from neobot.models.message import MessageSegment

    assert api.Bot is Bot
    assert api.Permission is Permission
    assert api.MessageEvent is MessageEvent
    assert api.MessageSegment is MessageSegment
    # 注册装饰器为薄封装,行为等价(见 test_command_decorator_registers)


def test_command_decorator_registers():
    """通过契约的 @command 注册后,matcher 中能找到对应指令。"""
    cm = CommandManager(prefixes=("/",))
    with patch("neobot.plugin_api.decorators._matcher", cm):
        @api.command("契约命令")
        async def handler(bot, event, args):
            pass
    assert "契约命令" in cm.message_handler.commands


# ---------------------------------------------------------------- manifest

def test_define_plugin_valid():
    m = define_plugin(
        name="my_plugin", description="描述", usage="/x",
        version="1.2.3", author="镀铬酸钾",
    )
    assert isinstance(m, PluginManifest)
    assert m.api_version == "1"
    assert m.to_dict()["name"] == "my_plugin"


@pytest.mark.parametrize("kwargs", [
    {"name": "1bad"},
    {"name": "bad name"},
    {"name": "bad/name"},
    {"name": ""},
])
def test_define_plugin_invalid_name(kwargs):
    with pytest.raises(PluginManifestError):
        define_plugin(**kwargs)


def test_define_plugin_invalid_version():
    with pytest.raises(PluginManifestError):
        define_plugin(name="ok_plugin", version="v1.0")


def test_define_plugin_unsupported_api_version():
    with pytest.raises(PluginManifestError):
        define_plugin(name="ok_plugin", api_version="2")


def test_resolve_manifest_prefers_plugin_manifest():
    module = MagicMock()
    module.plugin_manifest = define_plugin(name="new_style")
    module.__plugin_meta__ = {"name": "old"}
    manifest = resolve_manifest(module)
    assert isinstance(manifest, PluginManifest)
    assert manifest.name == "new_style"


def test_resolve_manifest_falls_back_to_legacy_meta():
    module = MagicMock()
    module.plugin_manifest = None
    module.__plugin_meta__ = {"name": "legacy"}
    assert resolve_manifest(module) == {"name": "legacy"}


def test_resolve_manifest_none_when_undeclared():
    module = MagicMock()
    module.plugin_manifest = None
    del module.__plugin_meta__
    assert resolve_manifest(module) is None


def test_is_contract_plugin():
    assert is_contract_plugin(MagicMock(plugin_manifest=define_plugin(name="a")))
    legacy = MagicMock(plugin_manifest=None, __plugin_meta__={"api_version": "1"})
    assert is_contract_plugin(legacy)
    old = MagicMock(plugin_manifest=None, __plugin_meta__={"name": "x"})
    assert not is_contract_plugin(old)


# ---------------------------------------------------------------- 边界检查器

def test_checker_flags_internal_imports():
    src = textwrap.dedent("""
        from neobot.plugin_api import command
        from neobot.core.managers.command_manager import matcher
        import neobot.adapters.mcc_adapter
        from neobot.models.message import MessageSegment
        from neobot.plugins.foo import bar
    """)
    violations = scan_plugin_imports(src)
    assert "neobot.core.managers.command_manager" in violations
    assert "neobot.adapters.mcc_adapter" in violations
    # 合法面不告警
    assert not any(v.startswith("neobot.plugin_api") for v in violations)
    assert not any(v.startswith("neobot.models") for v in violations)
    assert not any(v.startswith("neobot.plugins") for v in violations)


def test_checker_ignores_third_party():
    src = "import httpx\nfrom aiohttp import ClientSession\nfrom .relative import x\n"
    assert scan_plugin_imports(src) == []


def test_checker_handles_broken_source():
    assert scan_plugin_imports("def broken(:") == []


def test_checker_dedupes():
    src = (
        "import neobot.core.bot\n"
        "import neobot.core.bot\n"
        "from neobot.core import bot\n"
    )
    assert scan_plugin_imports(src) == ["neobot.core.bot", "neobot.core"]


def test_checker_exact_prefix_boundary():
    """兄弟命名空间(neobot.core_*)不被前缀匹配误伤。"""
    src = "import neobot.core_api\nimport neobot.core2\nimport neobot.adapters_x\n"
    assert scan_plugin_imports(src) == []


def test_checker_scans_package_submodules(tmp_path):
    """包式插件:__init__.py 干净但子模块违规 -> 递归扫描应命中。"""
    pkg = tmp_path / "pkg_plugin"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "from neobot.plugin_api import command\n", encoding="utf-8"
    )
    (pkg / "sub.py").write_text(
        "from neobot.core.managers.command_manager import matcher\n", encoding="utf-8"
    )
    # 更深一层 + 干扰项
    nested = pkg / "nested"
    nested.mkdir()
    (nested / "deep.py").write_text(
        "import neobot.adapters.mcc_adapter\n", encoding="utf-8"
    )
    (nested / "__pycache__").mkdir()

    violations = scan_module_file(str(pkg / "__init__.py"))
    assert "neobot.core.managers.command_manager" in violations
    assert "neobot.adapters.mcc_adapter" in violations


def test_checker_single_file_no_package_scan(tmp_path):
    """非包文件的扫描不递归(单文件语义保持)。"""
    f = tmp_path / "single.py"
    f.write_text("import neobot.core.bot\n", encoding="utf-8")
    assert scan_module_file(str(f)) == ["neobot.core.bot"]


# ---------------------------------------------------------------- PluginManager 集成

class _FakeModule:
    """模拟插件模块:带 __file__ 指向真实临时文件。"""

    def __init__(self, file_path, plugin_manifest=None, plugin_meta=None):
        self.__file__ = file_path
        self.__name__ = "neobot.plugins.fake"
        if plugin_manifest is not None:
            self.plugin_manifest = plugin_manifest
        if plugin_meta is not None:
            self.__plugin_meta__ = plugin_meta


@pytest.fixture
def plugin_manager():
    cm = CommandManager(prefixes=("/",))
    manager = PluginManager(cm)
    manager.loaded_plugins.clear()
    manager._legacy_import_violations.clear()
    return manager


def test_contract_plugin_violation_rejected(tmp_path, plugin_manager):
    """新式契约插件直接 import 内部模块 -> 拒绝加载并卸载已注册处理器。"""
    src = textwrap.dedent("""
        from neobot.plugin_api import command, define_plugin
        from neobot.core.managers.command_manager import matcher

        plugin_manifest = define_plugin(name="bad_contract")

        @command("bad")
        async def bad(bot, event, args):
            pass
    """)
    f = tmp_path / "bad_contract.py"
    f.write_text(src, encoding="utf-8")

    module = _FakeModule(str(f), plugin_manifest=define_plugin(name="bad_contract"))
    with pytest.raises(PluginLoadError) as exc_info:
        plugin_manager._check_contract_boundary("neobot.plugins.bad_contract", module)
    assert "违反插件 API 契约" in str(exc_info.value)


def test_legacy_plugin_violation_warns_but_loads(tmp_path, plugin_manager):
    """旧式插件直接 import 内部模块 -> 记录聚合警告,不拒绝。"""
    src = "from neobot.core.managers.command_manager import matcher\n"
    f = tmp_path / "legacy.py"
    f.write_text(src, encoding="utf-8")

    module = _FakeModule(str(f), plugin_meta={"name": "legacy"})
    violations = plugin_manager._check_contract_boundary("neobot.plugins.legacy", module)

    assert "neobot.core.managers.command_manager" in violations
    assert plugin_manager._legacy_import_violations == [
        ("neobot.plugins.legacy", ["neobot.core.managers.command_manager"])
    ]


def test_clean_contract_plugin_no_violation(tmp_path, plugin_manager):
    """只 import 契约命名空间的插件无违规。"""
    src = textwrap.dedent("""
        from neobot.plugin_api import command, define_plugin

        plugin_manifest = define_plugin(name="clean")

        @command("clean")
        async def clean(bot, event, args):
            pass
    """)
    f = tmp_path / "clean.py"
    f.write_text(src, encoding="utf-8")

    module = _FakeModule(str(f), plugin_manifest=define_plugin(name="clean"))
    assert plugin_manager._check_contract_boundary("neobot.plugins.clean", module) == []
    assert plugin_manager._legacy_import_violations == []


def test_store_manifest_new_style(plugin_manager):
    module = MagicMock()
    module.plugin_manifest = define_plugin(name="p", description="d", usage="/p")
    module.__plugin_meta__ = None
    plugin_manager._store_manifest("neobot.plugins.p", module)
    stored = plugin_manager.command_manager.plugins["neobot.plugins.p"]
    assert stored["name"] == "p"
    assert stored["description"] == "d"
    assert stored["api_version"] == "1"


def test_store_manifest_legacy_dict_passthrough(plugin_manager):
    module = MagicMock()
    module.plugin_manifest = None
    module.__plugin_meta__ = {"name": "legacy"}
    plugin_manager._store_manifest("neobot.plugins.legacy", module)
    assert plugin_manager.command_manager.plugins["neobot.plugins.legacy"] == {"name": "legacy"}


def test_log_legacy_violations_aggregates(plugin_manager):
    plugin_manager._legacy_import_violations = [
        ("neobot.plugins.a", ["neobot.core.bot"]),
        ("neobot.plugins.b", ["neobot.core.config_loader"]),
    ]
    with patch.object(plugin_manager.logger, "warning") as mock_warn:
        plugin_manager._log_legacy_violations()
    msg = mock_warn.call_args[0][0]
    assert "2 个插件" in msg
    assert "neobot.plugins.a" in msg and "neobot.plugins.b" in msg
    # 输出后清空,避免重复告警
    assert plugin_manager._legacy_import_violations == []


def test_log_legacy_violations_silent_when_clean(plugin_manager):
    with patch.object(plugin_manager.logger, "warning") as mock_warn:
        plugin_manager._log_legacy_violations()
    mock_warn.assert_not_called()


def test_reload_contract_violation_cleans_state(tmp_path, plugin_manager):
    """契约插件重载被拒后:loaded_plugins 与 sys.modules 均无残留,保持'未加载'一致。"""
    import sys

    src = textwrap.dedent("""
        from neobot.plugin_api import command, define_plugin
        from neobot.core.managers.command_manager import matcher

        plugin_manifest = define_plugin(name="bad_reload")

        @command("bad")
        async def bad(bot, event, args):
            pass
    """)
    f = tmp_path / "bad_reload.py"
    f.write_text(src, encoding="utf-8")

    module = _FakeModule(str(f), plugin_manifest=define_plugin(name="bad_reload"))
    full_name = "neobot.plugins.bad_reload"

    # 模拟"已加载过"的残留状态
    plugin_manager.loaded_plugins.add(full_name)
    sys.modules[full_name] = module

    with patch("importlib.reload", return_value=module):
        plugin_manager.reload_plugin(full_name)

    assert full_name not in plugin_manager.loaded_plugins
    assert full_name not in sys.modules
    # 已注册的处理器也被卸载
    assert full_name not in plugin_manager.command_manager.plugins


def test_load_all_plugins_manifest_error_reported(plugin_manager):
    """define_plugin 校验失败 -> 错误信息直接指向 manifest 字段,而非'未知错误'。"""
    import importlib

    from neobot.plugin_api.manifest import PluginManifestError

    err = PluginManifestError("插件名不合法: '1bad_name' (需为 1-64 位字母/数字/下划线/连字符,以字母开头)")
    # 注意:patch 顺序敏感——Python 3.11+ 的 mock 用 pkgutil.resolve_name
    # 解析字符串 target,而 resolve_name 内部调用 importlib.import_module。
    # 因此 import_module 的 patch 必须放在 with 的**最后**一位
    # (__enter__ 从左到右),否则会污染后续字符串 patch 的 target 解析。
    with patch("pkgutil.iter_modules", return_value=[(None, "bad_manifest", False)]), \
         patch("os.path.exists", return_value=True), \
         patch.object(importlib, "import_module", side_effect=err), \
         patch.object(plugin_manager.logger, "exception") as mock_exc:
        plugin_manager.load_all_plugins()

    assert "neobot.plugins.bad_manifest" not in plugin_manager.loaded_plugins
    # 错误信息直接指向 manifest 字段,而非"未知错误"
    assert "插件清单声明不合法" in mock_exc.call_args[0][0]
