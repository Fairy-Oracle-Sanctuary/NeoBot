"""
插件 import 边界检查器(内部工具,不属于公开契约)。

在插件加载前对其源码做 AST 扫描,找出直接 import 框架内部模块的语句。
内部模块指 ``neobot.core.*`` 与 ``neobot.adapters.*`` —— 它们不保证向后兼容,
插件只能使用 ``neobot.plugin_api`` 命名空间内的公开接口。

说明:
- ``neobot.plugin_api`` / ``neobot.plugins`` / ``neobot.models`` 的 import 不视为违规
  (models 为纯数据模型,属准公开面;插件间互相 import 同属插件生态)。
- 本检查器只负责"报告",是否拒绝加载由 PluginManager 按插件类型决定:
  新式契约插件(manifest 声明 api_version="1")违规 -> 拒绝加载;
  旧式插件违规 -> 仅聚合告警,保持兼容。
"""
from __future__ import annotations

import ast
from typing import List


def _is_internal(module: str) -> bool:
    """判断模块路径是否命中内部命名空间(精确边界,避免误伤 neobot.core_* 等兄弟命名空间)。"""
    return (
        module == "neobot.core"
        or module.startswith("neobot.core.")
        or module == "neobot.adapters"
        or module.startswith("neobot.adapters.")
    )


def scan_plugin_imports(source: str) -> List[str]:
    """
    AST 扫描插件源码,返回所有内部 import 的模块路径(去重、保序)。

    :param source: 插件源码文本。
    :return: 违规模块路径列表,如 ``["neobot.core.managers.command_manager"]``。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # 源码无法解析时不阻塞加载,返回空列表(加载阶段会另行报错)。
        return []

    violations: List[str] = []
    seen: set = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if _is_internal(mod) and mod not in seen:
                    seen.add(mod)
                    violations.append(mod)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod and _is_internal(mod) and mod not in seen:
                seen.add(mod)
                violations.append(mod)

    return violations


def _scan_package(path: str) -> List[str]:
    """
    包插件(__init__.py)的扫描路径:递归收集包内所有 .py(排除 __pycache__)。
    防止子模块直接 import 内部模块时通过主文件扫描漏报。
    """
    import os

    package_dir = os.path.dirname(path)
    files: List[str] = []
    for root, dirs, names in os.walk(package_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            if name.endswith(".py"):
                files.append(os.path.join(root, name))
    return files


def scan_module_file(path: str) -> List[str]:
    """
    从文件路径读取源码并扫描(去重、保序)。

    若 path 是包的 ``__init__.py``,会递归扫描整个包目录,
    覆盖包式插件子模块的违规 import。

    文件不存在或不可读时返回空列表(不阻塞加载)。
    """
    import os

    paths: List[str]
    if os.path.basename(path) == "__init__.py":
        paths = _scan_package(path)
    else:
        paths = [path]

    violations: List[str] = []
    seen: set = set()
    for p in paths:
        for mod in scan_module_file_single(p):
            if mod not in seen:
                seen.add(mod)
                violations.append(mod)
    return violations


def scan_module_file_single(path: str) -> List[str]:
    """扫描单个 .py 文件,不做包递归。文件不可读时返回空列表。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        return []
    return scan_plugin_imports(source)
