"""框架核心不得 import 产品插件（neobot.plugins.*）。

覆盖直接 import、函数内惰性 import，以及 import_module / __import__ 的字面量路径。
插件管理器按目录动态加载插件（f-string 拼模块名）不在此列。
"""
from __future__ import annotations

import os
from pathlib import Path

from neobot.plugin_api._checker import scan_framework_plugin_imports

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_DIRS = (
    ROOT / "src" / "neobot" / "core",
    ROOT / "src" / "neobot" / "adapters",
)
MAIN_PY = ROOT / "main.py"


def _iter_framework_sources():
    yield MAIN_PY
    for directory in FRAMEWORK_DIRS:
        for dirpath, dirnames, filenames in os.walk(directory):
            dirnames[:] = [name for name in dirnames if name != "__pycache__"]
            for filename in filenames:
                if filename.endswith(".py"):
                    yield Path(dirpath) / filename


class TestScanFrameworkPluginImports:
    def test_direct_and_lazy_import_flagged(self):
        source = (
            "import neobot.plugins.discord_cross\n"
            "def boot():\n"
            "    from neobot.plugins.wanfeng_review import start\n"
        )
        assert scan_framework_plugin_imports(source) == [
            "neobot.plugins.discord_cross",
            "neobot.plugins.wanfeng_review",
        ]

    def test_literal_import_module_and_dunder_import_flagged(self):
        source = (
            "import importlib\n"
            'importlib.import_module("neobot.plugins.discord_cross")\n'
            '__import__("neobot.plugins.wanfeng_members")\n'
        )
        assert scan_framework_plugin_imports(source) == [
            "neobot.plugins.discord_cross",
            "neobot.plugins.wanfeng_members",
        ]

    def test_dynamic_loader_and_docstring_not_flagged(self):
        source = (
            '"""插件位于 neobot.plugins 包。"""\n'
            "import importlib\n"
            'package_name = "neobot.plugins"\n'
            "full_name = f\"{package_name}.{module_name}\"\n"
            "importlib.import_module(full_name)\n"
            "from neobot.plugin_api import on_startup\n"
        )
        assert scan_framework_plugin_imports(source) == []

    def test_syntax_error_returns_empty(self):
        assert scan_framework_plugin_imports("def broken(:\n") == []


def test_core_adapters_and_main_do_not_import_plugins():
    """core/、adapters/ 与 main.py 不得依赖任何 neobot.plugins.* 模块。"""
    violations = []
    for path in _iter_framework_sources():
        source = path.read_text(encoding="utf-8")
        imported = scan_framework_plugin_imports(source)
        if imported:
            rel = path.relative_to(ROOT)
            violations.append(f"{rel}: {imported}")
    assert violations == []
