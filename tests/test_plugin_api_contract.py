"""
插件 API 契约兼容性测试套件。

覆盖三块契约基础设施，框架升级时自动验证它们没有悄悄变行为：
1. 边界检查器 (_checker): AST 扫描内部 import；
2. manifest (define_plugin / resolve_manifest / is_contract_plugin): 清单声明与校验；
3. PluginManager 集成: 契约插件违规 -> 拒绝加载，旧式插件违规 -> 聚合告警。

真实存量插件的契约合规性扫描也在这里做——保证仓库内 27 个插件
始终满足"不 import neobot.core.* / neobot.adapters.*"的契约承诺。
"""
from __future__ import annotations

import os

import pytest

from neobot.plugin_api._checker import (
    scan_module_file,
    scan_plugin_imports,
)
from neobot.plugin_api.manifest import (
    API_VERSION,
    PluginManifest,
    PluginManifestError,
    define_plugin,
    is_contract_plugin,
    resolve_manifest,
    to_stored_dict,
)

# ---------------------------------------------------------------------------
# 1. 边界检查器
# ---------------------------------------------------------------------------


class TestScanPluginImports:
    def test_plain_import_violation(self):
        src = "import neobot.core.managers.command_manager\n"
        assert scan_plugin_imports(src) == ["neobot.core.managers.command_manager"]

    def test_from_import_violation(self):
        src = "from neobot.adapters.onebot import Adapter\n"
        assert scan_plugin_imports(src) == ["neobot.adapters.onebot"]

    def test_plugin_api_allowed(self):
        src = (
            "from neobot.plugin_api import on_command\n"
            "import neobot.plugin_api.events\n"
            "from neobot.models import Message\n"
            "import neobot.plugins.echo\n"
        )
        assert scan_plugin_imports(src) == []

    def test_sibling_namespace_not_confused(self):
        # 精确边界: neobot.core_utils 不该被误伤为 neobot.core.*
        src = "import neobot.core_utils\nfrom neobot.adapters_extra import X\n"
        assert scan_plugin_imports(src) == []

    def test_dedup_preserve_order(self):
        # from-import 按语句的 module 记录("from neobot.core import ws" -> "neobot.core")
        src = (
            "import neobot.core.bot\n"
            "from neobot.core import ws\n"
            "import neobot.core.bot\n"
        )
        assert scan_plugin_imports(src) == ["neobot.core.bot", "neobot.core"]

    def test_syntax_error_returns_empty(self):
        assert scan_plugin_imports("def broken(:\n") == []

    def test_import_inside_function_also_caught(self):
        src = "def helper():\n    import neobot.core.permission\n"
        assert scan_plugin_imports(src) == ["neobot.core.permission"]


class TestScanModuleFile:
    def test_missing_file_returns_empty(self, tmp_path):
        assert scan_module_file(str(tmp_path / "nope.py")) == []

    def test_package_recursive_scan(self, tmp_path):
        # 包式插件: 子模块的违规 import 也要被抓到
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("x = 1\n", encoding="utf-8")
        (pkg / "sub.py").write_text(
            "import neobot.core.ws\n", encoding="utf-8"
        )
        violations = scan_module_file(str(pkg / "__init__.py"))
        assert violations == ["neobot.core.ws"]

    def test_package_skips_pycache(self, tmp_path):
        pkg = tmp_path / "mypkg"
        cache = pkg / "__pycache__"
        cache.mkdir(parents=True)
        (pkg / "__init__.py").write_text("x = 1\n", encoding="utf-8")
        (cache / "stale.py").write_text(
            "import neobot.core.bot\n", encoding="utf-8"
        )
        assert scan_module_file(str(pkg / "__init__.py")) == []


# ---------------------------------------------------------------------------
# 2. manifest
# ---------------------------------------------------------------------------


class TestDefinePlugin:
    def test_minimal_valid(self):
        m = define_plugin("echo")
        assert m.name == "echo"
        assert m.api_version == API_VERSION
        assert m.version == "0.1.0"

    def test_invalid_name_rejected(self):
        for bad in ("1abc", "有中文", "a" * 65, "", "a b"):
            with pytest.raises(PluginManifestError):
                define_plugin(bad)

    def test_invalid_version_rejected(self):
        for bad in ("1", "v1.0", "1.0", "1.0.0.0"):
            with pytest.raises(PluginManifestError):
                define_plugin("x", version=bad)

    def test_wrong_api_version_rejected(self):
        with pytest.raises(PluginManifestError):
            define_plugin("x", api_version="2")

    def test_dependencies_copied(self):
        m = define_plugin("x", dependencies=["a", "b"])
        m.dependencies.append("c")  # 不应影响后续调用
        assert define_plugin("y").dependencies == []


class TestResolveManifest:
    def test_new_style(self):
        class M:
            plugin_manifest = define_plugin("newstyle")

        resolved = resolve_manifest(M)
        assert isinstance(resolved, PluginManifest)
        assert resolved.name == "newstyle"

    def test_legacy_dict(self):
        class M:
            __plugin_meta__ = {"name": "legacy", "usage": "/x"}

        assert resolve_manifest(M) == {"name": "legacy", "usage": "/x"}

    def test_none_when_absent(self):
        class M:
            pass

        assert resolve_manifest(M) is None

    def test_is_contract_plugin(self):
        class New:
            plugin_manifest = define_plugin("n")

        class OldDict:
            __plugin_meta__ = {"name": "o", "api_version": "1"}

        class OldNoVersion:
            __plugin_meta__ = {"name": "o2"}

        assert is_contract_plugin(New) is True
        assert is_contract_plugin(OldDict) is True
        assert is_contract_plugin(OldNoVersion) is False

    def test_to_stored_dict_normalization(self):
        m = define_plugin("x", description="d")
        stored = to_stored_dict(m)
        assert stored["name"] == "x" and stored["description"] == "d"
        assert to_stored_dict(None) is None
        legacy = {"name": "y"}
        assert to_stored_dict(legacy) is legacy


# ---------------------------------------------------------------------------
# 3. 存量插件合规扫描(仓库内所有插件必须通过边界检查)
# ---------------------------------------------------------------------------

PLUGINS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "neobot", "plugins"
)


class TestExistingPluginsCompliance:
    """仓库内每个插件入口都不得 import neobot.core.* / neobot.adapters.*。"""

    def test_all_plugin_entries_clean(self):
        assert os.path.isdir(PLUGINS_DIR), "插件目录不存在"
        offenders = {}
        for name in sorted(os.listdir(PLUGINS_DIR)):
            path = os.path.join(PLUGINS_DIR, name)
            if name.startswith("_") or name == "__pycache__":
                continue
            if os.path.isdir(path):
                entry = os.path.join(path, "__init__.py")
                if not os.path.isfile(entry):
                    continue
            else:
                if not name.endswith(".py"):
                    continue
                entry = path
            violations = scan_module_file(entry)
            if violations:
                offenders[name] = violations
        assert not offenders, f"以下插件违反契约边界: {offenders}"
