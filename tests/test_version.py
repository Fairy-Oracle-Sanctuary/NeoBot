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
