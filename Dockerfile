FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.12-slim-bookworm AS backend
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src/ ./src/
RUN uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python \
    && useradd --uid 10001 --user-group --home-dir /sandbox/home --shell /bin/bash omt \
    && install -d -m 0700 -o omt -g omt /sandbox/home /sandbox/home/.omt /sandbox/workspace
ENV HOME=/sandbox/home \
    PATH="/app/backend/.venv/bin:${PATH}"
# OMT 的文件和 Bash 工具使用 API 进程的 cwd；不在应用代码目录执行。
WORKDIR /sandbox/workspace
USER omt
CMD ["omt-api"]

FROM node:22-bookworm-slim AS web
WORKDIR /app/frontend
RUN chown node:node /app/frontend
COPY --chown=node:node frontend/package.json frontend/package-lock.json ./
USER node
RUN npm ci --no-audit --no-fund
COPY --chown=node:node frontend/next.config.ts frontend/next-env.d.ts frontend/postcss.config.mjs frontend/tsconfig.json ./
COPY --chown=node:node frontend/src/ ./src/
ENV NEXT_TELEMETRY_DISABLED=1
# 镜像不挂载源码；预先构建，避免开发模式的热更新握手阻塞浏览器初始化。
RUN npm run build
# 容器内监听以接收端口转发；仍仅供可信本机测试，宿主机绑定由 Compose 限制。
CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
