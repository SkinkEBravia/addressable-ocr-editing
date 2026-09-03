# 实验容器：离线依赖全预装，代码经 bind mount 即时生效（见 README「容器」节）。
# 构建：docker build -t bdpc-exp .
# 运行：见 README；.env 不进镜像，运行时 --env-file 注入。

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# venv 放在 /opt（挂载 /app 时不被覆盖；也不污染宿主 .venv）
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 依赖层（变动少，吃缓存）：锁文件 + workspace 成员 + 项目骨架
COPY pyproject.toml uv.lock .python-version README.md ./
COPY related_source related_source
COPY src src
RUN uv sync --frozen

# 其余内容（运行时通常被 bind mount 覆盖）
COPY configs configs
COPY datasets datasets
COPY tests tests
COPY scripts scripts

CMD ["bash"]
