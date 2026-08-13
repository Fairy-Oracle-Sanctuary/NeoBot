import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import docker
from neobot.core.utils.executor import CodeExecutor

# Mock 配置对象
@pytest.fixture
def mock_config():
    config = MagicMock()
    config.docker.base_url = None
    config.docker.sandbox_image = "sandbox:latest"
    config.docker.timeout = 5
    config.docker.concurrency_limit = 2
    config.docker.tls_verify = False
    return config

@pytest.fixture
def mock_docker_client():
    with patch("docker.from_env") as mock_from_env:
        client = MagicMock()
        mock_from_env.return_value = client
        yield client

@pytest.fixture
def executor(mock_config, mock_docker_client):
    return CodeExecutor(mock_config)

def test_init_success(mock_config, mock_docker_client):
    """测试初始化成功"""
    executor = CodeExecutor(mock_config)
    assert executor.docker_client is not None
    mock_docker_client.ping.assert_called_once()

def test_init_docker_error(mock_config):
    """测试初始化 Docker 失败"""
    with patch("docker.from_env", side_effect=docker.errors.DockerException("Docker error")):
        executor = CodeExecutor(mock_config)
        assert executor.docker_client is None

def test_init_remote_docker(mock_config):
    """测试初始化远程 Docker"""
    mock_config.docker.base_url = "tcp://1.2.3.4:2375"
    with patch("docker.DockerClient") as mock_client_cls:
        executor = CodeExecutor(mock_config)
        mock_client_cls.assert_called_once()
        assert executor.docker_client is not None

@pytest.mark.asyncio
async def test_add_task_success(executor):
    """测试添加任务成功"""
    callback = AsyncMock()
    await executor.add_task("print('hello')", callback)
    assert executor.task_queue.qsize() == 1

@pytest.mark.asyncio
async def test_add_task_no_docker(mock_config):
    """测试 Docker 未初始化时添加任务"""
    with patch("docker.from_env", side_effect=docker.errors.DockerException):
        executor = CodeExecutor(mock_config)
        callback = AsyncMock()
        with pytest.raises(RuntimeError, match="Docker环境未就绪"):
            await executor.add_task("print('hello')", callback)

@pytest.mark.asyncio
async def test_worker_success(executor):
    """测试 Worker 成功处理任务"""
    # Mock _run_in_container
    executor._run_in_container = MagicMock(return_value=b"hello")
    
    callback = AsyncMock()
    await executor.add_task("print('hello')", callback)
    
    # 启动 worker 并在处理完一个任务后取消
    worker_task = asyncio.create_task(executor.worker())
    
    # 等待队列为空
    await executor.task_queue.join()
    
    # 验证结果
    callback.assert_called_with("hello")
    
    # 取消 worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_worker_timeout(executor):
    """测试 Worker 处理任务超时"""
    # Mock _run_in_container to sleep longer than timeout
    async def slow_run(*args):
        await asyncio.sleep(0.2)
        return b""
    
    # 我们不能直接 mock 同步方法让它异步 sleep，
    # 因为 run_in_executor 会在线程中运行它。
    # 这里我们 mock asyncio.wait_for 抛出 TimeoutError 可能会更容易，
    # 但为了测试完整流程，我们可以让 _run_in_container 阻塞。
    
    # 实际上，我们可以 mock _run_in_container 抛出 asyncio.TimeoutError 
    # (虽然它是在线程中运行，但 wait_for 会抛出这个异常)
    # 不，wait_for 抛出 TimeoutError 是因为 future 没有在时间内完成。
    
    # 让我们简单地 mock _run_in_container 并让 wait_for 超时
    executor.timeout = 0.01
    executor._run_in_container = MagicMock(side_effect=lambda x: time.sleep(0.05))
    
    import time
    
    callback = AsyncMock()
    await executor.add_task("print('hello')", callback)
    
    worker_task = asyncio.create_task(executor.worker())
    await executor.task_queue.join()
    
    callback.assert_called_with(f"执行超时 (超过 {executor.timeout} 秒)。")
    
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_worker_docker_errors(executor):
    """测试 Worker 处理 Docker 错误"""
    # ImageNotFound
    executor._run_in_container = MagicMock(side_effect=docker.errors.ImageNotFound("Image not found"))
    callback = AsyncMock()
    await executor.add_task("code", callback)
    
    worker_task = asyncio.create_task(executor.worker())
    await executor.task_queue.join()
    callback.assert_called_with(f"执行失败：沙箱基础镜像 '{executor.sandbox_image}' 不存在，请联系管理员构建。")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    # ContainerError
    executor._run_in_container = MagicMock(side_effect=docker.errors.ContainerError(
        "container", 1, "cmd", "image", b"Error output"
    ))
    callback = AsyncMock()
    await executor.add_task("code", callback)
    
    worker_task = asyncio.create_task(executor.worker())
    await executor.task_queue.join()
    callback.assert_called_with("代码执行出错:\nError output")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

def test_run_in_container_success(executor):
    """测试 _run_in_container 成功"""
    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.side_effect = [b"output", b""] # stdout, stderr
    
    executor.docker_client.containers.create.return_value = mock_container
    
    result = executor._run_in_container("print('hello')")
    
    assert result == b"output"
    mock_container.start.assert_called_once()
    mock_container.remove.assert_called_with(force=True)

def test_run_in_container_failure(executor):
    """测试 _run_in_container 失败（非零退出码）"""
    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 1}
    mock_container.logs.side_effect = [b"", b"Error"] # stdout, stderr
    
    executor.docker_client.containers.create.return_value = mock_container
    
    with pytest.raises(docker.errors.ContainerError):
        executor._run_in_container("bad code")
    
    mock_container.remove.assert_called_with(force=True)

def test_run_in_container_no_client(executor):
    """测试 _run_in_container 无客户端"""
    executor.docker_client = None
    with pytest.raises(docker.errors.DockerException):
        executor._run_in_container("code")
