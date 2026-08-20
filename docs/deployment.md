# 生产环境部署

将 NEO Bot 部署到服务器长期运行，只需要几个额外的步骤。本指南以 Linux 服务器为例。

## 1. 环境准备

### a. 安装 Python

代码基于 `asyncio` + `tomllib`，需要 **Python 3.11+**（推荐 3.12+；3.14 可额外开启
JIT / 无 GIL 模式）。在 Linux 服务器上安装 Python 及开发工具：

```bash
# Ubuntu/Debian（以 3.11 为例，可按需替换为 3.12 / 3.14）
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev gcc

# CentOS/RHEL
sudo yum install python3.11 python3.11-devel gcc
```

> 若使用 Docker 部署（见第 7 节），宿主机无需安装 Python。

### b. 克隆项目并创建虚拟环境

```bash
# 切换到项目目录（或新建）
cd /opt/neobot
git clone https://github.com/Fairy-Oracle-Sanctuary/NeoBot.git .

# 创建虚拟环境（强烈建议）
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
playwright install chromium
```

### c. 编译核心模块（可选但强烈推荐）

为了最大化性能，建议在部署环境上把核心模块编译为 C 扩展（Mypyc AOT）：

```bash
# 确保已激活虚拟环境
python scripts/compile_machine_code.py
```

**注意**：编译产物是平台相关的，必须在目标服务器上执行。详见 [性能优化](core-concepts/performance.md)。

## 2. 进程管理

直接运行 `python main.py` 然后关闭 SSH 会导致 Bot 停止。需要用进程管理器来守护 Bot。

推荐使用 `systemd`（Linux 原生方案）或 `pm2`。

### 方案 A：systemd（推荐）

创建 `/etc/systemd/system/neobot.service` 文件：

```ini
[Unit]
Description=NEO Bot Service
After=network.target redis.service

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/neobot
ExecStart=/opt/neobot/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

然后启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable neobot
sudo systemctl start neobot

# 查看状态
sudo systemctl status neobot

# 查看日志
sudo journalctl -u neobot -f
```

### 方案 B：pm2

如果你习惯用 pm2（Node.js 工具），也可以：

```bash
npm install pm2 -g
```

创建 `ecosystem.config.js`：

```javascript
module.exports = {
  apps : [{
    name   : "neobot",
    script : "main.py",
    interpreter: "/opt/neobot/venv/bin/python",
    max_memory_restart: "512M",
    env: {
      "PYTHONUNBUFFERED": "1"
    },
    error_file: "./logs/pm2-error.log",
    out_file: "./logs/pm2-out.log"
  }]
}
```

启动：

```bash
pm2 start ecosystem.config.js
pm2 logs neobot
pm2 save
pm2 startup
```

## 3. 配置 OneBot 客户端

Bot 使用 **正向 WebSocket 连接**，即 Bot 主动连接 OneBot 实现（如 NapCatQQ）。

在 `config.toml` 中配置：

```toml
[napcat_ws]
# OneBot 客户端的 WebSocket 服务地址
uri = "ws://127.0.0.1:3001"
token = "your_token_here"
reconnect_interval = 5
```

### NapCatQQ 配置示例

在 NapCatQQ 的 `config/onebot11.json` 中，启用正向 WebSocket 服务器：

```json
{
    "ws": {
        "enable": true,
        "host": "127.0.0.1",
        "port": 3001
    },
    "token": "your_token_here"
}
```

然后重启 NapCatQQ，Bot 启动后应该能正常连接。

## 4. 扩展配置

### Redis 连接

确保 Redis 服务运行在可访问的地址，在 `config.toml` 配置：

```toml
[redis]
host = "127.0.0.1"
port = 6379
db = 0
password = "redis_password"  # 如果有密码
```

### Docker 代码沙箱（可选）

若要使用 code_py 插件，需要配置 Docker：

```toml
[docker]
base_url = "unix:///var/run/docker.sock"  # Linux socket
sandbox_image = "python-sandbox:latest"
timeout = 10
concurrency_limit = 5
```

## 5. 监控和日志

### 查看日志

日志文件位于 `logs/` 目录，按日期滚动（如 `logs/2026-08-12.log`），保留最近 7 天：

```bash
# 查看今天的最新日志
tail -f logs/$(date +%F).log
```

### 监控系统资源

使用 systemd 时：

```bash
# 查看内存和 CPU 使用
systemctl status neobot
```

### 重启 Bot

```bash
# systemd
sudo systemctl restart neobot

# pm2
pm2 restart neobot
```

## 6. 常见问题

### Redis 连接失败

检查 Redis 是否运行：

```bash
redis-cli ping  # 应返回 PONG
```

### Playwright 缓存问题

如果更新后图片渲染出现问题，清空 Playwright 缓存：

```bash
rm -rf ~/.cache/ms-playwright
playwright install chromium
```

### 内存持续增长

检查是否有内存泄漏。在 systemd 中添加内存限制：

```ini
[Service]
MemoryLimit=512M
MemoryAccounting=yes
```

## 7. Docker 部署

除 systemd / pm2 之外，也可以将 Bot 打包为 Docker 容器运行。镜像内置了全部运行依赖（Python 3.11、Playwright Chromium、ffmpeg、Node.js、中文字体），宿主机无需安装任何运行时。

### a. 准备配置文件

仓库中已提供示例配置文件 `config.example.toml`。首次部署时将其复制为 `config.toml` 并填写真实凭据：

```bash
cp config.example.toml config.toml
```

**注意**：`config.toml` 含敏感信息（NapCat Token、Redis 密码、Discord Token 等），不应提交到版本库，也不要打进镜像。容器通过 volume 挂载宿主机上的 `config.toml`，请确保权限收紧：

```bash
chmod 600 config.toml
```

### b. 构建并启动

项目根目录已提供 `Dockerfile` 与 `docker-compose.yml`：

```bash
# 构建镜像并后台启动
docker compose up -d --build

# 查看实时日志
docker compose logs -f

# 停止
docker compose down
```

### c. 网络模式说明

容器使用 **host 网络模式**，直接复用宿主机网络。由于 `config.toml` 中的外部依赖（NapCat WS、Redis、MySQL、mcc-service、代理）均配置在 `localhost` / `127.0.0.1`，host 模式下无需修改任何地址即可连接。

> 仅适用于 Linux 宿主机。若需在 macOS / Windows 或跨主机部署，改用 bridge 网络并通过环境变量覆盖连接地址（见 `docker-compose.yml` 内注释），例如：
>
> ```yaml
> environment:
>   - NAPCAT_WS_URI=ws://<宿主机IP>:3001
>   - REDIS_HOST=<宿主机IP>
>   - MYSQL_HOST=<宿主机IP>
> ```
>
> 环境变量覆盖清单见 `src/neobot/core/config_loader.py` 的 `_override_with_env_vars`。

### d. 数据持久化

compose 已挂载以下目录，容器重建后数据不丢失：

| 宿主机路径 | 容器路径 | 说明 |
| --- | --- | --- |
| `./config.toml` | `/app/config.toml` | 敏感配置（只读） |
| `./logs` | `/app/logs` | 运行日志 |
| `./src/neobot/data` | `/app/src/neobot/data` | 权限数据（`admin.json` / `permissions.json`） |

如需启用代码沙箱执行功能（`code_py` 插件），在 `docker-compose.yml` 中取消注释并挂载 Docker socket，且 `[docker]` 配置段保持默认（`base_url` 留空即可）：

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

### e. 镜像内验证

构建后可快速验证运行环境是否就绪：

```bash
# 验证核心依赖可用
docker run --rm neobot:latest node -e "console.log(process.version)"
docker run --rm neobot:latest ffmpeg -version | head -1

# 挂载真实配置并验证加载
docker run --rm -v "$PWD/config.toml:/app/config.toml:ro" \
  neobot:latest python -c "import sys; sys.path.insert(0,'/app/src'); from neobot.core.config_loader import global_config as c; print(c.napcat_ws.uri, c.redis.host)"
```

### f. Docker 常见问题

**容器启动后立即退出**

多为配置校验失败（TOML 语法错误或缺少必填字段）。查看日志定位：

```bash
docker compose logs neobot
```

**Playwright / 浏览器相关插件报错**

镜像已通过 `playwright install --with-deps chromium` 安装 Chromium 及系统依赖。若宿主机 Docker 缓存异常，可重建镜像：

```bash
docker compose build --no-cache
```

**无法连接宿主机上的 NapCat / Redis**

确认使用 host 网络模式，并检查对应服务是否监听在 `127.0.0.1`；或改用 bridge 模式 + 环境变量指定宿主机 IP（见上文 c 节）。
