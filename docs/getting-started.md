# 快速上手

## 1. 你需要准备

*   **Python 3.11+**（推荐 3.12+；3.14 可选开启 JIT / 无 GIL 模式）
*   **Git**：拉取代码
*   **Redis**：缓存和权限管理，需要单独安装
*   **Docker** (可选)：用于代码沙箱执行（code_py插件）
*   **OneBot v11 客户端**：机器人本体，推荐用 [NapCatQQ](https://github.com/NapNeko/NapCatQQ)

> 不想折腾环境？直接用 Docker 一键部署，见 [生产部署](deployment.md) 第 7 节。

## 2. 搭环境

### a. 克隆代码

```bash
git clone https://github.com/Fairy-Oracle-Sanctuary/NeoBot.git
cd NeoBot
```

### b. 创建虚拟环境

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3.11 -m venv venv   # 或 python3.12 / python3.14
source venv/bin/activate
```

看到命令行前面多了个 `(venv)`，就说明你进来了。

### c. 安装依赖

```bash
pip install -r requirements.txt
```

### d. 安装 Playwright 依赖

```bash
playwright install chromium
```

### e. 编译核心 (可选，但强烈建议)

想让你的代码更快？把它的核心代码编译成 C 扩展（Mypyc AOT）。

```bash
python scripts/compile_machine_code.py
```
*注：Windows 上可能需要装个 Visual Studio Build Tools，Linux 上需要 GCC。编译失败也别慌，跳过就行，不影响运行。*

## 3. 第一次

### a. 修改配置

项目首次启动时会读取根目录的 `config.toml`；若不存在，会从
`config.example.toml` 自动生成。复制一份再编辑：

```bash
cp config.example.toml config.toml
```

关键配置如下：

```toml
[napcat_ws]
# 你的 OneBot 地址
# 我们用的是正向连接，也就是 Bot 主动去连 OneBot
uri = "ws://127.0.0.1:3001"
token = ""

# 当然你也可以配置逆向连接（NapCat 主动连 Bot）
[reverse_ws]
enabled = false          # 是否启用
host = "0.0.0.0"         # 监听地址
port = 3002              # 监听端口
token = ""               # 连接鉴权 Bearer token，建议设置

[redis]
host = "127.0.0.1"
port = 6379
db = 0
password = ""            # 有密码就填

# MySQL 配置（必填，用于持久化存储）
[mysql]
host = "127.0.0.1"       # 改成你的 MySQL 主机
port = 3306              # 端口
user = "neobot"          # 用户名
password = "请改成强密码"  # 密码
db = "neobot"            # 数据库名称
```

把 `uri` 改成你自己的 OneBot 地址，并按需填写 Redis / MySQL 凭据。

> 敏感配置也可以通过环境变量覆盖（如 `MYSQL_PASSWORD` / `REDIS_PASSWORD` /
> `NAPCAT_WS_URI`），详见 [安全最佳实践](./security-best-practices.md)。

### b. 启动！

一切就绪

```bash
python main.py
```

**可选加速模式（仅 Python 3.14）**：

```bash
# 开启 JIT 编译（提升运行时性能 2-5 倍）
python -X jit main.py

# 开启 JIT + 无全局锁（GIL-free）模式，多线程真正并行执行
python -X jit -X gil=0 main.py
```

> 3.11 / 3.12 直接 `python main.py` 即可，无需加任何参数。

如果你看到日志刷出来，最后显示 "连接成功！"，恭喜，你成功了！

现在，试着给你的机器人发个 `/help` 看看会返回什么东西
