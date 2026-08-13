# -*- coding: utf-8 -*-
import asyncio
import docker
from docker.tls import TLSConfig
from docker.types import LogConfig
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from neobot.core.utils.logger import logger

class CodeExecutor:
    """
    代码执行引擎，负责管理一个异步任务队列和并发的 Docker 容器执行。
    """
    def __init__(self, config: Any):
        """
        初始化代码执行引擎。
        :param config: 从 config_loader.py 加载的全局配置对象。
        """
        self.bot: Any = None  # Bot 实例将在 WS 连接成功后动态注入
        self.task_queue: asyncio.Queue = asyncio.Queue()
        
        # 从传入的配置中读取 Docker 相关设置
        docker_config = config.docker
        self.docker_base_url = docker_config.base_url
        self.sandbox_image = docker_config.sandbox_image
        self.timeout = docker_config.timeout
        concurrency = docker_config.concurrency_limit
        
        self.concurrency_limit = asyncio.Semaphore(concurrency)
        self.docker_client = None
        # 专用线程池：Docker 容器执行是阻塞操作，且超时后线程仍会继续运行，
        # 使用独立线程池可避免占满默认线程池（否则其他 run_in_executor 任务会被饿死）
        self._executor = ThreadPoolExecutor(
            max_workers=max(concurrency, 1),
            thread_name_prefix="neobot-code-exec",
        )

        logger.info("[CodeExecutor] 初始化 Docker 客户端...")
        try:
            if self.docker_base_url:
                # 如果配置了远程 Docker 地址，则使用 TLS 选项进行连接
                tls_config = None
                if docker_config.tls_verify:
                    tls_config = TLSConfig(
                        ca_cert=docker_config.ca_cert_path,
                        client_cert=(docker_config.client_cert_path, docker_config.client_key_path),
                        verify=True
                    )
                self.docker_client = docker.DockerClient(base_url=self.docker_base_url, tls=tls_config)
            else:
                # 否则，使用默认的本地环境连接
                self.docker_client = docker.from_env()

            # 检查 Docker 服务是否可用
            self.docker_client.ping()
            logger.success("[CodeExecutor] Docker 客户端初始化成功，服务连接正常。")
        except docker.errors.DockerException as e:
            self.docker_client = None
            logger.error(f"无法连接到 Docker 服务，请检查 Docker 是否正在运行: {e}")
        except Exception as e:
            self.docker_client = None
            logger.error(f"初始化 Docker 客户端时发生未知错误: {e}")

    async def add_task(self, code: str, callback: Callable[[str], asyncio.Future]):
        """
        将代码执行任务添加到队列中。
        :param code: 待执行的 Python 代码字符串。
        :param callback: 执行完毕后用于回复结果的回调函数。
        :raises RuntimeError: 如果 Docker 客户端未初始化。
        """
        if not self.docker_client:
            logger.warning("[CodeExecutor] 尝试添加任务，但 Docker 客户端未初始化。任务被拒绝。")
            # 这里可以选择抛出异常，或者直接调用回调返回错误信息
            # 为了用户体验，我们构造一个错误结果并直接调用回调（如果可能）
            # 但由于 callback 返回 Future，这里简单起见，我们记录日志并抛出异常
            raise RuntimeError("Docker环境未就绪，无法执行代码。")

        task = {"code": code, "callback": callback}
        await self.task_queue.put(task)
        logger.info(f"[CodeExecutor] 新的代码执行任务已入队 (队列当前长度: {self.task_queue.qsize()})。")

    async def worker(self):
        """
        后台工作者，不断从队列中取出任务并执行。
        """
        if not self.docker_client:
            logger.error("[CodeExecutor] Worker 无法启动，因为 Docker 客户端未初始化。")
            return

        logger.info("[CodeExecutor] 代码执行 Worker 已启动，等待任务...")
        while True:
            task = await self.task_queue.get()
            
            logger.info("[CodeExecutor] 开始处理代码执行任务。")
            
            async with self.concurrency_limit:
                result_message = ""
                try:
                    loop = asyncio.get_running_loop()
                    
                    # 使用 asyncio.wait_for 实现超时控制
                    # （超时后 run_in_executor 的线程仍会在专用线程池中继续跑完，
                    #   不占用默认线程池，避免影响其他异步任务）
                    result_bytes = await asyncio.wait_for(
                        loop.run_in_executor(
                            self._executor,  # 专用线程池，避免阻塞默认线程池
                            self._run_in_container,
                            task['code']
                        ),
                        timeout=self.timeout
                    )
                    
                    output = result_bytes.decode('utf-8').strip()
                    result_message = output if output else "代码执行完毕，无输出。"
                    logger.success("[CodeExecutor] 任务成功执行。")
                    
                except docker.errors.ImageNotFound:
                    logger.error(f"[CodeExecutor] 镜像 '{self.sandbox_image}' 不存在！")
                    result_message = f"执行失败：沙箱基础镜像 '{self.sandbox_image}' 不存在，请联系管理员构建。"
                except docker.errors.ContainerError as e:
                    # 确保 stderr 是字符串
                    error_output = e.stderr.decode('utf-8').strip() if isinstance(e.stderr, bytes) else e.stderr.strip()
                    result_message = f"代码执行出错:\n{error_output}"
                    logger.warning(f"[CodeExecutor] 代码执行时发生错误: {error_output}")
                except docker.errors.APIError as e:
                    logger.error(f"[CodeExecutor] Docker API 错误: {e}")
                    result_message = "执行失败：与 Docker 服务通信时发生错误，请检查服务状态。"
                except asyncio.TimeoutError:
                    result_message = f"执行超时 (超过 {self.timeout} 秒)。"
                    logger.warning("[CodeExecutor] 任务执行超时。")
                except Exception as e:
                    logger.exception(f"[CodeExecutor] 执行 Docker 任务时发生未知严重错误: {e}")
                    result_message = "执行引擎发生内部错误，请联系管理员。"
                
                # 调用回调函数回复结果
                try:
                    await task['callback'](result_message)
                except Exception as callback_error:
                    logger.error(f"[CodeExecutor] 执行回调函数时发生错误: {callback_error}")
                    # 即使回调失败，也要确保任务被标记为完成

            self.task_queue.task_done()

    def _run_in_container(self, code: str) -> bytes:
        """
        同步函数：在 Docker 容器中运行代码。
        此函数通过手动管理容器生命周期来提高稳定性。
        """
        if self.docker_client is None:
            raise docker.errors.DockerException("Docker client is not initialized.")

        container = None
        try:
            # 1. 创建容器
            container = self.docker_client.containers.create(
                image=self.sandbox_image,
                command=["python", "-c", code],
                mem_limit='128m',
                cpu_shares=512,
                network_disabled=True,
                log_config=LogConfig(type='json-file', config={'max-size': '1m'}),
            )
            # 2. 启动容器
            container.start()
            
            # 3. 等待容器执行完成
            # 主超时由 asyncio.wait_for 控制，这里的 timeout 是一个额外的保险
            result = container.wait(timeout=self.timeout + 5)
            
            # 4. 获取日志
            stdout = container.logs(stdout=True, stderr=False)
            stderr = container.logs(stdout=False, stderr=True)

            # 5. 检查退出码，如果不为 0，则手动抛出 ContainerError
            if result.get('StatusCode', 0) != 0:
                # 确保 stderr 是字符串
                error_message = stderr.decode('utf-8') if isinstance(stderr, bytes) else stderr
                raise docker.errors.ContainerError(
                    container, result['StatusCode'], f"python -c '{code}'", self.sandbox_image, error_message
                )
            
            return stdout

        finally:
            # 6. 确保容器总是被移除
            if container:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    # 如果容器因为某些原因已经消失，也沒关系
                    pass
                except Exception as e:
                    logger.error(f"[CodeExecutor] 强制移除容器 {container.id} 时失败: {e}")

def initialize_executor(config: Any):
    """
    初始化并返回一个 CodeExecutor 实例。
    """
    return CodeExecutor(config)

async def run_in_thread_pool(sync_func, *args, **kwargs):
    """
    在线程池中运行同步阻塞函数，以避免阻塞 asyncio 事件循环。
    :param sync_func: 同步函数
    :param args: 位置参数
    :param kwargs: 关键字参数
    :return: 同步函数的返回值
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: sync_func(*args, **kwargs))
