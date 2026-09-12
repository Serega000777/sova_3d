# services/api

FastAPI orchestration service. Python 3.13, managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                # create .venv and install locked deps
uv run pytest          # tests
uv run ruff check .    # lint
uv run mypy app        # types
uv run uvicorn app.main:create_app --factory --reload --port 8000
```
