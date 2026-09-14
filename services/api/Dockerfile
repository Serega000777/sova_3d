# Build context is `services/` (see infra/docker-compose.yml) so the worker library and the
# geometry kernel sources are reachable.
# Targets: `api` (default, no compute deps) and `worker` (api + physical-ai-worker + OCCT kernel).

# --- geometry kernel (C++/OCCT), built on the same Debian release as python:3.13-slim -------
FROM debian:trixie-slim AS geometry-build
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::http::Pipeline-Depth "0";\n' > /etc/apt/apt.conf.d/99network
RUN apt-get update && apt-get install -y --no-install-recommends       build-essential cmake ninja-build nlohmann-json3-dev libtbb-dev libfontconfig-dev       libocct-foundation-dev libocct-modeling-data-dev libocct-modeling-algorithms-dev       libocct-data-exchange-dev     && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY geometry .
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPHYSICAL_AI_BUILD_TESTS=OFF     && cmake --build build

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/api

FROM base AS api
COPY api/pyproject.toml api/uv.lock ./
COPY worker/pyproject.toml /app/worker/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-project --no-install-package physical-ai-worker
COPY api/app ./app
COPY api/alembic ./alembic
COPY api/alembic.ini ./
RUN uv sync --frozen --no-dev --no-install-package physical-ai-worker
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM api AS worker
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::http::Pipeline-Depth "0";\n' > /etc/apt/apt.conf.d/99network
# util-linux provides `unshare` for the parser sandbox's network isolation.
RUN apt-get update && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY worker /app/worker
RUN uv sync --frozen --no-dev --extra worker
CMD ["uv", "run", "--no-sync", "python", "-m", "app.jobs"]
