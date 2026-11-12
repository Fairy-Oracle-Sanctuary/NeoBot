"""合并转发发送：避开 NapCat 的视频大小限制，失败时重试并逐条兜底。

生产日志（NapCat 4.18.42）里失败分两类：

- 视频超过 100 MiB（104,857,600 字节）时，Highway 直接拒绝
  「视频文件过大，请使用文件上传」，整条转发一起失败。
  50–80 MiB 的视频可以正常放进转发。
- 媒体其实已经上传成功，但发送 res_id 失败（retcode 1200），体积从几 MiB 到 30 MiB
  都有，没有更具体的原因。这种重试一次，还不行就把节点拆成普通消息。
"""
from __future__ import annotations

import asyncio
import copy
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neobot.core.utils.logger import logger

# NapCat Highway 拒绝超过 100 MiB 的转发视频。留出余量，95 MiB 以上就不放进转发。
NAPCAT_FORWARD_VIDEO_LIMIT = 100 * 1024 * 1024
FORWARD_VIDEO_SAFE_BYTES = 95 * 1024 * 1024
FORWARD_BATCH_SIZE = 4
FFMPEG_COMPRESS_TIMEOUT = 90
_MIN_VIDEO_BPS = 80_000
_AUDIO_BPS = 96_000

CompressFunc = Callable[[Path, Path, int], bool]


class ForwardNotDelivered(Exception):
    """合并转发和逐条发送都没有把内容送出去。"""


def format_mib(size: int) -> str:
    return f"{size / 1024 / 1024:.1f}MB"


def video_bitrate(duration: float, target_bytes: int, audio_bps: int = _AUDIO_BPS) -> Optional[int]:
    """按目标体积估算视频码率。塞不进下限时返回 None，调用方改走群文件。"""
    if duration <= 0.5 or target_bytes <= 0:
        return None
    video_bps = int((target_bytes * 8) / duration) - audio_bps
    if video_bps < _MIN_VIDEO_BPS:
        return None
    return video_bps


def build_compress_command(src: Path, dest: Path, duration: float, limit_bytes: int) -> Optional[List[str]]:
    """把视频压到 limit 以下。目标体积再留一成，避免压完仍贴着上限。"""
    target = max(int(limit_bytes * 0.9), 1)
    bitrate = video_bitrate(duration, target)
    if bitrate is None or shutil.which("ffmpeg") is None:
        return None
    buf = bitrate * 2
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(src),
        "-vf", "scale='min(1280,iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", str(bitrate), "-maxrate", str(bitrate), "-bufsize", str(buf),
        "-c:a", "aac", "-b:a", "96k",
        "-threads", "2",
        "-movflags", "+faststart",
        str(dest),
    ]


def probe_duration(path: Path, timeout: int = 15) -> Optional[float]:
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        duration = float((result.stdout or "").strip())
    except ValueError:
        return None
    if duration <= 0:
        return None
    return duration


def compress_video_under(src: Path, dest: Path, limit_bytes: int, timeout: int = FFMPEG_COMPRESS_TIMEOUT) -> bool:
    """有 ffmpeg 且能在限定时间内压到 limit 以下时返回 True。"""
    duration = probe_duration(src)
    if duration is None:
        return False
    cmd = build_compress_command(src, dest, duration, limit_bytes)
    if not cmd:
        return False
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(f"[Forward] 压缩视频未完成: {type(exc).__name__}")
        dest.unlink(missing_ok=True)
        return False
    if result.returncode != 0 or not dest.is_file():
        dest.unlink(missing_ok=True)
        return False
    try:
        size = dest.stat().st_size
    except OSError:
        return False
    if size <= 0 or size > limit_bytes:
        dest.unlink(missing_ok=True)
        return False
    return True


def _content_list(node: Any) -> Optional[List[Any]]:
    if not isinstance(node, dict):
        return None
    data = node.get("data")
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if isinstance(content, list):
        return content
    return None


def _is_video(seg: Any) -> bool:
    return isinstance(seg, dict) and seg.get("type") == "video"


def node_is_heavy(node: Any) -> bool:
    content = _content_list(node) or []
    return any(isinstance(seg, dict) and seg.get("type") in ("video", "record", "file") for seg in content)


def split_forward_batches(nodes: List[Any], batch_size: int = FORWARD_BATCH_SIZE) -> List[List[Any]]:
    """视频单独成批，其余节点按批切，避免一条大视频拖垮整条转发。"""
    batches: List[List[Any]] = []
    current: List[Any] = []
    size = max(int(batch_size), 1)
    for node in nodes or []:
        if node_is_heavy(node):
            if current:
                batches.append(current)
                current = []
            batches.append([node])
            continue
        current.append(node)
        if len(current) >= size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches


def resolve_local_media(server: Any, file_val: str) -> tuple[Optional[str], Optional[Path]]:
    """转发节点里的地址若指向本地下载文件，返回 (file_id, path)。"""
    if server is None or not isinstance(file_val, str) or not file_val:
        return None, None
    if file_val.startswith("file://"):
        from neobot.core.services.local_file_server import _is_under_download_dir, _path_from_file_url

        path = _path_from_file_url(file_val)
        if path is None or not _is_under_download_dir(server, path) or not path.is_file():
            return None, None
        file_id = None
        try:
            resolved = path.resolve()
        except OSError:
            return None, None
        for candidate, mapped in getattr(server, "file_map", {}).items():
            try:
                if Path(mapped).resolve() == resolved:
                    file_id = candidate
                    break
            except OSError:
                continue
        return file_id, path

    finder = getattr(server, "file_id_from_url", None)
    file_id = finder(file_val) if callable(finder) else None
    if not file_id:
        return None, None
    mapped = getattr(server, "file_map", {}).get(file_id)
    if mapped is None:
        return file_id, None
    path = Path(mapped)
    if not path.is_file():
        return file_id, None
    return file_id, path


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in (name or ""))
    cleaned = cleaned.strip(" ._") or "video.mp4"
    if not cleaned.lower().endswith(".mp4"):
        cleaned += ".mp4"
    return cleaned[:80]


def _filename_for(server: Any, file_id: Optional[str], path: Path) -> str:
    meta = {}
    if server is not None and file_id:
        meta = (getattr(server, "_meta", {}) or {}).get(file_id) or {}
    return _safe_filename(str(meta.get("filename") or path.name or "video.mp4"))


def _publish(server: Any, path: Path, filename: str) -> str:
    file_id = server._generate_file_id(f"file://{path.resolve()}")
    server.file_map[file_id] = path
    meta = getattr(server, "_meta", None)
    if isinstance(meta, dict):
        meta[file_id] = {"content_type": "video/mp4", "filename": filename}
    return server.public_url(file_id)


def detach_oversized_videos(
    nodes: List[Any],
    server: Any,
    *,
    limit_bytes: int = FORWARD_VIDEO_SAFE_BYTES,
    compress: Optional[CompressFunc] = None,
) -> List[Dict[str, Any]]:
    """
    超过 limit 的本地视频不要放进合并转发。

    能在限定时间内压到限制以下的，替换成压缩后的地址继续转发；
    压不了的从节点里拿掉，并返回待 upload_group_file 的清单。
    """
    uploads: List[Dict[str, Any]] = []
    if not nodes or server is None:
        return uploads
    compressor = compress if compress is not None else compress_video_under
    for node in nodes:
        content = _content_list(node)
        if content is None:
            continue
        kept: List[Any] = []
        changed = False
        for seg in content:
            if not _is_video(seg):
                kept.append(seg)
                continue
            payload = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            file_val = payload.get("file")
            file_id, path = resolve_local_media(server, file_val if isinstance(file_val, str) else "")
            if path is None:
                kept.append(seg)
                continue
            try:
                size = path.stat().st_size
            except OSError:
                kept.append(seg)
                continue
            if size <= limit_bytes:
                kept.append(seg)
                continue
            changed = True
            logger.info(
                f"[Forward] 视频 {format_mib(size)} 超过合并转发上限 "
                f"{format_mib(limit_bytes)}，不放入转发节点"
            )
            shrunk: Optional[Path] = None
            dest = Path(server.download_dir) / f"shrink_{secrets.token_hex(4)}.mp4"
            try:
                if compressor(path, dest, limit_bytes):
                    shrunk = dest
            except Exception as exc:
                logger.warning(f"[Forward] 压缩视频失败: {type(exc).__name__}: {exc}")
                shrunk = None
            if shrunk is not None and shrunk.is_file():
                try:
                    shrunk_size = shrunk.stat().st_size
                except OSError:
                    shrunk_size = limit_bytes + 1
                if 0 < shrunk_size <= limit_bytes:
                    name = _filename_for(server, file_id, path)
                    url = _publish(server, shrunk, name)
                    cloned = copy.deepcopy(seg)
                    cloned.setdefault("data", {})["file"] = url
                    kept.append(cloned)
                    logger.info(f"[Forward] 视频已压到 {format_mib(shrunk_size)}，继续放进合并转发")
                    continue
                shrunk.unlink(missing_ok=True)
            elif dest.exists():
                dest.unlink(missing_ok=True)
            name = _filename_for(server, file_id, path)
            url = file_val if isinstance(file_val, str) and file_val.startswith("http") else ""
            if not url and file_id:
                url = server.public_url(file_id)
            if url:
                uploads.append({"url": url, "name": name, "size": size})
        if changed:
            node_data = node.get("data")
            if isinstance(node_data, dict):
                if kept:
                    node_data["content"] = kept
                else:
                    node_data["content"] = [{
                        "type": "text",
                        "data": {"text": "视频有点大，不放进聊天记录啦。"},
                    }]
    return uploads


def strip_media(content: Any) -> Any:
    """去掉媒体段，只留文字。本来就没有媒体时返回 None。"""
    if not isinstance(content, list):
        return None
    kept = []
    dropped = 0
    for piece in content:
        if isinstance(piece, dict) and piece.get("type") in ("image", "video", "record", "file"):
            dropped += 1
            continue
        kept.append(piece)
    if dropped == 0:
        return None
    if not kept:
        kept = [{"type": "text", "data": {"text": "媒体没发出去，打开上面的链接看看吧。"}}]
    return kept


def _node_content(node: Any) -> Any:
    if not isinstance(node, dict):
        return None
    data = node.get("data")
    if not isinstance(data, dict):
        return None
    return data.get("content")


async def _send_forward(bot: Any, kind: str, target_id: int, nodes: List[Any]) -> None:
    if kind == "group":
        await bot.send_group_forward_msg(target_id, nodes)
    else:
        await bot.send_private_forward_msg(target_id, nodes)


async def _send_plain(bot: Any, kind: str, target_id: int, message: Any) -> bool:
    action = "send_group_msg" if kind == "group" else "send_private_msg"
    key = "group_id" if kind == "group" else "user_id"
    try:
        await bot.call_api(
            action,
            {key: target_id, "message": bot._process_message(message)},
            strict=True,
        )
        return True
    except Exception as exc:
        logger.warning(f"[Forward] 普通消息发送失败: {type(exc).__name__}: {exc}")
        return False


async def _send_node_plain(bot: Any, kind: str, target_id: int, node: Any) -> bool:
    content = _node_content(node)
    if content is None:
        return False
    if await _send_plain(bot, kind, target_id, content):
        return True
    text_only = strip_media(content)
    if text_only is None:
        return False
    return await _send_plain(bot, kind, target_id, text_only)


async def _try_forward_once(bot: Any, kind: str, target_id: int, nodes: List[Any]) -> bool:
    try:
        await _send_forward(bot, kind, target_id, nodes)
        return True
    except Exception as exc:
        logger.warning(f"[Forward] 合并转发失败: {type(exc).__name__}: {exc}")
        return False


async def deliver_forward(bot: Any, kind: str, target_id: int, nodes: List[Any]) -> None:
    """
    发送合并转发。

    超大视频先压缩或改走群文件；每一批失败后重试一次（小图会再尝试内联成 base64），
    仍失败则把节点逐条发出去，图片保留。一条都没送出时抛出 ForwardNotDelivered。
    """
    from neobot.core.services.local_file_server import get_local_file_server, prepare_forward_nodes

    try:
        nodes = prepare_forward_nodes(nodes)
    except Exception as exc:
        logger.warning(f"[Forward] 准备媒体失败，按原节点发送: {type(exc).__name__}: {exc}")
        nodes = list(nodes or [])

    server = None
    try:
        server = get_local_file_server()
    except Exception as exc:
        logger.warning(f"[Forward] 本地文件服务不可用: {type(exc).__name__}: {exc}")

    uploads: List[Dict[str, Any]] = []
    if server is not None and any(node_is_heavy(node) for node in nodes):
        try:
            uploads = await asyncio.to_thread(detach_oversized_videos, nodes, server)
        except Exception as exc:
            logger.warning(f"[Forward] 检查视频大小失败，按原节点发送: {type(exc).__name__}: {exc}")

    delivered = 0
    for batch in split_forward_batches(nodes):
        if await _try_forward_once(bot, kind, target_id, batch):
            delivered += 1
            continue
        retried = copy.deepcopy(batch)
        try:
            prepare_forward_nodes(retried)
        except Exception:
            retried = batch
        logger.info("[Forward] 合并转发重试一次")
        if await _try_forward_once(bot, kind, target_id, retried):
            delivered += 1
            continue
        logger.info("[Forward] 重试仍失败，改为逐条发送")
        for node in batch:
            if await _send_node_plain(bot, kind, target_id, node):
                delivered += 1

    for item in uploads:
        if await _upload_video(bot, kind, target_id, item):
            delivered += 1

    if delivered == 0 and nodes:
        raise ForwardNotDelivered("合并转发没有发出去")


async def _upload_video(bot: Any, kind: str, target_id: int, item: Dict[str, Any]) -> bool:
    action = "upload_group_file" if kind == "group" else "upload_private_file"
    key = "group_id" if kind == "group" else "user_id"
    where = "群文件" if kind == "group" else "文件"
    size_text = format_mib(int(item.get("size") or 0))
    name = item.get("name") or "video.mp4"
    try:
        await bot.call_api(
            action,
            {key: target_id, "file": item["url"], "name": name},
            strict=True,
        )
    except Exception as exc:
        logger.warning(f"[Forward] 群文件上传失败: {type(exc).__name__}: {exc}")
        return await _send_plain(
            bot,
            kind,
            target_id,
            f"这个视频有 {size_text}，聊天记录装不下，{where}也没传上去。",
        )
    await _send_plain(
        bot,
        kind,
        target_id,
        f"这个视频有 {size_text}，聊天记录装不下（上限 100MB）。我放到{where}里啦：{name}",
    )
    return True
