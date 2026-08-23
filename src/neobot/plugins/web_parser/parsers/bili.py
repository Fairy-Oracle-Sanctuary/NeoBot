# -*- coding: utf-8 -*-
import asyncio
import re
import os
import subprocess
import tempfile
from typing import Optional, Dict, Any, List, Union
from neobot.plugin_api import logger, input_validator, global_config, download_to_local, get_local_file_server
from neobot.models import MessageEvent, MessageSegment
from ..base import BaseParser
from ..utils import format_duration

from bilibili_api import video, select_client, Credential
from bilibili_api.exceptions import ResponseCodeException
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.warning("[B站解析器] aiohttp 未安装，音视频合并功能将不可用")

# bilibili_api-python 可用性标志
BILI_API_AVAILABLE = True

# ffmpeg 可用性标志
FFMPEG_AVAILABLE = False
try:
    subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    FFMPEG_AVAILABLE = True
    logger.success("[B站解析器] ffmpeg 已安装，支持合并音视频")
except (subprocess.CalledProcessError, FileNotFoundError):
    logger.warning("[B站解析器] ffmpeg 未安装，视频可能没有声音。建议安装 ffmpeg 以获得完整音视频体验")

# 显式指定使用 aiohttp，避免与其他库冲突
try:
    select_client("aiohttp")
except Exception as e:
    logger.warning(f"设置 bilibili_api 客户端失败: {e}")


class BiliParser(BaseParser):
    """
    B站视频解析器（使用 bilibili-api-python 库）
    """

    # 解析失败重试：最多尝试 3 次，全部失败才报错
    max_parse_attempts = 3
    
    def __init__(self):
        super().__init__()
        self.parser_name = "bili"
        self.name = "B站解析器"
        self.url_pattern = re.compile(r"https?://(?:www\.)?(bilibili\.com/video/\w+|b23\.tv/[a-zA-Z0-9]+)")
        self.nickname = "B站视频解析"
        

    
    def _get_credential(self) -> Optional[Credential]:
        """获取 B 站登录凭证"""
        try:
            bili_config = global_config.bilibili
            if bili_config.sessdata and bili_config.bili_jct and bili_config.buvid3:
                return Credential(
                    sessdata=bili_config.sessdata,
                    bili_jct=bili_config.bili_jct,
                    buvid3=bili_config.buvid3,
                    dedeuserid=bili_config.dedeuserid
                )
        except (AttributeError, KeyError):
            pass
        return None

    async def parse(self, url: str) -> Optional[Dict[str, Any]]:
        """
        解析B站视频信息
        
        Args:
            url (str): B站视频URL
            
        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        # 提取 BV 号
        bvid = self.extract_bvid(url)
        if not bvid:
            logger.error(f"[{self.name}] 无法从 URL 提取 BV 号: {url}")
            return None
        
        try:
            if BILI_API_AVAILABLE:
                # 使用 bilibili-api-python 库
                credential = self._get_credential()
                v = video.Video(bvid=bvid, credential=credential)
                info = await v.get_info()
                
                # 处理封面 URL
                cover_url = info.get('pic', '')
                if cover_url:
                    cover_url = cover_url.split('@')[0]
                    if cover_url.startswith('//'):
                        cover_url = 'https:' + cover_url
                
                # 处理 UP 主头像
                owner = info.get('owner', {})
                owner_name = owner.get('name', '未知UP主')
                owner_face = owner.get('face', '')
                if owner_face:
                    if owner_face.startswith('//'):
                        owner_face = 'https:' + owner_face
                    owner_face = owner_face.split('@')[0]
                
                # 处理统计信息
                stat = info.get('stat', {})
                
                return {
                    "title": info.get('title', '未知标题'),
                    "bvid": bvid,
                    "aid": info.get('aid', 0),
                    "duration": info.get('duration', 0),
                    "cover_url": cover_url,
                    "play": stat.get('view', 0),
                    "like": stat.get('like', 0),
                    "coin": stat.get('coin', 0),
                    "favorite": stat.get('favorite', 0),
                    "share": stat.get('share', 0),
                    "danmaku": stat.get('danmaku', 0),
                    "owner_name": owner_name,
                    "owner_avatar": owner_face,
                    "followers": info.get('owner', {}).get('fans', 0),
                    "description": info.get('desc', ''),
                    "pubdate": info.get('pubdate', 0),
                }
            else:
                # 备用方案：直接解析页面
                return await self._parse_fallback(url, bvid)
                
        except ResponseCodeException as e:
            logger.error(f"[{self.name}] API 返回错误: {e.code} - {e.msg}")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            logger.error(f"[{self.name}] 解析视频信息失败: {type(e).__name__}: {e}")
            if BILI_API_AVAILABLE:
                logger.info(f"[{self.name}] 尝试备用解析方案")
                return await self._parse_fallback(url, bvid)
        
        return None
    
    async def _parse_fallback(self, url: str, bvid: str) -> Optional[Dict[str, Any]]:
        """
        备用解析方案（不使用 bilibili-api-python）
        
        Args:
            url (str): B站视频URL
            bvid (str): BV号
            
        Returns:
            Optional[Dict[str, Any]]: 视频信息字典
        """
        try:
            session = self.get_session()
            clean_url = url.split('?')[0]
            if '#/' in clean_url:
                clean_url = clean_url.split('#/')[0]

            # SSRF 防护：仅允许 http/https 且拒绝内网/回环地址
            if not input_validator.validate_http_url(clean_url):
                logger.warning(f"[{self.name}] 拒绝访问不安全的 URL: {clean_url[:200]}")
                return None

            async with session.get(clean_url, headers=self.HEADERS, timeout=5) as response:
                response.raise_for_status()
                text = await response.text()
                
                # 提取标题
                import re
                title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', text)
                title = title_match.group(1).strip() if title_match else '未知标题'
                
                # 提取播放量等信息
                play_match = re.search(r'"view":(\d+)', text)
                play = int(play_match.group(1)) if play_match else 0
                
                like_match = re.search(r'"like":(\d+)', text)
                like = int(like_match.group(1)) if like_match else 0
                
                coin_match = re.search(r'"coin":(\d+)', text)
                coin = int(coin_match.group(1)) if coin_match else 0
                
                favorite_match = re.search(r'"favorite":(\d+)', text)
                favorite = int(favorite_match.group(1)) if favorite_match else 0
                
                share_match = re.search(r'"share":(\d+)', text)
                share = int(share_match.group(1)) if share_match else 0
                
                # 提取 UP 主信息
                owner_match = re.search(r'"name":"([^"]+)"', text)
                owner_name = owner_match.group(1) if owner_match else '未知UP主'
                
                face_match = re.search(r'"face":"([^"]+)"', text)
                owner_face = face_match.group(1) if face_match else ''
                if owner_face:
                    if owner_face.startswith('//'):
                        owner_face = 'https:' + owner_face
                    owner_face = owner_face.split('@')[0]
                
                return {
                    "title": title,
                    "bvid": bvid,
                    "aid": 0,
                    "duration": 0,
                    "cover_url": '',
                    "play": play,
                    "like": like,
                    "coin": coin,
                    "favorite": favorite,
                    "share": share,
                    "danmaku": 0,
                    "owner_name": owner_name,
                    "owner_avatar": owner_face,
                    "followers": 0,
                    "description": '',
                    "pubdate": 0,
                }
                
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            logger.error(f"[{self.name}] 备用解析方案失败: {type(e).__name__}: {e}")
        
        return None
    
    def extract_bvid(self, url: str) -> Optional[str]:
        """
        从 URL 中提取 BV 号
        
        Args:
            url (str): B站视频URL
            
        Returns:
            Optional[str]: BV号，如果失败则返回None
        """
        # 方式1: 直接从 URL 中提取
        bvid_match = re.search(r'/video/(BV\w+)', url)
        if bvid_match:
            return bvid_match.group(1)
        
        # 方式2: 从短链接跳转后提取
        if 'b23.tv' in url:
            try:
                # 简单处理，不实际跳转，直接尝试提取
                bvid_match = re.search(r'BV\w{10}', url)
                if bvid_match:
                    return bvid_match.group(0)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
        
        return None
    
    async def get_real_url(self, short_url: str) -> Optional[str]:
        """
        获取B站短链接的真实URL

        兼容 301/302/303/307/308 状态码，并同时尝试 HEAD / GET；
        部分 CDN 不支持 HEAD 请求，需要回退到 GET。最后再兜底一次
        允许跟随重定向的 GET，直接取最终 URL。
        
        Args:
            short_url (str): B站短链接
            
        Returns:
            Optional[str]: 真实URL，如果失败则返回None
        """
        from urllib.parse import urljoin

        session = self.get_session()
        last_error: Optional[Exception] = None
        redirect_statuses = (301, 302, 303, 307, 308)

        # 1. 先 HEAD 后 GET，均不自动跟随重定向，手动读取 Location
        for method in ("HEAD", "GET"):
            try:
                async with session.request(
                    method,
                    short_url,
                    headers=self.HEADERS,
                    allow_redirects=False,
                    timeout=10,
                ) as response:
                    if response.status in redirect_statuses:
                        location = response.headers.get("Location")
                        if location:
                            return urljoin(str(response.url), location)
                    # 部分服务用 200 + Location 头表示跳转
                    if response.status == 200 and response.headers.get("Location"):
                        return urljoin(str(response.url), response.headers["Location"])
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                last_error = e
                continue

        # 2. 兜底：允许自动跟随重定向，直接取最终 URL
        try:
            async with session.get(
                short_url,
                headers=self.HEADERS,
                allow_redirects=True,
                timeout=10,
            ) as response:
                final_url = str(response.url)
                if final_url and final_url != short_url:
                    return final_url
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            last_error = e

        if last_error is not None:
            logger.error(f"[{self.name}] 获取真实URL失败: {type(last_error).__name__}: {last_error}")
        else:
            logger.error(f"[{self.name}] 获取真实URL失败: 短链接未返回跳转地址 ({short_url})")
        return None
    
    async def get_direct_video_url(self, video_url: str, bvid: str) -> Optional[str]:
        """
        获取B站视频直链（通过本地文件服务器下载）
        
        Args:
            video_url (str): B站视频的完整URL
            bvid (str): BV号
            
        Returns:
            Optional[str]: 本地视频 URL，如果失败则返回None
        """
        if not BILI_API_AVAILABLE:
            return None
        
        try:
            credential = self._get_credential()
            v = video.Video(bvid=bvid, credential=credential)
            # 先获取视频信息以获取 cid
            info = await v.get_info()
            cid = info.get('cid', 0)
            
            if not cid:
                return None
            
            # 获取下载链接数据，使用 html5=True 获取网页格式（通常包含合并的音视频）
            download_url_data = await v.get_download_url(cid=cid, html5=True)
            
            # 使用 VideoDownloadURLDataDetecter 解析数据
            detecter = video.VideoDownloadURLDataDetecter(data=download_url_data)
            
            # 尝试获取 MP4 格式的合并流（包含音视频）
            streams = detecter.detect_best_streams()
            
            # 如果没有获取到流，尝试其他格式
            if not streams:
                logger.warning(f"[{self.name}] 无法获取 html5 格式，尝试获取其他格式...")
                download_url_data = await v.get_download_url(cid=cid, html5=False)
                detecter = video.VideoDownloadURLDataDetecter(data=download_url_data)
                streams = detecter.detect_best_streams()
            
            if streams:
                # 获取视频直链
                video_direct_url = streams[0].url
                
                # 检查是否是分离的 m4s 流（可能没有声音）
                is_m4s_stream = '.m4s' in video_direct_url
                if is_m4s_stream:
                    logger.warning(f"[{self.name}] 检测到分离的 m4s 流，B站 API 返回的 m4s 流通常是分离的视频和音频，需要客户端合并才能有声音")
                    logger.info(f"[{self.name}] 建议: 使用支持合并 m4s 流的下载工具（如 ffmpeg）合并视频和音频")
                
                logger.info(f"[{self.name}] 获取到视频直链，开始下载到本地...")
                
                # B站下载需要 Referer 和 User-Agent
                headers = {
                    "Referer": "https://www.bilibili.com",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                
                # 调试：打印 download_url_data 结构
                logger.debug(f"[{self.name}] download_url_data 类型: {type(download_url_data)}")
                if isinstance(download_url_data, dict):
                    logger.debug(f"[{self.name}] download_url_data keys: {list(download_url_data.keys())}")
                
                # 如果是 m4s 流且 ffmpeg 可用，先保存 download_url_data 供合并使用
                if is_m4s_stream and FFMPEG_AVAILABLE and AIOHTTP_AVAILABLE:
                    local_url = await self._download_and_merge_m4s(video_direct_url, headers, bvid, download_url_data)
                else:
                    # 使用本地文件服务器下载
                    local_url = await download_to_local(video_direct_url, timeout=120, headers=headers)
                
                if local_url:
                    logger.success(f"[{self.name}] 视频已下载到本地: {local_url}")
                    return local_url
                else:
                    logger.error(f"[{self.name}] 下载到本地失败")
                    return None
                
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ResponseCodeException) as e:
            logger.error(f"[{self.name}] 获取视频直链失败: {type(e).__name__}: {e}")
        
        return None
    
    async def _download_and_merge_m4s(self, video_url: str, headers: Dict[str, str], bvid: str, download_url_data: Dict) -> Optional[str]:
        """
        下载并合并 m4s 视频和音频流
        
        Args:
            video_url (str): 视频流 URL
            headers (Dict[str, str]): 请求头
            bvid (str): BV号
            download_url_data (Dict): 下载 URL 数据
            
        Returns:
            Optional[str]: 合并后的本地视频 URL，如果失败则返回None
        """
        if not FFMPEG_AVAILABLE:
            logger.warning("[B站解析器] ffmpeg 不可用，无法合并音视频")
            return None
        
        if not AIOHTTP_AVAILABLE:
            logger.warning("[B站解析器] aiohttp 不可用，无法合并音视频")
            return None
        
        try:
            logger.info(f"[{self.name}] 开始下载并合并 m4s 音视频...")

            # SSRF 防护：仅允许 http/https 且拒绝内网/回环地址
            if not input_validator.validate_http_url(video_url):
                logger.warning(f"[{self.name}] 拒绝下载不安全的视频流 URL: {str(video_url)[:200]}")
                return None

            # 创建共享的 ClientSession 用于下载
            async with aiohttp.ClientSession() as session:
                # 下载视频流
                video_file = tempfile.NamedTemporaryFile(suffix='.m4s', delete=False)
                video_file.close()
                
                async with session.get(video_url, headers=headers, timeout=60) as response:
                    if response.status != 200:
                        logger.error(f"[{self.name}] 下载视频流失败: HTTP {response.status}")
                        return None
                    
                    with open(video_file.name, 'wb') as f:
                        while True:
                            chunk = await response.content.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
                
                logger.info(f"[{self.name}] 视频流下载完成: {video_file.name}")
                
                # 从 download_url_data 中提取音频 URL
                # B站的 dash 格式包含视频和音频流
                audio_url = None
                if isinstance(download_url_data, dict):
                    # 尝试 dash 格式（推荐）
                    if 'dash' in download_url_data and isinstance(download_url_data['dash'], dict):
                        dash = download_url_data['dash']
                        if 'audio' in dash and isinstance(dash['audio'], list) and len(dash['audio']) > 0:
                            # 获取第一个音频流
                            audio_item = dash['audio'][0]
                            audio_url = audio_item.get('baseUrl') or audio_item.get('url') or audio_item.get('backupUrl')
                            logger.debug(f"[{self.name}] 从 dash.audio 提取音频 URL: {audio_url is not None}")
                        elif 'audio' in dash and isinstance(dash['audio'], dict):
                            audio_url = dash['audio'].get('baseUrl') or dash['audio'].get('url')
                            logger.debug(f"[{self.name}] 从 dash.audio (dict) 提取音频 URL: {audio_url is not None}")
                    
                    # 尝试 durl 格式（非分段流）
                    elif 'durl' in download_url_data:
                        if isinstance(download_url_data['durl'], list) and len(download_url_data['durl']) > 0:
                            main_url = download_url_data['durl'][0].get('url') or download_url_data['durl'][0].get('baseUrl')
                            if main_url:
                                video_url = main_url
                                logger.debug(f"[{self.name}] 使用 durl 主 URL: {video_url}")
                
                if not audio_url or not input_validator.validate_http_url(audio_url):
                    logger.warning(f"[{self.name}] 无法从 download_url_data 中提取有效的音频 URL")
                    logger.debug(f"[{self.name}] download_url_data 结构: {download_url_data}")
                    os.unlink(video_file.name)
                    return None

                # durl 分支可能覆盖了 video_url，再次校验
                if not input_validator.validate_http_url(video_url):
                    logger.warning(f"[{self.name}] 拒绝下载不安全的视频流 URL: {str(video_url)[:200]}")
                    os.unlink(video_file.name)
                    return None

                # 下载音频流
                audio_file = tempfile.NamedTemporaryFile(suffix='.m4s', delete=False)
                audio_file.close()
                
                async with session.get(audio_url, headers=headers, timeout=60) as response:
                    if response.status != 200:
                        logger.error(f"[{self.name}] 下载音频流失败: HTTP {response.status}")
                        os.unlink(video_file.name)
                        return None
                    
                    with open(audio_file.name, 'wb') as f:
                        while True:
                            chunk = await response.content.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
            
            logger.info(f"[{self.name}] 音频流下载完成: {audio_file.name}")
            
            # 使用 ffmpeg 合并视频和音频
            merged_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
            merged_file.close()
            
            # ffmpeg命令：使用ffmpeg -i多次输入，然后合并
            # 先转换视频流（移除音频），然后添加音频流
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-i', video_file.name, '-i', audio_file.name,
                '-c:v', 'libx264', '-c:a', 'aac',
                '-shortest', merged_file.name
            ]
            
            logger.debug(f"[{self.name}] ffmpeg命令: {' '.join(ffmpeg_cmd)}")
            
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            # 详细记录ffmpeg输出
            if result.stdout:
                logger.debug(f"[{self.name}] ffmpeg stdout: {result.stdout}")
            if result.stderr:
                logger.debug(f"[{self.name}] ffmpeg stderr: {result.stderr}")
            
            if result.returncode != 0:
                logger.error(f"[{self.name}] ffmpeg 合并失败: {result.stderr}")
                os.unlink(video_file.name)
                os.unlink(audio_file.name)
                return None
            
            # 验证输出文件
            merged_size = os.path.getsize(merged_file.name)
            logger.debug(f"[{self.name}] 合并文件大小: {merged_size} bytes")
            
            if merged_size == 0:
                logger.error(f"[{self.name}] ffmpeg生成了空文件，命令可能有问题")
                logger.error(f"[{self.name}] ffmpeg命令: {' '.join(ffmpeg_cmd)}")
                if result.stderr:
                    logger.error(f"[{self.name}] ffmpeg错误输出: {result.stderr}")
                os.unlink(video_file.name)
                os.unlink(audio_file.name)
                return None
            
            logger.info(f"[{self.name}] 音视频合并成功: {merged_file.name} ({merged_size} bytes)")
            
            # 上传合并后的文件到本地文件服务器
            server = get_local_file_server()
            if server and server.site is not None:
                try:
                    file_id = server._generate_file_id(f'file://{merged_file.name}')
                    dest_path = server.download_dir / file_id
                    
                    # 获取合并文件大小
                    merged_size = os.path.getsize(merged_file.name)
                    logger.debug(f"[{self.name}] 合并文件大小: {merged_size} bytes")
                    
                    if merged_size == 0:
                        logger.error(f"[{self.name}] 合并文件为空，ffmpeg可能失败了")
                        merged_url = None
                    else:
                        # 复制本地文件到服务器目录
                        import shutil
                        shutil.copy2(merged_file.name, dest_path)
                        server.file_map[file_id] = dest_path
                        
                        # 验证复制后的文件
                        if dest_path.exists():
                            dest_size = dest_path.stat().st_size
                            logger.debug(f"[{self.name}] 复制后文件大小: {dest_size} bytes")
                            if dest_size == merged_size:
                                merged_url = f"{server.base_url}/download?id={file_id}"
                                logger.success(f"[{self.name}] 合并后的视频已上传到本地服务器: {merged_url}")
                            else:
                                logger.error(f"[{self.name}] 文件大小不匹配: 原始 {merged_size} vs 复制 {dest_size}")
                                merged_url = None
                        else:
                            logger.error(f"[{self.name}] 文件复制失败: {dest_path} 不存在")
                            merged_url = None
                except Exception as e:
                    logger.error(f"[{self.name}] 上传合并文件失败: {e}")
                    merged_url = None
            else:
                merged_url = None
            
            # 清理临时文件
            try:
                os.unlink(video_file.name)
                os.unlink(audio_file.name)
                os.unlink(merged_file.name)
            except (OSError, PermissionError) as e:
                logger.warning(f"[{self.name}] 清理临时文件失败: {e}")
            
            if merged_url:
                logger.success(f"[{self.name}] 合并后的视频已上传到本地服务器: {merged_url}")
                return merged_url
            
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError, subprocess.CalledProcessError) as e:
            logger.error(f"[{self.name}] 合并音视频失败: {type(e).__name__}: {e}")
        
        return None
    
    async def format_response(self, event: MessageEvent, data: Dict[str, Any]) -> List[Any]:
        """
        格式化B站视频响应消息
        
        Args:
            event (MessageEvent): 消息事件对象
            data (Dict[str, Any]): 视频信息
            
        Returns:
            List[Any]: 消息段列表
        """
        # 检查视频时长
        video_message: Union[str, MessageSegment]
        direct_url = None
        if data['duration'] > 7200:  # 2小时 = 7200秒
            video_message = "视频时长超过2小时，不进行解析。"
        else:
            # 构建完整的B站视频URL
            video_url = f"https://www.bilibili.com/video/{data.get('bvid', '')}"
            bvid = data.get('bvid', '')
            direct_url = await self.get_direct_video_url(video_url, bvid)
            if direct_url:
                video_message = MessageSegment.video(direct_url)
            else:
                video_message = "视频解析失败，无法获取直链。"

        text_message = (
            f"BiliBili 视频解析\n"
            f"--------------------\n"
            f" UP主: {data['owner_name']}\n"
            f" 粉丝: {self.format_count(data['followers'])}\n"
            f"--------------------\n"
            f" 标题: {data['title']}\n"
            f" BV号: {data['bvid']}\n"
            f" 时长: {format_duration(data['duration'])}\n"
            f"--------------------\n"
            f" 数据:\n"
            f"   播放: {self.format_count(data['play'])}\n"
            f"   点赞: {self.format_count(data['like'])}\n"
            f"   投币: {self.format_count(data['coin'])}\n"
            f"   收藏: {self.format_count(data['favorite'])}\n"
            f"   转发: {self.format_count(data['share'])}\n"
            f"   弹幕: {self.format_count(data.get('danmaku', 0))}\n"
        )
        
        image_message_segment = [
            MessageSegment.text("B站封面："),
            MessageSegment.image(data['cover_url'])
        ]

        up_info_segment = [
            MessageSegment.text("UP主头像："),
            MessageSegment.image(data['owner_avatar'])
        ]

        nodes = [
            event.bot.build_forward_node(user_id=event.self_id, nickname=self.nickname, message=text_message),
            event.bot.build_forward_node(user_id=event.self_id, nickname=self.nickname, message=image_message_segment),
            event.bot.build_forward_node(user_id=event.self_id, nickname=self.nickname, message=up_info_segment),
            event.bot.build_forward_node(user_id=event.self_id, nickname=self.nickname, message=video_message)
        ]

        # 媒体只在合并转发内展示，不单独直接发
        return nodes
    
    def should_handle_url(self, url: str) -> bool:
        """
        判断是否应该处理该URL
        
        Args:
            url (str): URL
            
        Returns:
            bool: 是否应该处理
        """
        return bool(self.url_pattern.search(url))
