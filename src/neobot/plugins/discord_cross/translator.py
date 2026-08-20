# -*- coding: utf-8 -*-
"""
跨平台消息互通插件翻译模块
"""
import httpx
import time
from typing import Dict, List
from neobot.plugin_api import ModuleLogger
from .config import config

logger = ModuleLogger("CrossPlatformTranslator")

TRANSLATION_CONTEXT_CACHE: Dict[str, List[Dict[str, str]]] = {}
MAX_CONTEXT_MESSAGES = 15

# 请求超时与重试（日志显示此前 DeepSeek 请求长时间超时且 0 成功，
# 显式超时 + 连续失败冷却可以避免每条消息都卡在请求上）
TRANSLATION_TIMEOUT = 15.0
TRANSLATION_RETRIES = 2
TRANSLATION_FAILURE_COOLDOWN_SECONDS = 300
TRANSLATION_FAILURE_STREAK_LIMIT = 3

# 连续失败熔断状态
_translation_fail_streak = 0
_translation_cooldown_until = 0.0

# 复用客户端（httpx 连接池），避免每条消息都新建/关闭连接导致 TIME_WAIT 堆积
_chat_client = None          # 同步 OpenAI 客户端（关键词提取）
_async_client = None         # 异步 AsyncOpenAI 客户端（翻译）
_sync_client = None          # 同步 OpenAI 客户端（备用翻译）


def _translation_on_cooldown() -> bool:
    return time.monotonic() < _translation_cooldown_until


def _record_translation_success() -> None:
    global _translation_fail_streak, _translation_cooldown_until
    _translation_fail_streak = 0
    _translation_cooldown_until = 0.0


def _record_translation_failure() -> None:
    global _translation_fail_streak, _translation_cooldown_until
    _translation_fail_streak += 1
    if _translation_fail_streak >= TRANSLATION_FAILURE_STREAK_LIMIT:
        _translation_cooldown_until = time.monotonic() + TRANSLATION_FAILURE_COOLDOWN_SECONDS
        logger.warning(
            f"[CrossPlatform] 翻译连续失败 {_translation_fail_streak} 次，"
            f"暂停翻译 {TRANSLATION_FAILURE_COOLDOWN_SECONDS}s 以避免无效请求"
        )


def _get_chat_client():
    """获取 DeepSeek Chat 客户端（仅用于关键词提取），复用单例避免连接泄漏"""
    global _chat_client
    if _chat_client is None:
        from openai import OpenAI
        _chat_client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_API_URL.replace("/chat/completions", ""),
            timeout=TRANSLATION_TIMEOUT,
            max_retries=TRANSLATION_RETRIES,
            # 忽略系统注入的 SOCKS/HTTP 代理环境变量（socksio 未安装会 ImportError）
            http_client=httpx.Client(
                trust_env=False,
                timeout=TRANSLATION_TIMEOUT,
            ),
        )
    return _chat_client


def _extract_keywords(text: str, max_keywords: int = 5) -> List[str]:
    """使用 DeepSeek AI 从文本中提取关键词"""
    if not text.strip():
        return []
    try:
        client = _get_chat_client()
        response = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": f"从以下文本中提取{max_keywords}个最关键的关键词或短语，用逗号分隔。只返回关键词，不要任何解释。"},
                {"role": "user", "content": text[:1000]}
            ],
            temperature=0.1,
            max_tokens=100
        )
        content = response.choices[0].message.content or ""
        keywords = [k.strip() for k in content.split(",") if k.strip()]
        return keywords[:max_keywords]
    except Exception as e:
        logger.error(f"[CrossPlatform] 关键词提取失败: {e}")
        return []


def get_translation_context(channel_id: int, direction: str) -> List[Dict[str, str]]:
    cache_key = f"{channel_id}_{direction}"
    return TRANSLATION_CONTEXT_CACHE.get(cache_key, [])


def save_forward_pair(
    channel_id: int,
    source_platform: str,
    original_content: str,
    formatted_content: str,
    username: str = ""
):
    if not original_content or not formatted_content:
        return
    logger.debug(f"[CrossPlatform] 保存转发配对: {source_platform} -> {formatted_content[:50]}...")


def add_translation_context(channel_id: int, direction: str, original: str, translated: str):
    cache_key = f"{channel_id}_{direction}"
    if cache_key not in TRANSLATION_CONTEXT_CACHE:
        TRANSLATION_CONTEXT_CACHE[cache_key] = []

    TRANSLATION_CONTEXT_CACHE[cache_key].append({
        "original": original,
        "translated": translated
    })

    if len(TRANSLATION_CONTEXT_CACHE[cache_key]) > MAX_CONTEXT_MESSAGES:
        TRANSLATION_CONTEXT_CACHE[cache_key] = TRANSLATION_CONTEXT_CACHE[cache_key][-MAX_CONTEXT_MESSAGES:]


async def translate_with_deepseek(
    text: str, 
    target_lang: str = "zh-CN",
    channel_id: int = 0,
    direction: str = "en2zh"
) -> str:
    """使用 DeepSeek API 翻译文本"""
    if not config.ENABLE_TRANSLATION or not text.strip():
        return text
        
    if config.DEEPSEEK_API_KEY == "your-deepseek-api-key-here":
        logger.warning("[CrossPlatform] DeepSeek API 密钥未配置，跳过翻译")
        return text

    if _translation_on_cooldown():
        logger.debug("[CrossPlatform] 翻译服务冷却中，直接返回原文")
        return text
    
    lang_name = "中文" if target_lang == "zh-CN" else "英文"
    
    context_ref = ""
    if channel_id > 0:
        context = get_translation_context(channel_id, direction)
        if context:
            context_ref = "\n\n参考最近的翻译：\n"
            for i, ctx in enumerate(context[-5:], 1):
                context_ref += f"{i}. 原文: {ctx['original'][:100]}\n   译文: {ctx['translated'][:100]}\n"
    
    system_prompt = f"""你是一个专业的翻译助手。请将以下文本翻译成{lang_name}。
只返回翻译后的文本，不要添加任何解释、注释或其他内容。避免翻译出仇视言论以及违反中国大陆相关法律法规的内容。如果有，请在翻译后有敏感的词语中把文本替换成井号（#）
保持原文的语气和格式。如果文本已经是目标语言，直接返回原文。{context_ref}"""
    
    messages = [{"role": "user", "content": text}]
    
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("[CrossPlatform] openai 库未安装，尝试使用同步请求")
        return await translate_with_deepseek_sync(text, target_lang, channel_id, direction)

    try:
        global _async_client
        if _async_client is None:
            _async_client = AsyncOpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_API_URL.replace("/chat/completions", ""),
                timeout=TRANSLATION_TIMEOUT,
                max_retries=TRANSLATION_RETRIES,
                http_client=httpx.AsyncClient(
                    trust_env=False,
                    timeout=TRANSLATION_TIMEOUT,
                ),
            )
        client = _async_client
        
        response = await client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            temperature=0.3,
            max_tokens=4000
        )
        
        translated_text = response.choices[0].message.content
        if translated_text:
            translated_text = translated_text.strip()
            logger.info(f"[CrossPlatform] 翻译成功: {text[:50]}... -> {translated_text[:50]}...")
            _record_translation_success()
            
            if channel_id > 0:
                add_translation_context(channel_id, direction, text, translated_text)
            
            return translated_text
        else:
            logger.warning("[CrossPlatform] DeepSeek 返回空翻译结果")
            return text
    except Exception as e:
        _record_translation_failure()
        logger.error(f"[CrossPlatform] 翻译失败: {type(e).__name__}: {e}")
        return text


async def translate_with_deepseek_sync(
    text: str, 
    target_lang: str = "zh-CN",
    channel_id: int = 0,
    direction: str = "en2zh"
) -> str:
    """使用同步请求的 DeepSeek 翻译（备用方案）"""
    if not config.ENABLE_TRANSLATION or not text.strip():
        return text
        
    if config.DEEPSEEK_API_KEY == "your-deepseek-api-key-here":
        return text

    if _translation_on_cooldown():
        logger.debug("[CrossPlatform] 翻译服务冷却中，直接返回原文")
        return text
    
    lang_name = "中文" if target_lang == "zh-CN" else "英文"
    
    context_ref = ""
    if channel_id > 0:
        context = get_translation_context(channel_id, direction)
        if context:
            context_ref = "\n\n参考最近的翻译：\n"
            for i, ctx in enumerate(context[-5:], 1):
                context_ref += f"{i}. 原文: {ctx['original'][:100]}\n   译文: {ctx['translated'][:100]}\n"
    
    system_prompt = f"""你是一个专业的翻译助手。请将以下文本翻译成{lang_name}。
只返回翻译后的文本，不要添加任何解释、注释或其他内容。避免翻译出仇视言论以及违反中国大陆相关法律法规的内容。如果有，请在翻译后有敏感的词语中把文本替换成井号（#）
保持原文的语气和格式。如果文本已经是目标语言，直接返回原文。{context_ref}"""
    
    messages = [{"role": "user", "content": text}]
    
    try:
        from openai import OpenAI

        global _sync_client
        if _sync_client is None:
            _sync_client = OpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_API_URL.replace("/chat/completions", ""),
                timeout=TRANSLATION_TIMEOUT,
                max_retries=TRANSLATION_RETRIES,
                http_client=httpx.Client(
                    trust_env=False,
                    timeout=TRANSLATION_TIMEOUT,
                ),
            )
        client = _sync_client
        
        response = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            temperature=0.3,
            max_tokens=4000
        )
        
        translated_text = response.choices[0].message.content
        if translated_text:
            translated_text = translated_text.strip()
            _record_translation_success()
            if channel_id > 0:
                add_translation_context(channel_id, direction, text, translated_text)
            return translated_text
        return text
            
    except Exception as e:
        _record_translation_failure()
        logger.error(f"[CrossPlatform] 同步翻译失败: {type(e).__name__}: {e}")
        return text
