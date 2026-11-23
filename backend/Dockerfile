# syntax=docker/dockerfile:1.7
# Tradeo API image. Multi-stage: build a venv, copy it into a slim runtime
# that runs as an unprivileged user with no build tooling.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production
RUN groupadd --system --gid 10001 tradeo \
 && useradd --system --uid 10001 --gid tradeo --no-create-home --shell /usr/sbin/nologin tradeo
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=root:root app ./app
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root migrations ./migrations
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header"]
