# Stage 1: build the Next.js static export
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime serving API + static frontend
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Dependencies first (cache-friendly)
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --frozen --no-dev

# Frontend static export (Next.js `output: 'export'` -> out/)
COPY --from=frontend-build /frontend/out ./static

ENV PATH="/app/.venv/bin:$PATH" \
    FINALLY_DB_PATH=/app/db/finally.db \
    FINALLY_STATIC_DIR=/app/static
RUN mkdir -p /app/db
VOLUME ["/app/db"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
