"""Response models shared by several routers (one OpenAPI name each)."""

import uuid

from pydantic import BaseModel

from app.models.execution import JobStatus


class JobAccepted(BaseModel):
    """202 response for every long-running operation (docs/03 §1)."""

    job_id: uuid.UUID
    status: JobStatus
    type: str
