# --- build the PWA -----------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- runtime -----------------------------------------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    GA_DATA_DIR=/data

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev

COPY backend/app ./app
COPY --from=web /web/dist ./app/static

# Fails the build if the OCR engine can't start offline with its bundled models.
RUN python -m app.receipts.warmup

RUN useradd --system --uid 1000 --home-dir /data app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

# TLS is terminated in front of the app (Caddy, Tailscale Serve, ...), so trust the
# proxy's X-Forwarded-* headers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
