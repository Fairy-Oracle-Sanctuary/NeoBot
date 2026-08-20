# -*- coding: utf-8 -*-
import html
import textwrap
import asyncio
import re
from typing import Dict
import datetime
import sys
from neobot.plugin_api import platform_command, platform_message, permission_manager, Permission, logger, image_manager, input_validator, define_plugin
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

plugin_manifest = define_plugin(
    name="code_py",
    description="在安全的沙箱环境中执行 Python 代码片段，支持单行、多行和图片输出。",
    usage="/py <单行代码>\n/code_py <单行代码>\n/py (进入多行输入模式)",
)

# --- 会话状态管理 ---
# 结构: {(user_id, group_id): asyncio.TimerHandle}
multi_line_sessions: Dict[tuple, asyncio.TimerHandle] = {}

async def generate_and_send_code_image(event: MessageEvent, input_code: str, output_result: str):
    """
    生成代码执行结果的图片并发送，如果发送失败则降级为文本消息。
    
    Args:
        event (MessageEvent): 消息事件对象
        input_code (str): 用户输入的代码
        output_result (str): 代码执行结果
    """
    try:
        # 准备模板数据
        user_nickname = event.sender.nickname if event.sender else str(event.user_id)
        user_id = event.user_id
        avatar_initial = user_nickname[0] if user_nickname else "U"
        
        # 构建QQ头像URL
        qq_avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
        
        template_data = {
            "user_nickname": user_nickname,
            "user_id": user_id,
            "avatar_initial": avatar_initial,
            "qq_avatar_url": qq_avatar_url,
            "code": input_code,
            "result": output_result,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "execution_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "result_title": "执行成功" if "Traceback" not in output_result and "Error" not in output_result else "执行出错",
            "result_class": "result-success" if "Traceback" not in output_result and "Error" not in output_result else "result-error"
        }
        
        # 渲染模板为图片
        image_base64 = await image_manager.render_template_to_base64(
            template_name="code_execution.html",
            data=template_data,
            output_name=f"code_execution_{event.user_id}_{int(datetime.datetime.now().timestamp())}.png",
            quality=90,
            image_type="png"
        )
        
        if image_base64:
            # 发送图片
            await event.reply(MessageSegment.image(image_base64))
        else:
            # 如果图片生成失败，降级为文本消息
            await event.reply(f"--- 你的代码 ---\n{input_code}\n--- 执行结果 ---\n{output_result}")
            
    except Exception as e:
        logger.error(f"[code_py] 生成代码执行图片失败: {e}")
        # 降级为文本消息
        await event.reply(f"--- 你的代码 ---\n{input_code}\n--- 执行结果 ---\n{output_result}")

async def execute_code(event: MessageEvent, code: str):
    """
    核心代码执行逻辑。
    
    Args:
        event (MessageEvent): 消息事件对象
        code (str): 要执行的Python代码
    """
    code_executor = getattr(event.bot, 'code_executor', None)
    if not code_executor or not code_executor.docker_client:
        await event.reply("代码执行服务当前不可用，请检查 Docker 连接配置。")
        return

    # 定义一个包装回调函数，确保正确处理异步操作和异常
    async def callback_wrapper(result):
        try:
            await generate_and_send_code_image(event, code, result)
        except Exception as e:
            logger.error(f"[code_py] 执行回调时发生错误: {e}")
            # 即使回调失败，也要确保任务被标记为完成
            # 降级为简单文本回复
            try:
                await event.reply(f"代码执行结果:\n{result}")
            except Exception as reply_error:
                logger.error(f"[code_py] 发送降级回复时也失败: {reply_error}")
    
    await code_executor.add_task(
        code, 
        callback_wrapper
    )
    await event.reply("代码已提交至沙箱执行队列，请稍候...")

def cleanup_session(session_key: tuple):
    """
    清理超时的会话。
    """
    if session_key in multi_line_sessions:
        del multi_line_sessions[session_key]
        logger.info(f"[code_py] 会话 {session_key} 已超时，自动取消。")

def normalize_code(code: str) -> str:
    """
    规范化用户输入的 Python 代码字符串。

    主要处理两个问题：
    1. 对消息中可能存在的 HTML 实体进行解码 (e.g., &#91; -> [)。
    2. 移除整个代码块的公共前导缩进，以修复因复制粘贴导致的多余缩进。

    :param code: 原始代码字符串。
    :return: 规范化后的代码字符串。
    """
    # 1. 解码 HTML 实体
    code = html.unescape(code)
    
    # 2. 输入验证 - 检查危险代码
    if not validate_code_security(code):
        raise ValueError("代码包含不安全内容，拒绝执行")

    # 3. 移除公共前导缩进
    try:
        code = textwrap.dedent(code)
    except ValueError:
        # 在某些情况下（例如，不一致的缩进），dedent 可能会失败，
        # 但我们不希望因此中断流程，所以捕获异常并继续。
        pass
        
    return code.strip()

def validate_code_security(code: str) -> bool:
    """
    验证代码安全性
    
    Args:
        code: Python 代码字符串
        
    Returns:
        bool: 是否安全
    """
    # 检查命令注入
    if not input_validator.validate_command_input(code):
        logger.warning(f"检测到可能的命令注入: {code[:100]}...")
        return False
    
    # 检查路径遍历
    if not input_validator.validate_path_input(code):
        logger.warning(f"检测到可能的路径遍历: {code[:100]}...")
        return False
    
    # 检查危险的系统调用
    dangerous_patterns = [
        r"import\s+(os|sys|subprocess|shutil|platform|ctypes)",
        r"__import__\s*\(",
        r"eval\s*\(",
        r"exec\s*\(",
        r"compile\s*\(",
        r"open\s*\(",
        r"__builtins__",
        r"__import__",
        r"globals\s*\(",
        r"locals\s*\(",
        r"getattr\s*\(",
        r"setattr\s*\(",
        r"delattr\s*\(",
        r"hasattr\s*\(",
        r"property\s*\(",
        r"super\s*\(",
        r"type\s*\(",
        r"isinstance\s*\(",
        r"issubclass\s*\(",
        r"callable\s*\(",
        r"dir\s*\(",
        r"vars\s*\(",
        r"help\s*\(",
        r"memoryview\s*\(",
        r"buffer\s*\(",
        r"slice\s*\(",
        r"staticmethod\s*\(",
        r"classmethod\s*\(",
        r"abc\.",
        r"inspect\.",
        r"pickle\.",
        r"marshal\.",
        r"shelve\.",
        r"dbm\.",
        r"sqlite3\.",
        r"xml\.",
        r"json\.",
        r"csv\.",
        r"configparser\.",
        r"argparse\.",
        r"optparse\.",
        r"getopt\.",
        r"shlex\.",
        r"cmd\.",
        r"readline\.",
        r"rlcompleter\.",
        r"stat\.",
        r"filecmp\.",
        r"tempfile\.",
        r"glob\.",
        r"fnmatch\.",
        r"linecache\.",
        r"shutil\.",
        r"macpath\.",
        r"dircache\.",
        r"fileinput\.",
        r"statvfs\.",
        r"socket\.",
        r"ssl\.",
        r"select\.",
        r"asyncore\.",
        r"asynchat\.",
        r"signal\.",
        r"mmap\.",
        r"crypt\.",
        r"termios\.",
        r"tty\.",
        r"pty\.",
        r"fcntl\.",
        r"pipes\.",
        r"posix\.",
        r"resource\.",
        r"nis\.",
        r"syslog\.",
        r"commands\.",
        r"pdb\.",
        r"profile\.",
        r"cProfile\.",
        r"hotshot\.",
        r"timeit\.",
        r"trace\.",
        r"tracemalloc\.",
        r"line_profiler\.",
        r"memory_profiler\.",
        r"guppy\.",
        r"objgraph\.",
        r"pympler\.",
        r"meliae\.",
        r"filprofiler\.",
        r"scalene\.",
        r"py-spy\.",
        r"austin\.",
        r"vprof\.",
        r"heartrate\.",
        r"pyflame\.",
        r"perf\.",
        r"vmprof\.",
        r"yappi\.",
        r"callsite\.",
        r"codetiming\.",
        r"stopwatch\.",
        r"timer\.",
        r"timing\.",
        r"benchmark\.",
        r"speedtest\.",
        r"performance\.",
        r"profiling\.",
        r"tracing\.",
        r"monitoring\.",
        r"instrumentation\.",
        r"debugging\.",
        r"logging\.",
        r"warnings\.",
        r"exceptions\.",
        r"traceback\.",
        r"__future__\.",
        r"builtins\.",
        r"types\.",
        r"collections\.",
        r"heapq\.",
        r"bisect\.",
        r"array\.",
        r"sched\.",
        r"queue\.",
        r"weakref\.",
        r"copy\.",
        r"pprint\.",
        r"reprlib\.",
        r"enum\.",
        r"numbers\.",
        r"math\.",
        r"cmath\.",
        r"decimal\.",
        r"fractions\.",
        r"random\.",
        r"statistics\.",
        r"itertools\.",
        r"functools\.",
        r"operator\.",
        r"pathlib\.",
        r"os\.path\.",
        r"fileinput\.",
        r"stat\.",
        r"statvfs\.",
        r"grp\.",
        r"pwd\.",
        r"crypt\.",
        r"termios\.",
        r"tty\.",
        r"pty\.",
        r"fcntl\.",
        r"pipes\.",
        r"resource\.",
        r"sys\.",
        r"sysconfig\.",
        r"builtins\.",
        r"__main__\.",
        r"warnings\.",
        r"contextlib\.",
        r"abc\.",
        r"atexit\.",
        r"traceback\.",
        r"__future__\.",
        r"gc\.",
        r"inspect\.",
        r"site\.",
        r"code\.",
        r"codeop\.",
        r"zipfile\.",
        r"tarfile\.",
        r"shutil\.",
        r"glob\.",
        r"fnmatch\.",
        r"linecache\.",
        r"shlex\.",
        r"macpath\.",
        r"dircache\.",
        r"stat\.",
        r"statvfs\.",
        r"filecmp\.",
        r"tempfile\.",
        r"spwd\.",
        r"grp\.",
        r"pwd\.",
        r"crypt\.",
        r"termios\.",
        r"tty\.",
        r"pty\.",
        r"fcntl\.",
        r"pipes\.",
        r"resource\.",
        r"nis\.",
        r"syslog\.",
        r"commands\.",
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            logger.warning(f"检测到危险模块导入: {pattern}")
            return False
    
    return True


@platform_command(["qq", "discord"], "py", "python", "code_py", permission=Permission.ADMIN)
async def code_py_main(event: MessageEvent, args: list[str]):
    """
    /py 命令的主入口。
    - 如果有参数，直接执行。
    - 如果没有参数，开启多行输入模式。
    """
    code_to_run = " ".join(args)

    if code_to_run:
        # 单行模式，对代码进行规范化处理
        normalized_code = normalize_code(code_to_run)
        if not normalized_code:
            await event.reply("代码为空或格式错误，请输入有效的代码。")
            return
        await execute_code(event, normalized_code)
    else:
        # 多行模式
        # 使用 getattr 兼容私聊和群聊
        session_key = (event.user_id, getattr(event, 'group_id', 'private'))
        
        # 如果上一个会话的超时任务还在，先取消它
        if session_key in multi_line_sessions:
            multi_line_sessions[session_key].cancel()

        await event.reply("已进入多行代码输入模式，请直接发送你的代码。\n(60秒内无操作将自动取消)")
        
        # 设置 60 秒超时
        loop = asyncio.get_running_loop()
        timeout_handler = loop.call_later(
            60, 
            cleanup_session, 
            session_key
        )
        multi_line_sessions[session_key] = timeout_handler

@platform_message(["qq", "discord"], block=False)
async def handle_multi_line_code(event: MessageEvent):
    """
    通用消息处理器，用于捕获多行模式下的代码输入。
    """
    # 使用 getattr 兼容私聊和群聊
    session_key = (event.user_id, getattr(event, 'group_id', 'private'))
    if session_key in multi_line_sessions:
        # 权限校验：仅管理员可执行代码（防御权限降级等边界情况）
        if not await permission_manager.check_permission(event.user_id, Permission.ADMIN):
            multi_line_sessions[session_key].cancel()
            del multi_line_sessions[session_key]
            await event.reply("权限不足：仅管理员可执行代码，多行输入模式已取消。")
            return True

        # 取消超时任务
        multi_line_sessions[session_key].cancel()
        del multi_line_sessions[session_key]

        # 对多行代码进行规范化处理
        normalized_code = normalize_code(event.raw_message)
        
        if not normalized_code:
            await event.reply("捕获到的代码为空或格式错误，已取消输入。")
            return

        await execute_code(event, normalized_code)
        return True # 消费事件，防止其他处理器响应
