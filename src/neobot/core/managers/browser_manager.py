"""
浏览器管理器模块

负责管理全局唯一的 Playwright 浏览器实例，避免频繁启动/关闭浏览器的开销。
"""
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Browser, Playwright, Page
from ..utils.logger import logger
from ..utils.singleton import Singleton

class BrowserManager(Singleton):
    """
    浏览器管理器（异步单例）
    """
    _playwright: Optional[Playwright] = None
    _browser: Optional[Browser] = None
    _page_pool: Optional[asyncio.Queue] = None
    _pool_size: int = 3
    _page_use_count: int = 0
    _max_page_uses: int = 50

    def __init__(self):
        """
        初始化浏览器管理器
        """
        super().__init__()

    async def initialize(self):
        """
        初始化 Playwright 和 Browser
        """
        if self._browser is None:
            try:
                logger.info("正在启动无头浏览器...")
                self._playwright = await async_playwright().start()
                # 启动 Chromium，headless=True 表示无头模式
                self._browser = await self._playwright.chromium.launch(headless=True)
                logger.success("无头浏览器启动成功！")
            except Exception as e:
                logger.exception(f"无头浏览器启动失败: {e}")
                self._browser = None

    async def init_pool(self, size: int = 3):
        """
        初始化页面池
        """
        if not self._browser:
            await self.initialize()
            
        if not self._browser:
            logger.error("浏览器初始化失败，无法创建页面池")
            return

        self._pool_size = size
        self._page_pool = asyncio.Queue(maxsize=size)
        
        logger.info(f"正在初始化页面池 (大小: {size})...")
        for i in range(size):
            try:
                page = await self._browser.new_page()
                await self._page_pool.put(page)
            except Exception as e:
                logger.error(f"创建页面池页面 {i+1} 失败: {e}")
        
        logger.success(f"页面池初始化完成，当前可用页面: {self._page_pool.qsize()}")

    async def get_page(self) -> Optional[Page]:
        """
        从池中获取一个页面。如果池未初始化或为空，则尝试创建一个新页面（不入池）。
        """
        if self._page_pool and not self._page_pool.empty():
            try:
                page = self._page_pool.get_nowait()
                # 简单的健康检查
                if page.is_closed():
                    logger.warning("检测到池中页面已关闭，重新创建一个...")
                    if self._browser:
                        page = await self._browser.new_page()
                    else:
                        return None
                return page
            except asyncio.QueueEmpty:
                pass
        
        # 如果池空了或者没初始化，回退到临时创建
        logger.debug("页面池为空或未初始化，创建临时页面")
        return await self.get_new_page()

    async def release_page(self, page: Page):
        """
        归还页面到池中。如果池已满或未初始化，则关闭页面。
        如果页面使用次数超过阈值，则关闭旧页面并创建新页面。
        """
        if not page or page.is_closed():
            return

        if self._page_pool:
            try:
                BrowserManager._page_use_count += 1
                if BrowserManager._page_use_count >= BrowserManager._max_page_uses:
                    logger.debug(f"页面使用次数已达阈值 ({BrowserManager._max_page_uses})，替换为新页面")
                    BrowserManager._page_use_count = 0
                    await page.close()
                    if self._browser:
                        new_page = await self._browser.new_page()
                        if new_page:
                            self._page_pool.put_nowait(new_page)
                        else:
                            logger.warning("创建新页面失败，保留原页面")
                            self._page_pool.put_nowait(page)
                    else:
                        logger.warning("浏览器未初始化，无法创建新页面")
                    return

                await page.goto("about:blank")
                try:
                    await page.evaluate("""() => {
                        try {
                            if (window.localStorage) window.localStorage.clear();
                            if (window.sessionStorage) window.sessionStorage.clear();
                            if (window.indexedDB && indexedDB.databases) {
                                indexedDB.databases().then(dbs => {
                                    dbs.forEach(db => indexedDB.deleteDatabase(db.name));
                                });
                            }
                            if ('caches' in window) {
                                caches.keys().then(names => names.forEach(name => caches.delete(name)));
                            }
                            if (window.gc) window.gc();
                        } catch (e) {}
                        try {
                            document.write('');
                            document.close();
                        } catch (e) {}
                    }""")
                    context = page.context
                    try:
                        await context.clear_cookies()
                    except Exception:
                        pass
                except Exception as e:
                    logger.debug(f"页面清理时出现非致命错误: {e}")

                self._page_pool.put_nowait(page)
                return
            except asyncio.QueueFull:
                # 页面池已满：关闭页面释放浏览器资源，避免页面泄漏
                await page.close()
                return

        await page.close()

    async def get_new_page(self) -> Optional[Page]:
        """
        获取一个新的页面 (Page)
        
        使用完毕后，调用者应该负责关闭该页面 (await page.close())
        """
        if self._browser is None:
            logger.warning("浏览器尚未初始化，尝试重新初始化...")
            await self.initialize()
            
        if self._browser:
            try:
                return await self._browser.new_page()
            except Exception as e:
                logger.error(f"创建新页面失败: {e}")
                return None
        return None

    async def shutdown(self):
        """
        关闭浏览器和 Playwright
        """
        # 清空页面池
        if self._page_pool:
            while not self._page_pool.empty():
                try:
                    page = self._page_pool.get_nowait()
                    await page.close()
                except (asyncio.QueueEmpty, AttributeError):
                    pass
            self._page_pool = None

        if self._browser:
            await self._browser.close()
            self._browser = None
            logger.info("浏览器已关闭")
            
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
            logger.info("Playwright 已停止")

# 全局浏览器管理器实例
browser_manager = BrowserManager()
