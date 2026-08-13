"""
图片生成管理器模块

负责管理图片生成相关的逻辑，支持多种渲染引擎（目前支持 Playwright）。
"""
import os
import base64
import tempfile
from typing import Dict, Any, Optional
from jinja2 import Template

from .browser_manager import browser_manager
from ..utils.logger import logger
from ..utils.singleton import Singleton
from ..config_loader import global_config

class ImageManager(Singleton):
    """
    图片生成管理器（单例）
    """

    def __init__(self):
        """
        初始化图片生成管理器
        """
        # 检查是否已经初始化
        if hasattr(self, 'template_dir'):
            return
            
        # 模板目录
        self.template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
        # 临时文件目录 - 使用系统临时目录
        self.temp_dir = os.path.join(tempfile.gettempdir(), "neobot_images")
        os.makedirs(self.temp_dir, exist_ok=True)
        # 模板缓存
        self._template_cache: Dict[str, Template] = {}

    async def render_template(self, template_name: str, data: Dict[str, Any], output_name: str = "output.png", quality: int = 80, image_type: str = "png", width: int = 1920, height: int = 1080) -> Optional[str]:
        """
        使用 Playwright 渲染 Jinja2 模板并保存为图片文件

        Args:
            template_name (str): 模板文件名 (例如 "help.html")
            data (Dict[str, Any]): 传递给模板的数据字典
            output_name (str, optional): 输出文件名. Defaults to "output.png".
            quality (int, optional): JPEG 质量 (0-100). 仅在 image_type 为 jpeg 时有效. Defaults to 80.
            image_type (str, optional): 图片类型 ('png' or 'jpeg'). Defaults to "png".
            width (int, optional): 图片宽度. Defaults to 1920.
            height (int, optional): 图片高度. Defaults to 1080.

        Returns:
            Optional[str]: 生成图片的绝对路径，如果失败则返回 None
        """
        template_path = os.path.join(self.template_dir, template_name)
        if not os.path.exists(template_path):
            logger.error(f"模板文件未找到: {template_path}")
            return None

        try:
            # 1. 渲染 HTML (使用缓存)
            if template_name in self._template_cache:
                template = self._template_cache[template_name]
            else:
                with open(template_path, "r", encoding="utf-8") as f:
                    template_str = f.read()
                template = Template(template_str)
                self._template_cache[template_name] = template
            
            html_content = template.render(**data)

            # 2. 使用浏览器截图
            # 改为从池中获取页面
            page = await browser_manager.get_page()
            if not page:
                logger.error("无法获取浏览器页面")
                return None

            try:
                width = data.get("width", width)
                height = data.get("height", height)
                await page.set_viewport_size({"width": width, "height": height})
                
                # 加载内容
                await page.set_content(html_content)
                await page.wait_for_selector("body")
                
                
                screenshot_args = {
                    'full_page': True, 
                    'type': image_type,
                    'omit_background': False,
                    'scale': 'css'
                }
                if image_type == 'jpeg':
                    screenshot_args['quality'] = quality
                    
                screenshot_bytes = await page.screenshot(**screenshot_args)  # type: ignore
                
            finally:
                # 归还页面到池中，而不是直接关闭
                await browser_manager.release_page(page)

            # 3. 保存文件
            output_path = os.path.join(self.temp_dir, output_name)
            with open(output_path, "wb") as f:
                f.write(screenshot_bytes)
                
            logger.info(f"图片已生成: {output_path} ({len(screenshot_bytes)/1024:.2f} KB)")
            return os.path.abspath(output_path)

        except Exception as e:
            logger.exception(f"渲染模板 {template_name} 失败: {e}")
            return None

    async def render_template_to_base64(self, template_name: str, data: Dict[str, Any], output_name: str = "output.png", quality: int = 80, image_type: str = "png", width: int = 1920, height: int = 1080) -> Optional[str]:
        """
        渲染模板并返回 Base64 编码的图片字符串
        """
        file_path = await self.render_template(template_name, data, output_name, quality, image_type, width=width, height=height)
        if not file_path:
            return None
            
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            
            mime_type = "image/jpeg" if image_type == "jpeg" else "image/png"
            base64_str = base64.b64encode(content).decode("utf-8")
            
            # 记录摘要日志，避免刷屏
            log_message = f"Base64 图片已生成 (MIME: {mime_type}, Size: {len(base64_str)/1024:.2f} KB, Preview: {base64_str[:30]}...{base64_str[-30:]})"
            logger.debug(log_message)
            
            return f"data:{mime_type};base64," + base64_str
        except Exception as e:
            logger.error(f"读取图片文件失败: {e}")
            return None

# 全局图片管理器实例
image_manager = ImageManager()
