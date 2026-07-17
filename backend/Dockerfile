# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install --requirement requirements.txt

FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PORT=8000

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app backend/alembic.ini ./alembic.ini
COPY --chown=app:app backend/alembic ./alembic
COPY --chown=app:app backend/app ./app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; from urllib.parse import urlsplit; host=urlsplit(os.getenv('BACKEND_URL','http://localhost:8000')).netloc; request=urllib.request.Request('http://127.0.0.1:8000/readyz',headers={'Host':host}); urllib.request.urlopen(request,timeout=3)" || exit 1

# One process per container keeps the in-process snapshot worker deterministic.
# Scale with additional containers only after moving that worker to a dedicated service.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
