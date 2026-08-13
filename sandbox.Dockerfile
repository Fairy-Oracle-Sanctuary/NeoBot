# 使用一个轻量级的 Python 官方镜像作为基础
FROM python:3.11-slim

# 创建一个工作目录，用于存放和执行用户的代码
WORKDIR /sandbox


# 默认的启动命令是 python，这样容器启动时可以直接执行 .py 文件
CMD ["python"]
