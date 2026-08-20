# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Any, Dict, List

import aiohttp
from neobot.plugin_api import platform_command, image_manager, logger, input_validator, define_plugin
from neobot.models import MessageEvent, MessageSegment
from .resource.city_code import CITY_CODES
# 插件元数据
plugin_manifest = define_plugin(
    name="weather",
    description="查询天气信息，支持中国天气网数据。",
    usage="/天气 [城市代码] - 查询指定城市的天气信息\n例如：/天气 101190207 (南京)",
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


async def get_weather_data(city_code: str) -> Dict[str, Any]:
    """
    获取天气数据

    Args:
        city_code (str): 城市代码

    Returns:
        Dict[str, Any]: 包含城市信息和天气数据的字典
    """
    try:
        url = f"https://www.weather.com.cn/weather/{city_code}.shtml"
        
        # 使用异步 HTTP 客户端
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=HEADERS) as response:
                html_content = await response.text(encoding="utf-8")
        
        # 提取城市信息
        city_info = (
            html_content.split('<a href="http://www.weather.com.cn/forecast/" ')[-1]
            .split("</div>")[0]
            .strip()
        )

        city_parts = []
        city_parts.append(city_info.split("<a>")[-1].split("</a>")[0])

        if city_info.count("_blank") == 1:
            city_parts.append(
                city_info.split("<span>></span>")[-1]
                .replace("</span>", "")
                .replace("<span>", "")
                .strip()
            )
        else:
            additional_parts = (
                city_info.split('target="_blank">')[-1]
                .replace("<span>></span>  <span>", "")
                .replace("</span>", "")
                .split("</a>")
            )
            city_parts.extend(additional_parts)

        city_name = " ".join([part for part in city_parts if part.strip()])

        # 提取天气信息
        weather_data = []
        for i in range(7):
            try:
                weather_info = (
                    html_content.split('<ul class="t clearfix">')[-1]
                    .split('on">')[1]
                    .split("</li>")[i]
                )

                day = weather_info.split("<h1>")[-1].split("</h1>")[0].strip()
                weather = (
                    weather_info.split('<p title="')[-1]
                    .split('" class="wea">')[0]
                    .strip()
                )

                tem = (
                    weather_info.split("<span>")[-1]
                    .split("</i>")[0]
                    .replace("</span>/<i>", " / ")
                    .strip()
                )
                if len(tem) > 10:
                    tem = weather_info.split("<i>")[1].split("</i>")[0].strip()

                wind = weather_info.split('<span title="')
                wind_direction = []
                if len(wind) > 2:
                    for j in range(2):
                        wind_direction.append(
                            wind[j + 1]
                            .split('"></span>')[0]
                            .replace('" class="', " / ")
                        )
                else:
                    wind_direction.append(
                        wind[1].split('"></span>')[0].replace('" class="', " / ")
                    )
                wind_power = weather_info.split("<i>")[-1].split("</i>")[0].strip()

                wind_direction_str = (
                    " / ".join(wind_direction) if wind_direction else "未知"
                )

                weather_data.append(
                    {
                        "day": day,
                        "weather": weather,
                        "temperature": tem,
                        "wind_power": wind_power,
                        "wind_direction": wind_direction_str,
                    }
                )

            except (IndexError, ValueError) as e:
                logger.warning(f"解析第{i + 1}天天气数据失败: {e}")
                continue

        return {
            "city_name": city_name,
            "weather_data": weather_data,
            "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": datetime.now().strftime("%Y年%m月%d日 %H:%M"),
        }

    except Exception as e:
        logger.error(f"获取天气数据失败: {e}")
        return None


@platform_command(["qq", "discord"], "天气")
async def handle_weather(bot, event: MessageEvent, args: List[str]):
    """
    处理天气查询指令

    Args:
        bot: Bot实例
        event: 消息事件
        args: 指令参数
    """
    if not args:
        # 显示支持的城市列表
        city_list = "\n".join(
            [f"{name}: {code}" for name, code in list(CITY_CODES.items())[:10]]
        )
        reply_msg = f"请指定城市名称或城市代码，例如：\n/天气 北京\n/天气 101010100\n\n支持的城市：\n{city_list}\n..."
        await event.reply(reply_msg)
        return

    city_input = args[0].strip()
    
    # 输入验证
    if not input_validator.validate_sql_input(city_input):
        await event.reply("输入包含不安全字符，请重新输入。")
        return
    
    if not input_validator.validate_xss_input(city_input):
        await event.reply("输入包含不安全内容，请重新输入。")
        return

    # 尝试匹配城市名称或直接使用城市代码
    city_code = None
    if city_input in CITY_CODES:
        city_code = CITY_CODES[city_input]
    elif input_validator.nine_digit_pattern.match(city_input):
        city_code = city_input
    else:
        # 尝试模糊匹配城市名称
        for name, code in CITY_CODES.items():
            if city_input in name:
                city_code = code
                break

    if not city_code:
        await event.reply(f"未找到城市 '{city_input}'，请检查城市名称或使用城市代码。")
        return

    # 获取天气数据
    await event.reply("正在查询天气信息，请稍候...")
    weather_info = await get_weather_data(city_code)

    if not weather_info or not weather_info.get("weather_data"):
        await event.reply("获取天气信息失败，请稍后重试。")
        return

    try:
        # 渲染HTML模板为图片
        base64_image = await image_manager.render_template_to_base64(
            "weather.html", weather_info, output_name="weather.png", width=400, height=500
        )

        if base64_image:
            # 发送图片消息
            await event.reply(MessageSegment.image(base64_image))
        else:
            await event.reply("生成天气图片失败，请稍后重试。")

    except Exception as e:
        logger.error(f"渲染天气图片失败: {e}")
        await event.reply("生成天气图片时发生错误，请稍后重试。")
