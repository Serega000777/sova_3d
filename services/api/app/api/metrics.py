"""Prometheus metrics (T-097): what jobs, AI and geometry are actually doing.

Read straight from the database, so the numbers are the same ones the product is built
on — no separate counter to drift out of step. The endpoint is off unless METRICS_TOKEN
is set, and then it needs that token: this is operational data about every workspace.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Header, Request, Response

from app.api.deps import DbDep
from app.api.errors import NotFoundError, UnauthorizedError
from app.models.execution import Job, JobStatus, Operation
from app.models.printing import PrintAnalysisRecord
from app.models.scanning import ScanSession
from app.models.usage import UsageEntry

router = APIRouter(tags=["metrics"], include_in_schema=False)

WINDOW = timedelta(hours=24)


def _line(name: str, labels: dict[str, str], value: float) -> str:
    rendered = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if v)
    return f"{name}{{{rendered}}} {value}" if rendered else f"{name} {value}"


@router.get("/metrics", response_class=Response)
def metrics(
    request: Request,
    db: DbDep,
    authorization: str = Header(default=""),
) -> Response:
    expected = request.app.state.settings.metrics_token
    if not expected:
        raise NotFoundError("metrics", "disabled")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, expected):
        raise UnauthorizedError("metrics token required")

    since = datetime.now(UTC) - WINDOW
    lines: list[str] = []

    lines.append("# HELP physicalai_jobs Jobs by type and status in the last 24h.")
    lines.append("# TYPE physicalai_jobs gauge")
    rows = db.execute(
        sa.select(Job.type, Job.status, sa.func.count())
        .where(Job.created_at >= since)
        .group_by(Job.type, Job.status)
    ).all()
    for job_type, status, count in rows:
        lines.append(_line("physicalai_jobs", {"type": job_type, "status": status.value}, count))

    lines.append("# HELP physicalai_jobs_in_flight Jobs queued or running right now.")
    lines.append("# TYPE physicalai_jobs_in_flight gauge")
    in_flight = db.execute(
        sa.select(Job.type, sa.func.count())
        .where(Job.status.in_([JobStatus.queued, JobStatus.running]))
        .group_by(Job.type)
    ).all()
    for job_type, count in in_flight:
        lines.append(_line("physicalai_jobs_in_flight", {"type": job_type}, count))

    lines.append("# HELP physicalai_job_duration_seconds Finished job wall time in the last 24h.")
    lines.append("# TYPE physicalai_job_duration_seconds summary")
    seconds = sa.func.extract("epoch", Job.finished_at - Job.started_at)
    durations = db.execute(
        sa.select(Job.type, sa.func.count(), sa.func.coalesce(sa.func.sum(seconds), 0))
        .where(Job.finished_at.is_not(None), Job.started_at.is_not(None), Job.finished_at >= since)
        .group_by(Job.type)
    ).all()
    for job_type, count, total in durations:
        lines.append(
            _line("physicalai_job_duration_seconds_count", {"type": job_type}, float(count))
        )
        lines.append(_line("physicalai_job_duration_seconds_sum", {"type": job_type}, float(total)))

    lines.append("# HELP physicalai_job_failures Failed jobs by error code in the last 24h.")
    lines.append("# TYPE physicalai_job_failures gauge")
    error_code = Job.error["code"].astext.label("code")
    failures = db.execute(
        sa.select(Job.type, error_code, sa.func.count())
        .where(Job.status == JobStatus.failed, Job.created_at >= since)
        .group_by(Job.type, error_code)
    ).all()
    for job_type, code, count in failures:
        lines.append(
            _line("physicalai_job_failures", {"type": job_type, "code": code or "unknown"}, count)
        )

    lines.append("# HELP physicalai_ai_cost_usd Model spend in the last 24h.")
    lines.append("# TYPE physicalai_ai_cost_usd gauge")
    model_label = UsageEntry.metadata_["model"].astext.label("model")
    spend = db.execute(
        sa.select(
            model_label,
            sa.func.coalesce(sa.func.sum(UsageEntry.cost_usd), 0),
            sa.func.coalesce(sa.func.sum(UsageEntry.quantity), 0),
            sa.func.count(),
        )
        .where(UsageEntry.created_at >= since)
        .group_by(model_label)
    ).all()
    for model, cost, tokens, calls in spend:
        labels = {"model": model or "unknown"}
        lines.append(_line("physicalai_ai_cost_usd", labels, float(cost)))
        lines.append(_line("physicalai_ai_tokens", labels, float(tokens)))
        lines.append(_line("physicalai_ai_calls", labels, float(calls)))

    lines.append("# HELP physicalai_geometry_operations Kernel operations executed, all time.")
    lines.append("# TYPE physicalai_geometry_operations gauge")
    operations = db.execute(
        sa.select(Operation.operation_type, sa.func.count()).group_by(Operation.operation_type)
    ).all()
    for operation_type, count in operations:
        lines.append(_line("physicalai_geometry_operations", {"type": operation_type}, count))

    lines.append("# HELP physicalai_print_analyses Printability analyses by status, all time.")
    lines.append("# TYPE physicalai_print_analyses gauge")
    analyses = db.execute(
        sa.select(PrintAnalysisRecord.status, sa.func.count()).group_by(PrintAnalysisRecord.status)
    ).all()
    for status, count in analyses:
        lines.append(_line("physicalai_print_analyses", {"status": str(status)}, count))

    lines.append("# HELP physicalai_scans Scan sessions by status, all time.")
    lines.append("# TYPE physicalai_scans gauge")
    scans = db.execute(
        sa.select(ScanSession.status, sa.func.count()).group_by(ScanSession.status)
    ).all()
    for status, count in scans:
        lines.append(_line("physicalai_scans", {"status": status.value}, count))

    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
