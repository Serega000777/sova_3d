"""Usage ledger service (T-010).

The ledger is append-only (enforced by trigger); this module is the only
sanctioned write path and the place where aggregates are computed.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.execution import Job
from app.models.usage import UsageEntry, UsageKind
from app.services import pricing

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class UsageTotals:
    cost_usd: Decimal
    credits_balance: Decimal
    quantity_by_kind: dict[UsageKind, Decimal]
    entries: int


def record(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    kind: UsageKind,
    quantity: Decimal | int,
    unit: str,
    cost_usd: Decimal | int = ZERO,
    credits_delta: Decimal | int = ZERO,
    user_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    ai_request_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageEntry:
    """Append one ledger row. Never mutate an existing row: post a correcting entry."""
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    if cost_usd < 0:
        raise ValueError("cost_usd must be non-negative")
    entry = UsageEntry(
        workspace_id=workspace_id,
        user_id=user_id,
        job_id=job_id,
        ai_request_id=ai_request_id,
        idempotency_key=idempotency_key,
        kind=kind,
        quantity=Decimal(quantity),
        unit=unit,
        cost_usd=Decimal(cost_usd),
        credits_delta=Decimal(credits_delta),
        metadata_=metadata or {},
    )
    session.add(entry)
    session.flush()
    return entry


def record_job_completion(
    session: Session,
    job: Job,
    *,
    action_type: str,
    quantity: Decimal | int,
    unit: str,
    cost_usd: Decimal | int = ZERO,
) -> None:
    """Record one idempotent shadow-meter event for a successful job.

    AI and vision handlers already record provider-derived usage. Keep those exact rows as
    the job's completion meter instead of adding a second placeholder row at the runner.
    """
    existing = session.scalar(sa.select(UsageEntry.id).where(UsageEntry.job_id == job.id).limit(1))
    if existing is not None:
        return

    quoted_credits = pricing.quote(action_type)
    # F-068 remains shadow-only: a canonical quote is recorded, but credits_delta stays zero until
    # payment, top-up, refund and enforcement rules are approved and connected to a real provider.
    statement = (
        insert(UsageEntry)
        .values(
            workspace_id=job.workspace_id,
            user_id=job.created_by,
            job_id=job.id,
            idempotency_key=f"job:{job.id}",
            kind=UsageKind.credits,
            quantity=Decimal(quantity),
            unit=unit,
            cost_usd=Decimal(cost_usd),
            credits_delta=ZERO,
            metadata_={
                "action_type": action_type,
                "metering_mode": "shadow",
                "pricing": pricing.PRICING_VERSION,
                "quoted_credits": str(quoted_credits),
            },
        )
        .on_conflict_do_nothing()
    )
    session.execute(statement)


def workspace_totals(
    session: Session,
    workspace_id: uuid.UUID,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> UsageTotals:
    """Aggregate a workspace's ledger over an optional [since, until) window."""
    where = [UsageEntry.workspace_id == workspace_id]
    if since is not None:
        where.append(UsageEntry.created_at >= since)
    if until is not None:
        where.append(UsageEntry.created_at < until)

    by_kind_rows = session.execute(
        sa.select(UsageEntry.kind, sa.func.sum(UsageEntry.quantity))
        .where(*where)
        .group_by(UsageEntry.kind)
    ).all()
    totals = session.execute(
        sa.select(
            sa.func.coalesce(sa.func.sum(UsageEntry.cost_usd), 0),
            sa.func.coalesce(sa.func.sum(UsageEntry.credits_delta), 0),
            sa.func.count(),
        ).where(*where)
    ).one()

    return UsageTotals(
        cost_usd=Decimal(totals[0]),
        credits_balance=Decimal(totals[1]),
        quantity_by_kind={UsageKind(kind): Decimal(qty) for kind, qty in by_kind_rows},
        entries=int(totals[2]),
    )
