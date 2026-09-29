# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- сборка ---
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels .

# ---------------------------------------------------------------- рантайм ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    pip install /wheels/*.whl \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin relay

# Непривилегированный пользователь; в compose ФС монтируется только на чтение.
USER 10001
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=2)"]

# Миграции накатывает сам шлюз при старте.
ENTRYPOINT ["tg-relay"]
CMD ["serve"]
