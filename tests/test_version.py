# -*- coding: utf-8 -*-
"""版本查询插件的单元测试。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from neobot.plugins import version as vp


def _mock_response(data: dict, status: int = 200):
    """构造同时支持 async with 和 .json() 的 response 对象。"""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _patch_session(resp):
    """mock aiohttp.ClientSession：session.get() 返回支持 async with 的 response。"""

    def decorator(fn):
        def wrapper(*args, **kwargs):
            async def scenario():
                session = MagicMock()
                session.get.return_value = resp
                with patch.object(vp.aiohttp, "ClientSession") as mock_cls:
                    mock_cls.return_value.__aenter__ = AsyncMock(return_value=session)
                    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                    vp._remote_cache.clear()
                    return await fn(*args, **kwargs)

            return asyncio.run(scenario())

        return wrapper

    return decorator


def test_read_version_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "VERSION_FILE", str(tmp_path / "versions"))
    monkeypatch.setattr(vp, "_COMMIT_SHA_FILE", str(tmp_path / "commit-sha"))
    assert vp._read_version_file() == ""


def test_escape_reply():
    assert vp._escape_reply("feat(x): 新功能") == "feat(x): 新功能"
    assert vp._escape_reply("a`b`c") == "a\\`b\\`c"
    assert vp._escape_reply("第一行\n第二行\r换行") == "第一行 第二行 换行"
    assert vp._escape_reply("") == ""
    assert vp._escape_reply(None) is None


def test_read_version_file_content(tmp_path, monkeypatch):
    f = tmp_path / "versions"
    f.write_text("abc123\n")
    monkeypatch.setattr(vp, "VERSION_FILE", str(f))
    monkeypatch.setattr(vp, "_COMMIT_SHA_FILE", str(tmp_path / "commit-sha"))
    assert vp._read_version_file() == "abc123"


@_patch_session(_mock_response({
    "sha": "deadbeef",
    "commit": {
        "message": "feat(x): 新功能\n\n详细说明第二行",
        "author": {"name": "测试作者", "email": "t@example.com"},
    },
    "author": {"login": "tester"},
}))
async def test_remote_commit_parse():
    """_get_remote_commit 解析 GitHub API 响应（mock 网络层）。"""
    info = await vp._get_remote_commit()

    assert info["sha"] == "deadbeef"
    # message 只取第一行
    assert info["message"] == "feat(x): 新功能"
    # author 优先 commit.author.name
    assert info["author"] == "测试作者"


@_patch_session(_mock_response({
    "sha": "abcd1234",
    "commit": {"message": "docs: 更新", "author": {"name": None}},
    "author": {"login": "fallback_user"},
}))
async def test_remote_commit_author_fallback():
    """author 缺失 commit.author.name 时回退 author.login。"""
    info = await vp._get_remote_commit()
    assert info["author"] == "fallback_user"


@_patch_session(_mock_response({}, status=403))
async def test_remote_commit_failure():
    """API 失败返回空 dict。"""
    info = await vp._get_remote_commit()
    assert info == {}


# ── DeepSeek AI 概述（2026-08 新增） ──────────────────────────────


def _fake_translation_config(**overrides):
    """构造带 translation 配置的全局配置替身（缺省为未配置占位 key）。"""
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        cross_platform=SimpleNamespace(
            translation=SimpleNamespace(
                api_key="your-deepseek-api-key-here",
                api_url="",
                model="deepseek-chat",
            )
        )
    )
    for k, v in overrides.items():
        setattr(cfg.cross_platform.translation, k, v)
    return cfg


async def test_ai_summary_none_when_unconfigured(monkeypatch):
    """未配置 DeepSeek（占位 key/空 URL）时返回 None（静默跳过）。"""
    monkeypatch.setattr(vp, "global_config", _fake_translation_config())
    vp._AI_SUMMARY_CACHE.clear()

    summary = await vp._get_ai_summary("deadbeef", "feat(x): 新功能", "测试作者")
    assert summary is None


async def test_ai_summary_none_when_empty_sha(monkeypatch):
    """sha 为空时不调用 API。"""
    monkeypatch.setattr(vp, "global_config", _fake_translation_config(
        api_key="sk-test", api_url="https://api.deepseek.com/v1/chat/completions",
    ))
    vp._AI_SUMMARY_CACHE.clear()

    summary = await vp._get_ai_summary("", "feat(x): 新功能")
    assert summary is None


async def test_ai_summary_success_and_cache(monkeypatch):
    """配置齐全时调用 DeepSeek 返回中文概述，并按 sha 缓存（二次调用不重复请求）。"""
    monkeypatch.setattr(vp, "global_config", _fake_translation_config(
        api_key="sk-test", api_url="https://api.deepseek.com/v1/chat/completions",
    ))
    vp._AI_SUMMARY_CACHE.clear()

    calls = {"n": 0}

    class FakeMessage:
        content = "给推特视频加水印和指纹处理，防止发不出来"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(*a, **kw):
                    calls["n"] += 1
                    return FakeResponse()

    import sys
    fake_openai = type(sys)("fake_openai")
    fake_openai.AsyncOpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    summary1 = await vp._get_ai_summary("deadbeef", "feat(x): 新功能", "测试作者")
    assert summary1 == "给推特视频加水印和指纹处理，防止发不出来"
    # 二次调用走缓存，不再请求
    summary2 = await vp._get_ai_summary("deadbeef", "feat(x): 新功能", "测试作者")
    assert summary2 == summary1
    assert calls["n"] == 1


async def test_ai_summary_none_on_api_failure(monkeypatch):
    """DeepSeek 调用抛异常时返回 None（不影响 /ver 主功能）。"""
    monkeypatch.setattr(vp, "global_config", _fake_translation_config(
        api_key="sk-test", api_url="https://api.deepseek.com/v1/chat/completions",
    ))
    vp._AI_SUMMARY_CACHE.clear()

    import sys

    class BoomClient:
        def __init__(self, *a, **kw):
            pass

        class completions:
            @staticmethod
            async def create(*a, **kw):
                raise RuntimeError("API down")

    fake_openai = type(sys)("fake_openai")
    fake_openai.AsyncOpenAI = BoomClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    summary = await vp._get_ai_summary("deadbeef", "feat(x): 新功能")
    assert summary is None


async def test_ver_reply_includes_ai_summary(monkeypatch):
    """/ver 回复包含 AI 概述行；概述失败时无该行。"""
    monkeypatch.setattr(vp, "global_config", _fake_translation_config(
        api_key="sk-test", api_url="https://api.deepseek.com/v1/chat/completions",
    ))
    vp._AI_SUMMARY_CACHE.clear()
    vp._remote_cache.clear()

    # 远程 commit（mock aiohttp 响应）
    resp = _mock_response({
        "sha": "deadbeef",
        "commit": {
            "message": "feat(x): 新功能",
            "author": {"name": "测试作者"},
        },
        "author": {"login": "tester"},
    })

    # AI 概述直接返回固定值
    async def fake_summary(sha, message, author=""):
        return "给视频加水印，防止发不出来"

    monkeypatch.setattr(vp, "_get_ai_summary", fake_summary)

    captured = {}

    class FakeBot:
        pass

    class FakeEvent:
        bot = FakeBot()

        async def reply(self, text):
            captured["text"] = text

    from neobot.plugins import version as vp_mod

    session = MagicMock()
    session.get.return_value = resp
    with patch.object(vp_mod.aiohttp, "ClientSession") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await vp_mod.handle_ver(FakeBot(), FakeEvent(), [])

    assert "🤖 更新概述：给视频加水印，防止发不出来" in captured["text"]

    # 概述失败时不出现该行
    async def fake_summary_none(sha, message, author=""):
        return None

    monkeypatch.setattr(vp, "_get_ai_summary", fake_summary_none)
    vp._remote_cache.clear()
    with patch.object(vp_mod.aiohttp, "ClientSession") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await vp_mod.handle_ver(FakeBot(), FakeEvent(), [])

    assert "更新概述" not in captured["text"]
