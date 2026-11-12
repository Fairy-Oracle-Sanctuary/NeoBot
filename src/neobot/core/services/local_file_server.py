# -*- coding: utf-8 -*-
"""
本地文件下载服务

该模块提供一个本地 HTTP 服务，用于下载远程文件到本地并提供本地访问。
主要解决 NapCat 等第三方服务无法直接访问某些远程资源（如 B 站防盗链）的问题。
"""

import asyncio
import base64
import shutil
import socket
import struct
import tempfile
import secrets
import time
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urljoin, urlparse, parse_qs
import aiohttp
from aiohttp import web

from neobot.core.utils.logger import logger
from neobot.core.config_loader import global_config
from neobot.core.utils.input_validator import input_validator

# 下载文件保留时长：超过后由定时任务删除，防止 /tmp 磁盘被媒体文件占满
FILE_MAX_AGE_SECONDS = 24 * 3600  # 24 小时
# 定时清理间隔
CLEANUP_INTERVAL_SECONDS = 3600  # 每小时
# 单文件下载大小上限：防止一个超大链接把磁盘写满
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200 MB
# 允许的最大重定向跳数（每一跳都会重新做 SSRF 校验）
MAX_REDIRECTS = 3
# 小图直接塞进消息（base64://），避免 NapCat 容器再来拉本机 HTTP
BASE64_IMAGE_MAX_BYTES = 1536 * 1024  # 1.5 MiB

_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
}
_KNOWN_SUFFIXES = set(_CONTENT_TYPE_SUFFIX.values()) | {".m4s", ".jpeg"}


def client_timeout(seconds: float) -> aiohttp.ClientTimeout:
    """aiohttp 3.12+ 拒绝把 int/float 直接传给 timeout。"""
    return aiohttp.ClientTimeout(total=max(float(seconds), 1.0))


def docker_bridge_ipv4() -> Optional[str]:
    """
    宿主机 docker0 地址。

    NeoBot 使用 host 网络时，这个地址就是独立容器（例如 wb-napcat）访问宿主机端口的网关。
    """
    return _iface_ipv4("docker0")


def _iface_ipv4(name: str) -> Optional[str]:
    try:
        import fcntl
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = fcntl.ioctl(
                sock.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack("256s", name.encode("utf-8")[:15]),
            )
            return socket.inet_ntoa(packed[20:24])
        finally:
            sock.close()
    except OSError:
        return None


def resolve_public_base_url(configured: str, port: int, bind_host: str) -> str:
    """
    NapCat 用来拉取本服务文件的根地址。

    显式配置优先。留空时：若进程绑在非回环地址且能看到 docker0，
    用桥地址（独立容器访问得到）；否则退回 127.0.0.1（NapCat 与本进程同一网络命名空间）。
    """
    configured = (configured or "").strip().rstrip("/")
    if configured:
        return configured
    loopback_bind = bind_host in ("127.0.0.1", "localhost", "::1")
    if not loopback_bind:
        bridge = docker_bridge_ipv4()
        if bridge:
            return f"http://{bridge}:{port}"
    return f"http://127.0.0.1:{port}"


def _suffix_for(content_type: str, url: str) -> str:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype in _CONTENT_TYPE_SUFFIX:
        return _CONTENT_TYPE_SUFFIX[ctype]
    path = urlparse(url).path if url else ""
    ext = Path(path).suffix.lower()
    if ext == ".jpeg":
        return ".jpg"
    if ext in _KNOWN_SUFFIXES:
        return ext
    return ""


class LocalFileServer:
    """
    本地文件下载服务
    
    提供一个本地 HTTP 服务，用于下载远程文件到本地并提供本地访问。
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 3003, base_url: str = ""):
        """
        初始化本地文件下载服务
        
        Args:
            host (str): 服务监听地址，默认仅本机可访问（供同机 NapCat 使用）；
                        如需跨主机访问请显式配置为 0.0.0.0 并自行做好网络层防护
            port (int): 服务监听端口
            base_url (str): 外部服务（如 NapCat）访问本服务的地址，默认 http://127.0.0.1:{port}；
                            当 NapCat 为独立容器时，需配置为宿主机可达地址（如 http://<宿主机IP>:3003）
        """
        self.host = host
        self.port = port
        self.base_url = (base_url or f"http://127.0.0.1:{port}").rstrip("/")
        self.app = web.Application()
        self.runner = None
        self.site = None
        self.download_dir = Path(tempfile.gettempdir()) / "neobot_downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # 注册路由
        self.app.router.add_get('/download', self.handle_download)
        self.app.router.add_get('/health', self.handle_health)
        
        # 文件映射表：file_id -> file_path
        self.file_map: Dict[str, Path] = {}
        # file_id -> {content_type, filename}，给 NapCat 正确的类型，避免被当成未知二进制拒绝
        self._meta: Dict[str, Dict[str, str]] = {}
        # URL -> file_id，用于同一 URL 重复下载时复用同一个文件
        self._url_to_id: Dict[str, str] = {}

        # 定时清理过期下载文件的后台任务
        self._cleanup_task: Optional[asyncio.Task] = None

        logger.success(f"[LocalFileServer] 初始化完成: {self.host}:{self.port}")
    
    async def start(self):
        """启动服务"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        # 启动定时清理过期下载文件的任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.success(
            f"[LocalFileServer] 服务已启动: http://{self.host}:{self.port}，"
            f"对外地址 {self.base_url}"
        )
        if self.host in ("127.0.0.1", "localhost", "::1"):
            logger.warning(
                "[LocalFileServer] 只监听回环地址。NapCat 若在独立容器 wb-napcat 中，"
                "访问不到 127.0.0.1。请把 host 设为 0.0.0.0。"
            )
        if "127.0.0.1" in self.base_url or "localhost" in self.base_url:
            if docker_bridge_ipv4() and self.host not in ("127.0.0.1", "localhost", "::1"):
                logger.warning(
                    "[LocalFileServer] base_url 指向本机回环，独立容器里的 NapCat 拉取会失败。"
                    "请把 base_url 留空（自动用 docker0）或写成 NapCat 容器能访问的地址。"
                )

    async def stop(self):
        """停止服务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        if self.runner:
            await self.runner.cleanup()
            logger.info("[LocalFileServer] 服务已停止")
    
    async def _cleanup_loop(self):
        """定时清理过期下载文件的后台循环"""
        try:
            while True:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                try:
                    self._cleanup_old_files()
                except Exception as e:
                    logger.error(f"[LocalFileServer] 清理过期文件失败: {e}")
        except asyncio.CancelledError:
            pass

    def _cleanup_old_files(self):
        """删除超过保留时长的下载文件，并同步清理 file_map（防止内存与磁盘无限增长）"""
        if not self.download_dir.exists():
            return

        now = time.time()
        removed = 0

        # 清理 file_map 中指向过期文件的映射
        for file_id in list(self.file_map.keys()):
            file_path = self.file_map[file_id]
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = 0
            if now - mtime > FILE_MAX_AGE_SECONDS:
                try:
                    file_path.unlink(missing_ok=True)
                except OSError as e:
                    logger.warning(f"[LocalFileServer] 删除过期文件失败 {file_path}: {e}")
                del self.file_map[file_id]
                self._meta.pop(file_id, None)
                removed += 1

        # 清理 download_dir 中未被 file_map 记录的孤儿文件（如下载后进程未写入映射即崩溃）
        for file_path in self.download_dir.iterdir():
            if not file_path.is_file():
                continue
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                continue
            if now - mtime > FILE_MAX_AGE_SECONDS:
                try:
                    file_path.unlink(missing_ok=True)
                except OSError as e:
                    logger.warning(f"[LocalFileServer] 删除孤儿文件失败 {file_path}: {e}")
                removed += 1

        # 清理已失效的 URL -> file_id 映射，避免长期运行后无限增长
        for cached_url, cached_id in list(self._url_to_id.items()):
            if cached_id not in self.file_map:
                del self._url_to_id[cached_url]

        if removed:
            logger.info(f"[LocalFileServer] 已清理 {removed} 个过期下载文件")

    def _generate_file_id(self, url: str) -> str:
        """
        生成文件 ID。

        同一 URL 复用同一个 ID（便于去重）；不同 URL 使用不可预测的随机 ID，
        避免通过 md5(url) 猜出他人文件的下载地址。
        """
        cached_id = self._url_to_id.get(url)
        if cached_id:
            return cached_id

        file_id = f"file_{secrets.token_urlsafe(16)}"
        self._url_to_id[url] = file_id
        return file_id

    def public_url(self, file_id: str) -> str:
        return f"{self.base_url}/download?id={file_id}"

    def _our_netlocs(self) -> set:
        base = urlparse(self.base_url)
        netlocs = {base.netloc, f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if self.port in (80, 443):
            netlocs.add("127.0.0.1")
            netlocs.add("localhost")
        return netlocs

    def file_id_from_url(self, url: str) -> Optional[str]:
        """若 url 指向本服务的 /download，返回 file id。"""
        if not isinstance(url, str) or "/download" not in url:
            return None
        parsed = urlparse(url)
        if parsed.path.rstrip("/") != "/download":
            return None
        if parsed.netloc not in self._our_netlocs():
            return None
        file_id = (parse_qs(parsed.query).get("id") or [None])[0]
        if file_id and file_id in self.file_map:
            return file_id
        return None

    def rewrite_loopback_url(self, url: str) -> str:
        """把指向本端口回环的下载地址改写成 NapCat 能访问的 base_url。"""
        if not isinstance(url, str):
            return url
        parsed = urlparse(url)
        if parsed.path.rstrip("/") != "/download":
            return url
        loopbacks = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if parsed.netloc not in loopbacks:
            return url
        if urlparse(self.base_url).netloc == parsed.netloc:
            return url
        file_id = (parse_qs(parsed.query).get("id") or [None])[0]
        if not file_id:
            return url
        return self.public_url(file_id)

    def publish_local_file(
        self,
        src: Path,
        content_type: str = "video/mp4",
        filename: str = "video.mp4",
    ) -> Optional[str]:
        """把已经落在磁盘上的文件登记进下载服务，返回 NapCat 可访问的 URL。"""
        if self.site is None:
            return None
        src = Path(src)
        if not src.is_file() or src.stat().st_size == 0:
            return None
        file_id = self._generate_file_id(f"file://{src.resolve()}")
        suffix = _suffix_for(content_type, filename)
        dest = self.download_dir / f"{file_id}{suffix}"
        shutil.copy2(src, dest)
        self.file_map[file_id] = dest
        self._meta[file_id] = {"content_type": content_type, "filename": filename}
        return self.public_url(file_id)

    async def download_file(
        self,
        url: str,
        timeout: int = 60,
        headers: Optional[Dict[str, str]] = None,
        trust_env: bool = True,
    ) -> Optional[str]:
        """
        下载远程文件到本地。

        Args:
            url: 远程文件 URL
            timeout: 下载超时时间（秒）
            headers: 请求头（B 站等防盗链需要 Referer）
            trust_env: 是否走系统代理。部分 CDN 对代理 IP 返回 403，失败后会再直连一次。

        Returns:
            本地文件 ID，失败则返回 None
        """
        if not input_validator.validate_http_url(url):
            logger.warning(f"[LocalFileServer] 拒绝下载不安全的 URL: {url[:200]}")
            return None

        file_id, status = await self._download_once(url, timeout, headers, trust_env)
        if file_id:
            return file_id
        # 代理出口被图床/B 站 CDN 拒绝时，直连再试一次。已经是直连就不再重试。
        if status in (403, 412) and trust_env:
            logger.info(f"[LocalFileServer] 下载被拒绝 HTTP {status}，改为不走代理直连重试")
            file_id, _status = await self._download_once(url, timeout, headers, trust_env=False)
            return file_id
        return None

    async def _download_once(
        self,
        url: str,
        timeout: int,
        headers: Optional[Dict[str, str]],
        trust_env: bool,
    ) -> Tuple[Optional[str], Optional[int]]:
        """返回 (file_id, http_status)。成功时 status 为 200。"""
        file_id = self._generate_file_id(url)
        file_path: Optional[Path] = None
        try:
            cached = self.file_map.get(file_id)
            if cached is not None and cached.exists():
                logger.info(f"[LocalFileServer] 文件已存在: {file_id}")
                return file_id, 200

            logger.info(f"[LocalFileServer] 开始下载: {url[:200]}")
            async with aiohttp.ClientSession(trust_env=trust_env) as session:
                response, error = await self._open_with_validation(session, url, timeout, headers)
                if response is None:
                    if error:
                        logger.error(f"[LocalFileServer] 下载失败: {error}")
                    return None, None

                async with response:
                    if response.status != 200:
                        host = urlparse(str(response.url)).netloc
                        logger.error(f"[LocalFileServer] 下载失败: HTTP {response.status} host={host}")
                        return None, response.status

                    content_type = response.headers.get("Content-Type", "")
                    content_length = response.headers.get("Content-Length", "")
                    if content_length.isdigit() and int(content_length) > MAX_DOWNLOAD_BYTES:
                        logger.warning(
                            f"[LocalFileServer] 拒绝下载超大文件: {content_length} 字节"
                            f"（上限 {MAX_DOWNLOAD_BYTES}）"
                        )
                        return None, response.status

                    suffix = _suffix_for(content_type, url)
                    file_path = self.download_dir / f"{file_id}{suffix}"
                    written = 0
                    with open(file_path, "wb") as f:
                        while True:
                            chunk = await response.content.read(8192)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > MAX_DOWNLOAD_BYTES:
                                raise ValueError(
                                    f"文件超过 {MAX_DOWNLOAD_BYTES} 字节上限，已中止下载"
                                )
                            f.write(chunk)

            ctype = (content_type or "application/octet-stream").split(";", 1)[0].strip()
            filename = f"media{suffix or ''}"
            self.file_map[file_id] = file_path
            self._meta[file_id] = {"content_type": ctype or "application/octet-stream", "filename": filename}
            logger.success(f"[LocalFileServer] 下载完成: {file_id} ({file_path.stat().st_size} bytes)")
            return file_id, 200
        except Exception as e:
            logger.error(f"[LocalFileServer] 下载失败: {e}")
            try:
                if file_path is not None and file_path.exists():
                    file_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None, None

    async def _open_with_validation(
        self,
        session: aiohttp.ClientSession,
        url: str,
        timeout: int,
        headers: Optional[Dict[str, str]],
    ):
        """
        手动跟随重定向，并对每一跳重新做 SSRF 校验。

        aiohttp 默认会自动跟随 302，若只校验初始 URL，攻击者用一个公网地址
        302 跳到 http://127.0.0.1:xxxx 即可绕过校验。

        Returns:
            (response, error_message)：成功时 response 为未关闭的响应对象；
            失败时 response 为 None，error_message 说明原因。
        """
        current_url = url
        for _ in range(MAX_REDIRECTS + 1):
            response = await session.get(
                current_url,
                timeout=client_timeout(timeout),
                headers=headers,
                allow_redirects=False,
            )
            if response.status not in (301, 302, 303, 307, 308):
                return response, None

            location = response.headers.get("Location")
            response.release()
            if not location:
                return None, "重定向响应缺少 Location"

            next_url = urljoin(current_url, location)
            if not input_validator.validate_http_url(next_url):
                logger.warning(f"[LocalFileServer] 拒绝重定向到不安全地址: {next_url[:200]}")
                return None, "重定向目标不安全"
            current_url = next_url

        return None, f"重定向次数超过上限 {MAX_REDIRECTS}"
    
    async def handle_download(self, request: web.Request) -> web.Response:
        """处理文件下载请求"""
        file_id = request.query.get('id')
        
        if not file_id or file_id not in self.file_map:
            return web.Response(
                status=404,
                text='File not found',
                content_type='text/plain'
            )
        
        file_path = self.file_map[file_id]
        
        if not file_path.exists():
            return web.Response(
                status=404,
                text='File not found',
                content_type='text/plain'
            )
        
        meta = self._meta.get(file_id, {})
        filename = meta.get("filename") or file_path.name
        content_type = meta.get("content_type") or "application/octet-stream"
        # NapCat 只做 GET，不能带自定义鉴权头。文件 ID 不可猜测，因此这里不要求 token，
        # 否则容器来拉文件会得到 403，合并转发随之失败。
        headers = {
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(file_path.stat().st_size),
            "Cache-Control": "private, max-age=3600",
        }
        response = web.FileResponse(file_path, headers=headers)
        response.content_type = content_type
        return response
    
    async def handle_health(self, request: web.Request) -> web.Response:
        """健康检查"""
        return web.json_response({
            'status': 'ok',
            'service': 'LocalFileServer',
            'download_dir': str(self.download_dir),
            'files_count': len(self.file_map)
        })


# 全局实例
_local_file_server: Optional[LocalFileServer] = None


def get_local_file_server() -> Optional[LocalFileServer]:
    """获取全局本地文件服务器实例"""
    global _local_file_server
    
    if _local_file_server is None:
        try:
            server_config = global_config.local_file_server
            public_base = resolve_public_base_url(
                server_config.base_url,
                server_config.port,
                server_config.host,
            )
            _local_file_server = LocalFileServer(
                host=server_config.host,
                port=server_config.port,
                base_url=public_base,
            )
        except Exception as e:
            logger.error(f"[LocalFileServer] 初始化失败: {e}")
            return None
    
    return _local_file_server


async def start_local_file_server():
    """启动全局本地文件服务器"""
    server = get_local_file_server()
    if server:
        await server.start()


async def stop_local_file_server():
    """停止全局本地文件服务器"""
    global _local_file_server
    if _local_file_server:
        await _local_file_server.stop()
        _local_file_server = None


async def download_to_local(
    url: str,
    timeout: int = 60,
    headers: Optional[Dict[str, str]] = None,
    trust_env: bool = True,
) -> Optional[str]:
    """
    下载远程文件到本地并返回本地访问 URL
    
    Args:
        url (str): 远程文件 URL
        timeout (int): 下载超时时间（秒）
        headers: 请求头
        trust_env: 是否走系统代理。B 站 CDN 对代理常返回 403，调用方可传 False。

    Returns:
        本地访问 URL，如果失败则返回 None
    """
    server = get_local_file_server()
    if not server:
        return None
    # 服务未启动（[local_file_server].enabled=false 时不会监听端口）时，
    # 返回的地址 NapCat 访问不到，直接返回 None 让调用方回退原始直链
    if server.site is None:
        logger.warning("[LocalFileServer] 服务未启动，跳过本地中转")
        return None
    
    file_id = await server.download_file(url, timeout, headers, trust_env=trust_env)
    if not file_id:
        return None

    return server.public_url(file_id)


def prepare_forward_nodes(nodes: Optional[List[Any]]) -> List[Any]:
    """
    发送合并转发前整理媒体：

    - 本服务上的小图改成 base64://，NapCat 不用再跨容器来拉
    - 较大的视频仍用 HTTP，但地址换成 NapCat 容器能够访问的 base_url
      （不要留 127.0.0.1，那是 NapCat 容器自己的回环）
    """
    if not nodes:
        return []
    server = get_local_file_server()
    if server is None:
        return nodes
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        content = data.get("content")
        if isinstance(content, list):
            for seg in content:
                _prepare_segment(server, seg)
    return nodes


def _prepare_segment(server: "LocalFileServer", seg: Any) -> None:
    if not isinstance(seg, dict):
        return
    if seg.get("type") not in ("image", "video", "record", "file"):
        return
    payload = seg.get("data")
    if not isinstance(payload, dict):
        return
    file_val = payload.get("file")
    if not isinstance(file_val, str) or not file_val:
        return
    file_id = server.file_id_from_url(file_val)
    if not file_id:
        rewritten = server.rewrite_loopback_url(file_val)
        if rewritten != file_val:
            payload["file"] = rewritten
        return
    path = server.file_map.get(file_id)
    if path is None or not path.exists():
        payload["file"] = server.public_url(file_id)
        return
    if seg.get("type") == "image" and path.stat().st_size <= BASE64_IMAGE_MAX_BYTES:
        payload["file"] = "base64://" + base64.b64encode(path.read_bytes()).decode("ascii")
        return
    payload["file"] = server.public_url(file_id)
