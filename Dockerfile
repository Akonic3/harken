# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HARKEN_DB=/data/harken.db

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip pip install . \
    && addgroup --system harken \
    && adduser --system --ingroup harken harken \
    && mkdir -p /data \
    && chown harken:harken /data

USER harken
EXPOSE 8042

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8042'), timeout=3)"

# PaaS hosts (Railway, Render, Fly) inject $PORT; default to 8042 elsewhere.
CMD ["sh", "-c", "exec harken serve --host 0.0.0.0 --port ${PORT:-8042}"]
