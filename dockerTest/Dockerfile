# 1. 选择基础镜像：从 Docker Hub 拉取一个包含 Python 3.9 的轻量级 Linux 环境
#    使用 "-slim" 版本可以在满足大部分需求的同时，显著减小最终镜像的体积 [citation:3][citation:7]
FROM python:3.9-slim

# 2. 设置工作目录：容器内部将使用 /app 作为主目录
#    后续的命令（如 COPY, RUN, CMD）都会在这个目录下执行 [citation:2][citation:9]
WORKDIR /app

# 3. 复制依赖清单并安装依赖：
#    先单独复制 requirements.txt，是为了利用 Docker 的缓存机制。
#    如果 requirements.txt 没变，下次构建时会直接使用缓存的依赖安装层，速度飞快 [citation:4][citation:7]
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 复制项目代码：
#    将当前目录（你的项目文件夹）下的所有文件，复制到容器的 /app 目录下 [citation:2][citation:7]
COPY . .

# 5. 声明容器运行时监听的端口（如果你的程序是 Web 服务，如 Flask/FastAPI）
#    这只是一个声明，实际映射仍需在 docker run 时用 -p 参数指定 [citation:3][citation:9]
EXPOSE 5000

# 6. 定义容器启动时的默认执行命令：
#    当容器启动时，运行 python app.py [citation:3][citation:9]
CMD ["python", "test.py"]