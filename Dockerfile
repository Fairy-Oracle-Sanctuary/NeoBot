# 主程序镜像：NeoBot QQ 机器人
# 基础镜像使用 Python 3.11（代码使用了 tomllib，需要 3.11+）
FROM python:3.11-slim

# 环境变量：时区、UTF-8、日志即时输出
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8

# 系统依赖：
#   - ffmpeg        B站解析器 / 希腊字母插件 视频图片处理
#   - nodejs        osu! 插件难度估算器（ts_oma node_bridge）
#   - fonts-noto-cjk 帮助图片、天气、osu 难度图等生成中文图片需要
#   - tzdata        时区数据
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        nodejs \
        fonts-noto-cjk \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷贝依赖清单，利用 Docker 构建缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # 安装 Playwright Chromium 及其系统依赖
    && python -m playwright install --with-deps chromium \
    && rm -rf /root/.cache/pip

# 拷贝代码（config.toml 含敏感凭据，不放入镜像，运行期通过 volume 挂载）
COPY main.py cli.py config.example.toml ./
COPY src ./src
COPY scripts ./scripts

# 运行期需要的数据目录（admin.json / permissions.json 会被运行时写入）
RUN mkdir -p logs /app/src/neobot/data
ARG COMMIT_SHA=unknown
RUN echo "${COMMIT_SHA}" > /app/commit-sha
# 反向 WebSocket 3002 / 本地文件服务器 3003
EXPOSE 3002 3003

CMD ["python", "main.py"]
