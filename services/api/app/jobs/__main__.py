"""`python -m app.jobs` — the worker-general process."""

import logging

from app.jobs.runner import serve

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    serve()
