# services/api

FastAPI orchestration service. Python 3.13, managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                # create .venv and install locked deps
uv run pytest          # tests
uv run ruff check .    # lint
uv run mypy app        # types
uv run uvicorn app.main:create_app --factory --reload --port 8000
```

## Database

Migrations live in `alembic/versions`, written by hand (no autogenerate) so
every constraint and trigger is explicit.

```bash
uv run alembic upgrade head        # uses $DATABASE_URL
uv run alembic downgrade -1
uv run alembic revision -m "short_slug"
```

Integration tests need PostgreSQL: `TEST_DATABASE_URL` (defaults to the compose
instance on 15432, database `physicalai_test`, created on demand). They skip
locally if the DB is unreachable and fail under `CI`.

## Job runner (worker-general)

Long-running work (repair, later exports/analysis) is executed by
`python -m app.jobs`, a loop that claims queued rows from `jobs`
(`FOR UPDATE SKIP LOCKED`), runs the registered handler and commits every
state change so `GET /jobs/{id}` shows live progress. It needs the compute
library: `uv sync --extra worker`. The compose `worker` service builds the
`worker` target of `Dockerfile` (api image + `physical-ai-worker` + `unshare`).

## Operator CLI

```bash
uv run python -m app.cli create-user --email you@example.com --name You
uv run python -m app.cli issue-token --email you@example.com
```
