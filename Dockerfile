# syntax=docker/dockerfile:1

# ─── 构建阶段 ───────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --prefix=/install .

# ─── 运行阶段 ───────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOA_HOST=0.0.0.0 \
    HOA_PORT=8099 \
    HOA_DB_PATH=/app/data/hoa.db

# 非 root 运行
RUN useradd --create-home --uid 10001 hoa

COPY --from=builder /install /usr/local

WORKDIR /app
RUN mkdir -p /app/data && chown -R hoa:hoa /app
VOLUME ["/app/data"]

USER hoa
EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/api/v1/meta', timeout=4).status==200 else 1)"

CMD ["hoa-api", "serve"]
