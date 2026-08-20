# -*- coding: utf-8 -*-
"""
Discord 适配器 (Discord Adapter)

此模块负责与 Discord API 建立连接，接收 Discord 消息，
并将其转换为本地 OneBot 数据模型，
同时提供将本地消息段发送回 Discord 的能力。
"""
import asyncio
import json
import os
import io
import tempfile
from typing import Optional

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False

from neobot.core.utils.logger import ModuleLogger
from neobot.core.managers.redis_manager import redis_manager
from neobot.core.config_loader import global_config

class DiscordAdapter(discord.Client if DISCORD_AVAILABLE else object):
    """
    Discord 客户端适配器。
    继承自 discord.Client，负责处理 Discord 的底层事件。
    """
    def __init__(self, token: str):
        if not DISCORD_AVAILABLE:
            raise ImportError("discord.py 未安装，请运行 `pip install discord.py`")
        
        self.logger = ModuleLogger("DiscordAdapter")
        self.token = token
        self.send_channel = None
        # 监督器状态：start_client 每次尝试都会创建一个全新的客户端实例，
        # 因为 discord.py 的 Client 在会话关闭后无法复用。
        self._connected = False
        self._active_client: Optional["DiscordAdapter"] = None
        self._supervisor_stop = False
        
        self.proxy = None
        self.proxy_type = "http"
        self._redis_sub_task = None
        # 后台任务集合：跟踪 fire-and-forget 任务（如 Redis 派发的 handle_send_message），关闭时统一取消
        self._background_tasks: set = set()
        if global_config.discord.proxy:
            self.proxy = global_config.discord.proxy
            self.proxy_type = global_config.discord.proxy_type or "http"
            
            proxy_url = self.proxy
            if self.proxy_type.lower() in ["socks5", "socks4"]:
                if not proxy_url.startswith(("socks5://", "socks4://")):
                    proxy_url = f"{self.proxy_type.lower()}://{proxy_url.split('://')[-1]}"
            
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
            self.logger.info(f"[DiscordAdapter] 代理已设置: {proxy_url} (类型: {self.proxy_type})")
            
        intents = discord.Intents.default()
        intents.message_content = True
        
        # discord.py 原生支持 proxy 参数：REST 请求（users/@me、发送消息等）
        # 和 WebSocket 网关都会通过该代理连接。
        if self.proxy:
            super().__init__(intents=intents, proxy=self.proxy)
            self.logger.info(f"[DiscordAdapter] discord.py 请求将走代理: {self.proxy}")
        else:
            super().__init__(intents=intents)

    def _spawn_task(self, coro) -> asyncio.Task:
        """创建后台任务并登记引用，任务完成后自动移除（避免僵尸任务累积）。"""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def on_ready(self):
        """当 Bot 成功连接到 Discord 时触发"""
        self._connected = True
        self.logger.success(f"Discord Bot 已登录: {self.user} (ID: {self.user.id})")
        
        self.start_heartbeat_task(interval=30)
        
        if self._redis_sub_task is None or self._redis_sub_task.done():
            if self._redis_sub_task is not None and not self._redis_sub_task.done():
                self._redis_sub_task.cancel()
                try:
                    await self._redis_sub_task
                except asyncio.CancelledError:
                    pass
            self._redis_sub_task = asyncio.create_task(self.start_redis_subscription())

    async def on_resumed(self):
        """当 Bot 重新连接到 Discord 时触发"""
        self._connected = True
        self.logger.success(f"Discord Bot 已重新连接: {self.user} (ID: {self.user.id})")
        
        self.start_heartbeat_task(interval=30)
        
        if self._redis_sub_task is None or self._redis_sub_task.done():
            if self._redis_sub_task is not None and not self._redis_sub_task.done():
                self._redis_sub_task.cancel()
                try:
                    await self._redis_sub_task
                except asyncio.CancelledError:
                    pass
            self._redis_sub_task = asyncio.create_task(self.start_redis_subscription())

    async def on_message(self, message: 'discord.Message'):
        """当收到 Discord 消息时触发"""
        # 忽略机器人自己的消息
        if message.author.bot:
            return

        self.logger.info(f"[Discord 消息] {message.author}: {message.content}")

        try:
            # 阶段 2/3：不再伪装 OneBot 事件，走平台无关消息总线 + CommandContext 分发
            from neobot.core.messaging.bus import message_bus
            from neobot.core.messaging.context import CommandContext
            from neobot.core.messaging.message import MessageSegment as PlatformSegment
            from neobot.core.messaging.message import PlatformMessage
            from neobot.core.managers.command_manager import matcher
            from .router import DiscordBotWrapper

            segments = []
            content_parts = []
            if message.content:
                content_parts.append(message.content)
                segments.append(PlatformSegment.text(message.content))
            for attachment in message.attachments:
                filename = attachment.filename.lower()
                if filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    segments.append(PlatformSegment.image(attachment.url, attachment.filename))
                elif filename.endswith(('.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv')):
                    segments.append(PlatformSegment.video(attachment.url, attachment.filename))
                elif filename.endswith(('.amr', '.silk', '.mp3', '.wav', '.ogg', '.m4a')):
                    segments.append(PlatformSegment.record(attachment.url, attachment.filename))
                else:
                    segments.append(PlatformSegment.image(attachment.url, attachment.filename))
                content_parts.append(f"[附件: {attachment.filename}]")

            channel_type = "private" if isinstance(message.channel, discord.DMChannel) else "group"
            msg = PlatformMessage(
                platform="discord",
                channel_id=message.channel.id,
                channel_type=channel_type,
                message_id=message.id,
                author_id=message.author.id,
                author_name=message.author.display_name,
                content="".join(content_parts),
                segments=segments,
                reply_to=getattr(message.reference, "message_id", None) if message.reference else None,
                raw=message,
            )
            bot = DiscordBotWrapper(self)
            ctx = CommandContext.from_platform_message(msg, bot, sender_name=message.author.display_name)

            # 入站总线：跨平台转发器等订阅
            await message_bus.publish_incoming(msg)
            # 平台感知指令分发（Discord 只跑显式注册了 discord 平台的插件）
            await matcher.handle_platform_event(ctx)
        except Exception as e:
            self.logger.error(f"处理 Discord 消息时发生异常: {e}")
            import traceback
            self.logger.error(f"异常堆栈: {traceback.format_exc()}")

    async def start_redis_subscription(self):
        """启动 Redis 订阅以处理跨平台消息发送"""
        if redis_manager._redis is None:
            self.logger.warning("[DiscordAdapter] Redis 未初始化，跳过订阅")
            return
            
        try:
            channel_name = "neobot_discord_send"
            # 使用上下文管理器，任务取消/异常时 pubsub 连接会被自动关闭，
            # 避免重连后 Redis 连接池泄漏
            async with redis_manager.redis.pubsub() as pubsub:
                await pubsub.subscribe(channel_name)

                self.logger.success(f"[DiscordAdapter] 已订阅 Redis 频道: {channel_name}")

                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            # 校验 HMAC 签名，防止任意可访问 Redis 的进程伪造发送消息
                            if isinstance(data, dict):
                                signature = data.pop("_sig", "")
                            else:
                                signature = ""
                            if not redis_manager.verify_pubsub(data, signature):
                                self.logger.warning("[DiscordAdapter] Redis 消息签名校验失败，丢弃伪造消息")
                                continue
                            if data.get("type") == "send_message":
                                # 使用 _spawn_task 异步处理并登记引用，避免阻塞订阅循环且防止僵尸任务累积
                                self._spawn_task(self.handle_send_message(data))
                        except json.JSONDecodeError as e:
                            self.logger.error(f"[DiscordAdapter] 解析 Redis 消息失败: {e}")
                        except Exception as e:
                            self.logger.error(f"[DiscordAdapter] 处理 Redis 消息失败: {e}")
                        
        except Exception as e:
            self.logger.error(f"[DiscordAdapter] Redis 订阅异常: {e}")

    async def convert_to_ogg_opus(self, audio_bytes: bytes) -> Optional[bytes]:
        """
        将音频文件转换为 OGG Opus 格式，用于 Discord 语音消息
        """
        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as temp_in:
                temp_in.write(audio_bytes)
                temp_in_path = temp_in.name
                
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_out:
                temp_out_path = temp_out.name
                
            # 使用 ffmpeg 转换
            # -c:a libopus: 使用 Opus 编码器
            # -b:a 64k: 比特率 64k
            # -vbr on: 开启可变比特率
            # -compression_level 10: 最高压缩级别
            # -frame_duration 20: 帧时长 20ms
            # -application voip: 针对语音优化
            cmd = [
                "ffmpeg", "-y", "-i", temp_in_path,
                "-c:a", "libopus", "-b:a", "64k", "-vbr", "on",
                "-compression_level", "10", "-frame_duration", "20",
                "-application", "voip", temp_out_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                with open(temp_out_path, "rb") as f:
                    ogg_bytes = f.read()
                return ogg_bytes
            else:
                self.logger.error(f"[DiscordAdapter] ffmpeg 转换失败: {stderr.decode('utf-8', errors='ignore')}")
                return None
                
        except Exception as e:
            self.logger.error(f"[DiscordAdapter] 音频转换异常: {e}")
            return None
        finally:
            # 清理临时文件
            try:
                if os.path.exists(temp_in_path):
                    os.remove(temp_in_path)
                if os.path.exists(temp_out_path):
                    os.remove(temp_out_path)
            except Exception:
                pass

    async def handle_send_message(self, data: dict):
        """处理来自 Redis 的消息发送请求"""
        try:
            channel_id = data.get("channel_id")
            content = data.get("content", "")
            attachments = data.get("attachments", [])
            embed_data = data.get("embed")
            
            if channel_id is None:
                self.logger.error("[DiscordAdapter] 缺少 channel_id")
                return
                
            channel = self.get_channel(channel_id)
            if channel is None:
                self.logger.error(f"[DiscordAdapter] 未找到频道: {channel_id}")
                return
            
            # 检查会话状态
            if not self.is_closed():
                self.logger.info(f"[DiscordAdapter] 正在发送消息到频道 {channel_id}")
            else:
                self.logger.warning(f"[DiscordAdapter] 会话已关闭，消息将被丢弃: channel_id={channel_id}")
                return
            
            embed = None
            if embed_data:
                embed = discord.Embed.from_dict(embed_data)
            
            files = []
            if attachments:
                for attachment in attachments:
                    if isinstance(attachment, dict):
                        attachment_url = attachment.get("url", "")
                        filename = attachment.get("filename", "")
                    else:
                        attachment_url = str(attachment)
                        filename = ""
                    
                    if attachment_url.startswith('http'):
                        try:
                            import aiohttp
                            proxy_url = self.proxy if self.proxy else None
                            async with aiohttp.ClientSession() as session:
                                async with session.get(attachment_url, proxy=proxy_url, timeout=30) as response:
                                    content_bytes = await response.read()
                                    
                            if not filename:
                                filename = os.path.basename(attachment_url.split('?')[0]) or "attachment"
                            
                            # 检查是否是语音文件
                            is_voice = filename.lower().endswith(('.amr', '.silk', '.mp3', '.wav', '.ogg', '.m4a'))
                            
                            if is_voice:
                                # 尝试转换为 OGG Opus
                                ogg_bytes = await self.convert_to_ogg_opus(content_bytes)
                                if ogg_bytes:
                                    # 转换成功，作为语音消息发送
                                    # discord.py 官方 API 目前不支持直接发送语音消息
                                    # 我们需要使用内部的 HTTP 客户端来发送
                                    try:
                                        # 构造 payload
                                        payload = {
                                            "flags": 8192  # IS_VOICE_MESSAGE
                                        }
                                        
                                        if content:
                                            payload["content"] = content
                                            content = ""  # 清空 content，避免重复发送
                                            
                                        if embed:
                                            payload["embeds"] = [embed.to_dict()]
                                            embed = None  # 清空 embed，避免重复发送
                                            
                                        # 使用内部 HTTP 客户端发送
                                        route = discord.http.Route('POST', '/channels/{channel_id}/messages', channel_id=channel_id)
                                        await self.http.request(
                                            route,
                                            form=[
                                                {'name': 'payload_json', 'value': json.dumps(payload)},
                                                {'name': 'files[0]', 'value': ogg_bytes, 'filename': 'voice-message.ogg', 'content_type': 'audio/ogg'}
                                            ]
                                        )
                                        self.logger.success(f"[DiscordAdapter] 语音消息已发送到频道 {channel_id}")
                                        continue  # 跳过后面的普通发送逻辑
                                    except Exception as e:
                                        self.logger.error(f"[DiscordAdapter] 发送语音消息失败: {e}，将作为普通文件发送")
                                        files.append(discord.File(fp=io.BytesIO(ogg_bytes), filename="voice.ogg"))
                                else:
                                    # 转换失败，作为普通文件发送
                                    files.append(discord.File(fp=io.BytesIO(content_bytes), filename=filename))
                            else:
                                files.append(discord.File(fp=io.BytesIO(content_bytes), filename=filename))
                        except Exception as e:
                            self.logger.error(f"[DiscordAdapter] 下载附件失败: {attachment_url}, 错误: {e}")
            
            if content or files or embed:
                try:
                    self.logger.debug(f"[DiscordAdapter:TRACE] handle_send_message 准备发送: channel_id={channel_id}, content='{content[:80] if content else ''}...', files={len(files)}")
                    await channel.send(content=content, files=files if files else None, embed=embed)
                    self.logger.debug(f"[DiscordAdapter:TRACE] channel.send() 完成: channel_id={channel_id}")
                    self.logger.success(f"[DiscordAdapter] 消息已发送到频道 {channel_id}")
                except Exception as send_error:
                    self.logger.error(f"[DiscordAdapter] 发送消息失败 (channel.send): {type(send_error).__name__}: {send_error}")
            else:
                self.logger.debug(f"[DiscordAdapter] 没有内容需要发送到频道 {channel_id}")
            
        except Exception as e:
            self.logger.error(f"[DiscordAdapter] 发送消息失败: {e}")

    async def start_client(self, max_retries: int = -1, retry_delay: int = 5, max_retry_delay: int = 300):
        """
        启动 Discord 客户端（监督循环）。

        注意：discord.py 的客户端在会话关闭（Session is closed）后无法在
        同一个实例上重新 start()。旧实现“清理后在同一实例上无限重试”会导致
        每 5 秒一次、永不停歇的错误刷屏。这里每次尝试都创建一个全新的
        DiscordAdapter 实例，并使用指数退避，连接成功后重置退避。
        
        Args:
            max_retries: 最大重连次数，-1 表示无限重连
            retry_delay: 重连延迟（秒）
            max_retry_delay: 最大重连延迟（秒），指数退避上限
        """
        if not DISCORD_AVAILABLE:
            self.logger.error("无法启动 Discord 客户端：discord.py 未安装")
            return

        self._supervisor_stop = False
        self._active_client = None
        retry_count = 0

        while max_retries == -1 or retry_count < max_retries:
            if self._supervisor_stop:
                break

            # 每次尝试都创建全新的客户端实例，避免 "Session is closed" 死循环
            client = DiscordAdapter(self.token)
            self._active_client = client
            try:
                self.logger.info("正在连接 Discord...")
                await client.start(client.token)
            except asyncio.CancelledError:
                self.logger.info("连接被取消，停止 Discord 监督循环")
                self._supervisor_stop = True
            except discord.ConnectionClosed as e:
                retry_count += 1
                self.logger.warning(f"Discord 连接关闭: code={e.code}, reason={e.reason} (第 {retry_count} 次)")
                # 如果是正常关闭，不计入重连次数
                if e.code == 1000:
                    self.logger.info("连接正常关闭，等待重新连接...")
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Discord 连接异常: {type(e).__name__}: {e} (第 {retry_count} 次)")
            finally:
                was_connected = getattr(client, "_connected", False)
                await self._close_client_instance(client)
                self._active_client = None

            if self._supervisor_stop:
                break

            if was_connected:
                # 曾经成功登录过，说明网络曾恢复，重置退避
                retry_count = 0
                delay = retry_delay
            else:
                delay = min(retry_delay * (2 ** min(retry_count - 1, 5)), max_retry_delay)

            limit_text = "无限" if max_retries == -1 else str(max_retries)
            self.logger.info(f"将在 {delay} 秒后重连 ({retry_count}/{limit_text})...")
            await asyncio.sleep(delay)

        self.logger.info("Discord 客户端已停止")

    async def close(self):
        """关闭监督器及其当前活跃的 Discord 客户端实例。"""
        self._supervisor_stop = True
        active = getattr(self, "_active_client", None)
        if active is not None and active is not self:
            await self._close_client_instance(active)
            self._active_client = None
        try:
            await super().close()
        except Exception as e:
            self.logger.error(f"关闭 Discord 监督器时出错: {e}")

    async def _close_client_instance(self, client: "DiscordAdapter"):
        """
        关闭一个客户端实例并取消其后台任务（心跳、Redis 订阅）。
        """
        try:
            heartbeat_task = getattr(client, "heartbeat_task", None)
            if heartbeat_task is not None and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            self.logger.error(f"清理心跳任务时出错: {e}")

        try:
            redis_sub_task = getattr(client, "_redis_sub_task", None)
            if redis_sub_task is not None and not redis_sub_task.done():
                redis_sub_task.cancel()
                try:
                    await redis_sub_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            self.logger.error(f"清理 Redis 订阅任务时出错: {e}")

        # 取消 fire-and-forget 后台任务（如 Redis 派发的 handle_send_message）
        try:
            bg_tasks = list(getattr(client, "_background_tasks", set()))
            for task in bg_tasks:
                task.cancel()
            for task in bg_tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            client._background_tasks.clear()
        except Exception as e:
            self.logger.error(f"清理后台任务时出错: {e}")

        try:
            await client.close()
        except Exception as e:
            self.logger.error(f"关闭 Discord 客户端实例时出错: {e}")

    async def start_heartbeat(self, interval: int = 30):
        """
        启动心跳机制，定期检查连接状态
        
        Args:
            interval: 心跳间隔（秒）
        """
        self.logger.info(f"心跳机制已启动，间隔: {interval}秒")
        
        while not self.is_closed():
            try:
                await asyncio.sleep(interval)
                
                # 检查 WebSocket 连接状态
                if self.ws is not None:
                    # 正确检查 WebSocket 状态
                    if not getattr(self.ws, 'open', False):
                        self.logger.warning("检测到 WebSocket 连接已关闭，触发重连...")
                        try:
                            await self.ws.close(code=4000)
                        except Exception as close_error:
                            self.logger.error(f"关闭 WebSocket 连接时出错: {close_error}")
                        break
                    
                self.logger.debug(f"心跳正常: {self.user}")
                
            except Exception as e:
                self.logger.error(f"心跳检测异常: {e}")
                break

    def start_heartbeat_task(self, interval: int = 30):
        """
        启动心跳任务（非阻塞）
        
        Args:
            interval: 心跳间隔（秒）
        """
        if not hasattr(self, 'heartbeat_task') or self.heartbeat_task.done():
            self.heartbeat_task = asyncio.create_task(self.start_heartbeat(interval))
            self.logger.info("心跳任务已启动")
