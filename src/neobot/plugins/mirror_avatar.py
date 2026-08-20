"""
镜像头像插件

提供 /镜像 指令，将@的用户头像或用户发送的图片处理成轴对称图形。
支持普通图片和 GIF 动画。
"""
from neobot.plugin_api import platform_command, platform_message, Bot, input_validator, define_plugin
from neobot.models.events.message import MessageEvent
from PIL import Image, ImageSequence
import io
import aiohttp
import base64
import asyncio

plugin_manifest = define_plugin(
    name="mirror_avatar",
    description="将用户头像或图片处理成轴对称图形",
    usage="/镜像 @人 - 将@的用户头像处理成轴对称图形\n/镜像 gif - 将@的用户头像处理成轴对称GIF动画\n/镜像 - 等待用户发送图片进行镜像处理",
)

# 存储等待图片的用户信息：user_id -> asyncio.Task（等待任务），收到图片/超时时取消，避免任务泄漏
waiting_for_image = {}

async def get_avatar(user_id: int) -> bytes:
    """
    获取用户头像
    
    :param user_id: 用户QQ号
    :return: 头像图片字节
    """
    # 构建QQ头像URL
    url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
            else:
                raise Exception(f"获取头像失败: {response.status}")

async def get_image_from_url(url: str) -> bytes:
    """
    从URL获取图片
    
    :param url: 图片URL
    :return: 图片字节
    """
    # SSRF 防护：仅允许 http/https 且拒绝内网/回环地址
    if not input_validator.validate_http_url(url):
        raise Exception("不安全的图片 URL")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
            else:
                raise Exception(f"获取图片失败: {response.status}")

def process_avatar(image_bytes: bytes) -> bytes:
    """
    处理头像为轴对称图形
    
    :param image_bytes: 原始头像字节
    :return: 处理后的头像字节
    """
    # 打开图片
    img = Image.open(io.BytesIO(image_bytes))
    
    # 获取图片尺寸
    width, height = img.size
    
    # 计算对称轴位置（中间）
    mid_x = width // 2
    
    # 分割图片为左右两部分
    left_half = img.crop((0, 0, mid_x, height))
    
    # 翻转左侧部分到右侧
    left_half_flipped = left_half.transpose(Image.FLIP_LEFT_RIGHT)
    
    # 创建新图片
    new_img = Image.new('RGB', (width, height))
    
    # 粘贴左侧原始部分和右侧翻转部分
    new_img.paste(left_half, (0, 0))
    new_img.paste(left_half_flipped, (mid_x, 0))
    
    # 保存处理后的图片
    output = io.BytesIO()
    new_img.save(output, format='JPEG')
    output.seek(0)
    
    return output.read()

def process_gif_avatar(gif_bytes: bytes) -> bytes:
    """
    处理GIF动画为轴对称图形
    
    :param gif_bytes: 原始GIF字节
    :return: 处理后的GIF字节
    """
    # 打开GIF
    gif = Image.open(io.BytesIO(gif_bytes))
    
    # 检查是否为动画GIF
    if not getattr(gif, "is_animated", False):
        # 如果不是动画，当作普通图片处理
        return process_avatar(gif_bytes)
    
    # 获取GIF的所有帧
    frames = []
    durations = []
    disposal_methods = []
    
    for frame in ImageSequence.Iterator(gif):
        # 如果是P模式（调色板模式），需要特殊处理
        if frame.mode == 'P':
            # 转换为RGB进行处理
            frame_rgb = frame.convert('RGB')
        else:
            frame_rgb = frame.convert('RGB')
        
        # 获取图片尺寸
        width, height = frame_rgb.size
        
        # 计算对称轴位置（中间）
        mid_x = width // 2
        
        # 分割图片为左右两部分
        left_half = frame_rgb.crop((0, 0, mid_x, height))
        
        # 翻转左侧部分到右侧
        left_half_flipped = left_half.transpose(Image.FLIP_LEFT_RIGHT)
        
        # 创建新图片
        new_frame = Image.new('RGB', (width, height))
        
        # 粘贴左侧原始部分和右侧翻转部分
        new_frame.paste(left_half, (0, 0))
        new_frame.paste(left_half_flipped, (mid_x, 0))
        
        frames.append(new_frame)
        durations.append(frame.info.get('duration', 100))
        disposal_methods.append(frame.info.get('disposal', 0))
    
    # 保存处理后的GIF
    output = io.BytesIO()
    if frames:
        # 使用save_all保存多帧GIF
        frames[0].save(
            output,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=False,
            disposal=disposal_methods
        )
    output.seek(0)
    
    return output.read()

async def wait_for_image(bot: Bot, event: MessageEvent):
    """
    等待用户发送图片
    
    :param bot: Bot实例
    :param event: 消息事件对象
    """
    user_id = event.user_id
    
    # 设置超时时间
    timeout = 30
    
    # 提示用户发送图片
    await event.reply(f"请在{timeout}秒内发送要处理的图片")
    
    # 记录等待状态（存储当前任务引用，便于收到图片时取消，避免任务泄漏）
    waiting_for_image[user_id] = asyncio.current_task()
    
    try:
        # 等待超时
        await asyncio.sleep(timeout)
        
        # 检查是否仍然在等待
        if user_id in waiting_for_image:
            del waiting_for_image[user_id]
            await event.reply("等待超时，请重新发送指令")
    except asyncio.CancelledError:
        # 图片已收到，任务被取消
        pass
    finally:
        # 兜底清理：确保任务退出后条目不残留
        waiting_for_image.pop(user_id, None)

@platform_message(["qq", "discord"], block=False)
async def handle_image_message(bot: Bot, event: MessageEvent):
    """
    处理用户发送的图片消息
    
    :param bot: Bot实例
    :param event: 消息事件对象
    """
    user_id = event.user_id
    
    # 检查用户是否在等待图片
    if user_id not in waiting_for_image:
        return
    
    # 查找消息中的图片
    images = []
    is_gif = False
    for segment in event.message:
        if segment.type == "image":
            url = segment.data.get("url", "")
            # 检查是否为GIF图片
            if ".gif" in url.lower() or segment.data.get("sub_type", 0) == 1:
                is_gif = True
            if url:
                images.append((url, is_gif))
    
    if not images:
        # 取消等待任务并清理
        task = waiting_for_image.pop(user_id, None)
        if task is not None:
            task.cancel()
        await event.reply("未找到图片，请重新发送")
        return
    
    # 取消等待任务（收到图片，不再需要超时回复）
    task = waiting_for_image.pop(user_id, None)
    if task is not None:
        task.cancel()
    
    try:
        # 获取第一张图片
        image_url, is_gif = images[0]
        
        # 下载图片
        image_bytes = await get_image_from_url(image_url)
        
        # 处理图片
        if is_gif:
            processed_image = process_gif_avatar(image_bytes)
        else:
            processed_image = process_avatar(image_bytes)
        
        # 检查是否可以发送图片
        # Discord 等平台没有 can_send_image，视为支持发送
        can_send = await bot.can_send_image() if hasattr(bot, "can_send_image") else {"yes": True}
        if not can_send.get("yes"):
            await event.reply("当前环境不支持发送图片")
            return
        
        # 发送处理后的图片
        from neobot.models.message import MessageSegment
        # 将字节数据转换为 Base64 编码
        processed_image_base64 = base64.b64encode(processed_image).decode('utf-8')
        # 使用 Base64 编码的字符串
        await event.reply(MessageSegment.image(f"base64://{processed_image_base64}"))
        
    except Exception as e:
        await event.reply(f"处理图片失败: {str(e)}")

@platform_command(["qq", "discord"], "镜像")
async def handle_mirror(bot: Bot, event: MessageEvent, args: list[str]):
    """
    处理镜像指令，将@的用户头像或用户发送的图片处理成轴对称图形
    
    :param bot: Bot实例
    :param event: 消息事件对象
    :param args: 指令参数列表
    """
    # 检查消息中是否有@的用户
    at_users = []
    for segment in event.message:
        if segment.type == "at" and segment.data.get("qq"):
            at_users.append(int(segment.data["qq"]))
    
    # 检查是否为GIF模式
    is_gif_mode = False
    if args and args[0] == "gif":
        is_gif_mode = True
    
    if at_users:
        # 获取第一个@的用户
        user_id = at_users[0]
        
        try:
            # 获取用户头像
            avatar_bytes = await get_avatar(user_id)
            
            # 处理头像
            if is_gif_mode:
                processed_avatar = process_gif_avatar(avatar_bytes)
            else:
                processed_avatar = process_avatar(avatar_bytes)
            
            # 检查是否可以发送图片
            can_send = await bot.can_send_image()
            if not can_send.get("yes"):
                await event.reply("当前环境不支持发送图片")
                return
            
            # 发送处理后的头像
            from neobot.models.message import MessageSegment
            # 将字节数据转换为 Base64 编码
            processed_avatar_base64 = base64.b64encode(processed_avatar).decode('utf-8')
            # 使用 Base64 编码的字符串
            await event.reply(MessageSegment.image(f"base64://{processed_avatar_base64}"))
            
        except Exception as e:
            await event.reply(f"处理头像失败: {str(e)}")
    else:
        # 没有@用户，等待用户发送图片
        # 启动等待任务
        asyncio.create_task(wait_for_image(bot, event))
