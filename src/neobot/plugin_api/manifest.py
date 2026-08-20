"""
插件清单 (Plugin Manifest) —— 插件 API 契约的一部分。

插件通过模块级 ``plugin_manifest = define_plugin(...)`` 声明自身元信息,
取代旧的 ``__plugin_meta__`` 字典。两者目前同时被 ``PluginManager`` 支持,
新插件应统一使用本模块提供的 ``PluginManifest`` / ``define_plugin``。

声明 ``api_version`` 的插件被视为"新式契约插件":
- 只允许 import ``neobot.plugin_api`` 命名空间内的公开接口;
- 违反边界(import ``neobot.core.*`` / ``neobot.adapters.*``)会被拒绝加载。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Union

#: 当前契约版本(plugin-api-v1)。框架侧与插件侧不一致时由 PluginManager 决定兼容策略。
API_VERSION = "1"

_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class PluginManifestError(ValueError):
    """manifest 声明不合法。"""


@dataclass
class PluginManifest:
    """插件清单。字段对齐 ``docs/plugin-api.md`` 中定义的契约。"""

    #: 插件名(必填,用于 /help 与日志展示)
    name: str
    #: 一句话功能描述
    description: str = ""
    #: 用法说明(支持多行,出现在 /help 中)
    usage: str = ""
    #: 插件自身版本,遵循 semver
    version: str = "0.1.0"
    #: 作者标识(昵称 / QQ / GitHub 均可)
    author: str = ""
    #: 所依赖的插件 API 契约版本,如 "1"
    api_version: str = API_VERSION
    #: 依赖的其他插件名
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转为 dict,兼容旧版 ``__plugin_meta__`` 的消费方(如 /help)。"""
        return asdict(self)


def define_plugin(
    name: str,
    description: str = "",
    usage: str = "",
    version: str = "0.1.0",
    author: str = "",
    api_version: str = API_VERSION,
    dependencies: Optional[List[str]] = None,
) -> PluginManifest:
    """
    声明插件清单。对关键字段做合法性校验,尽早暴露拼写错误。

    :raises PluginManifestError: 字段不合法时
    """
    if not _NAME_RE.match(name):
        raise PluginManifestError(
            f"插件名不合法: {name!r} (需为 1-64 位字母/数字/下划线/连字符,以字母开头)"
        )
    if not _VERSION_RE.match(version):
        raise PluginManifestError(
            f"插件版本不合法: {version!r} (需为 semver 格式,如 0.1.0)"
        )
    if api_version != API_VERSION:
        raise PluginManifestError(
            f"不支持的插件 API 契约版本: {api_version!r} (当前框架支持 {API_VERSION!r})"
        )
    return PluginManifest(
        name=name,
        description=description,
        usage=usage,
        version=version,
        author=author,
        api_version=api_version,
        dependencies=list(dependencies or []),
    )


def resolve_manifest(module: Any) -> Optional[Union[PluginManifest, Dict[str, Any]]]:
    """
    从已加载的插件模块中解析清单,兼容新旧两种声明方式。

    优先识别 ``plugin_manifest``(PluginManifest 实例),其次回退到旧的
    ``__plugin_meta__`` 字典。

    :return: 新式插件返回 PluginManifest;旧式插件原样返回其 ``__plugin_meta__``
        字典(保持历史行为,存储与 /help 展示不感知差异);未声明返回 None。
    """
    manifest = getattr(module, "plugin_manifest", None)
    if isinstance(manifest, PluginManifest):
        return manifest

    meta = getattr(module, "__plugin_meta__", None)
    if isinstance(meta, dict):
        return meta
    return None


def is_contract_plugin(module: Any) -> bool:
    """
    判断插件是否为"新式契约插件"(声明了 api_version)。

    契约插件承诺遵守 ``neobot.plugin_api`` 边界,违规时加载器会拒绝加载。
    """
    manifest = getattr(module, "plugin_manifest", None)
    if isinstance(manifest, PluginManifest):
        return True
    meta = getattr(module, "__plugin_meta__", None)
    return bool(isinstance(meta, dict) and meta.get("api_version"))


def to_stored_dict(meta: Union[PluginManifest, Dict[str, Any], None]) -> Optional[Dict[str, Any]]:
    """把解析出的清单归一化为 dict,供 CommandManager.plugins 存储。"""
    if meta is None:
        return None
    if isinstance(meta, PluginManifest):
        return meta.to_dict()
    return meta
