# Build context is `services/` (see infra/docker-compose.yml) so the worker library and the
# geometry kernel sources are reachable.
# Targets: `api` (default, no compute deps), `worker` (api + physical-ai-worker + OCCT kernel)
# and `test` (worker + test suites).

# --- geometry kernel (C++/OCCT), built on the same Debian release as python:3.13-slim -------
FROM debian:trixie-slim AS geometry-build
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::http::Pipeline-Depth "0";\n' > /etc/apt/apt.conf.d/99network
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build nlohmann-json3-dev libtbb-dev libfontconfig-dev \
      libocct-foundation-dev libocct-modeling-data-dev libocct-modeling-algorithms-dev \
      libocct-data-exchange-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY geometry .
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPHYSICAL_AI_BUILD_TESTS=OFF \
    && cmake --build build

# --- python base ------------------------------------------------------------------------------
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/api

# --- python dependencies of the api, shared by both images -------------------------------------
FROM base AS deps
COPY api/pyproject.toml api/uv.lock ./
COPY worker/pyproject.toml /app/worker/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-project --no-install-package physical-ai-worker

# --- api: orchestration only, no compute dependencies -------------------------------------------
FROM deps AS api
COPY api/app ./app
COPY api/alembic ./alembic
COPY api/alembic.ini ./
RUN uv sync --frozen --no-dev --no-install-package physical-ai-worker
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# --- worker: api + compute library + OCCT kernel + sandbox tooling -----------------------------
# System packages first (they rarely change), then the heavy compute wheels (torch, shap-e),
# then source code: an edit to api/ or worker/ rebuilds two small layers and never re-runs
# apt or the wheel downloads. UV_NO_CACHE keeps uv's download cache out of the layers — it
# would otherwise ship every wheel twice (archive + installed copy) in the image.
FROM base AS worker
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::http::Pipeline-Depth "0";\n' > /etc/apt/apt.conf.d/99network
# util-linux provides `unshare` for the parser sandbox's network isolation; the OCCT runtime
# libraries back the geometry-service binary built above; git is how uv fetches shap-e and
# CLIP (F-019), which are pinned to commits, not published to PyPI.
RUN apt-get update && apt-get install -y --no-install-recommends util-linux git ca-certificates \
      libocct-foundation-7.8 libocct-modeling-data-7.8 libocct-modeling-algorithms-7.8 \
      libocct-data-exchange-7.8 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=geometry-build /src/build/geometry-service /usr/local/bin/geometry-service
COPY api/pyproject.toml api/uv.lock ./
COPY worker/pyproject.toml /app/worker/pyproject.toml
RUN uv sync --frozen --no-dev --extra worker --no-install-project --no-install-package physical-ai-worker
COPY api/app ./app
COPY api/alembic ./alembic
COPY api/alembic.ini ./
COPY worker /app/worker
RUN uv sync --frozen --no-dev --extra worker
CMD ["uv", "run", "--no-sync", "python", "-m", "app.jobs"]

# --- test: worker image + dev dependencies + test suites, for containerized CI --------------
FROM worker AS test
COPY api/tests ./tests
COPY worker/tests /app/worker/tests
RUN uv sync --frozen --extra worker
CMD ["uv", "run", "--no-sync", "pytest", "-q", "-rs", "tests"]
