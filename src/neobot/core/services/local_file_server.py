# -*- coding: utf-8 -*-
"""
本地文件下载服务

该模块提供一个本地 HTTP 服务，用于下载远程文件到本地并提供本地访问。
主要解决 NapCat 等第三方服务无法直接访问某些远程资源（如 B 站防盗链）的问题。
"""

import asyncio
import tempfile
import secrets
import time
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urljoin
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
        logger.success(f"[LocalFileServer] 服务已启动: http://{self.host}:{self.port}")

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
    
    async def download_file(self, url: str, timeout: int = 60, headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        下载远程文件到本地
        
        Args:
            url (str): 远程文件 URL
            timeout (int): 下载超时时间（秒）
            headers (Optional[Dict[str, str]]): 请求头
            
        Returns:
            Optional[str]: 本地文件 ID，如果失败则返回 None
        """
        try:
            # SSRF 防护：仅允许 http/https 且拒绝内网/回环地址
            if not input_validator.validate_http_url(url):
                logger.warning(f"[LocalFileServer] 拒绝下载不安全的 URL: {url[:200]}")
                return None
            file_id = self._generate_file_id(url)
            file_path = self.download_dir / f"{file_id}"
            
            # 检查文件是否已存在（进程重启后 file_map 为空，仍需补写映射，否则 handle_download 会 404）
            if file_path.exists():
                self.file_map[file_id] = file_path
                logger.info(f"[LocalFileServer] 文件已存在: {file_id}")
                return file_id
            
            logger.info(f"[LocalFileServer] 开始下载: {url}")
            
            # 使用 aiohttp 下载文件；trust_env=True 让下载走系统代理环境变量
            # （neobot 服务通过 systemd 注入 http_proxy/https_proxy 指向 mihomo）
            async with aiohttp.ClientSession(trust_env=True) as session:
                response, error = await self._open_with_validation(session, url, timeout, headers)
                if response is None:
                    if error:
                        logger.error(f"[LocalFileServer] 下载失败: {error}")
                    return None

                async with response:
                    if response.status != 200:
                        logger.error(f"[LocalFileServer] 下载失败: HTTP {response.status}")
                        return None

                    # 先看 Content-Length，避免为一个超大文件白下载半天
                    content_length = response.headers.get("Content-Length", "")
                    if content_length.isdigit() and int(content_length) > MAX_DOWNLOAD_BYTES:
                        logger.warning(
                            f"[LocalFileServer] 拒绝下载超大文件: {content_length} 字节"
                            f"（上限 {MAX_DOWNLOAD_BYTES}）"
                        )
                        return None

                    # 读取并保存文件
                    written = 0
                    with open(file_path, 'wb') as f:
                        while True:
                            chunk = await response.content.read(8192)
                            if not chunk:
                                break
                            written += len(chunk)
                            # 有些服务端不返回 Content-Length，这里再按实际写入量兜底
                            if written > MAX_DOWNLOAD_BYTES:
                                raise ValueError(
                                    f"文件超过 {MAX_DOWNLOAD_BYTES} 字节上限，已中止下载"
                                )
                            f.write(chunk)
            
            self.file_map[file_id] = file_path
            logger.success(f"[LocalFileServer] 下载完成: {file_id} ({file_path.stat().st_size} bytes)")
            return file_id
            
        except Exception as e:
            logger.error(f"[LocalFileServer] 下载失败: {e}")
            # 清理写了一半的残文件，避免占盘
            try:
                if 'file_path' in locals() and file_path.exists():
                    file_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

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
                timeout=timeout,
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
        
        # 获取文件大小
        file_size = file_path.stat().st_size
        
        # 设置响应头
        headers = {
            'Content-Disposition': f'attachment; filename="{file_id}"',
            'Content-Length': str(file_size)
        }
        
        return web.FileResponse(file_path, headers=headers)
    
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
            _local_file_server = LocalFileServer(
                host=server_config.host,
                port=server_config.port,
                base_url=server_config.base_url
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


async def download_to_local(url: str, timeout: int = 60, headers: Optional[Dict[str, str]] = None) -> Optional[str]:
    """
    下载远程文件到本地并返回本地访问 URL
    
    Args:
        url (str): 远程文件 URL
        timeout (int): 下载超时时间（秒）
        headers (Optional[Dict[str, str]]): 请求头
        
    Returns:
        Optional[str]: 本地访问 URL，如果失败则返回 None
    """
    server = get_local_file_server()
    if not server:
        return None
    # 服务未启动（[local_file_server].enabled=false 时不会监听端口）时，
    # 返回的地址 NapCat 访问不到，直接返回 None 让调用方回退原始直链
    if server.site is None:
        logger.warning("[LocalFileServer] 服务未启动，跳过本地中转")
        return None
    
    file_id = await server.download_file(url, timeout, headers)
    if not file_id:
        return None
    
    # 给 NapCat 的访问地址使用可配置的 base_url：
    # - 默认 127.0.0.1（NapCat 为 host 网络时直达宿主机）
    # - NapCat 是独立容器时，需在 [local_file_server].base_url 配置宿主机可达地址
    return f"{server.base_url}/download?id={file_id}"
