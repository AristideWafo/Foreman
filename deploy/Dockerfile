# syntax=docker/dockerfile:1.7

# --- Frontend ---------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# --- Backend (dépendances) --------------------------------------------------
FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

# --- Image finale -----------------------------------------------------------
FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home foreman
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /frontend/dist /app/static
COPY catalog/ /app/catalog/
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
ARG APP_VERSION=dev
ENV PATH="/app/.venv/bin:$PATH" FOREMAN_STATIC_DIR=/app/static PYTHONUNBUFFERED=1 FOREMAN_VERSION=$APP_VERSION
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "--factory", "foreman.surfaces.web.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "5"]
