"""API shapes of the root-cause analysis (app/api/v1/rca.py).

Mirrored by frontend/src/types/rca.ts — change both together.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RcaTrigger = Literal["manual", "chat", "alert", "scan"]
RcaStatus = Literal["pending", "running", "completed", "failed"]
ReportStatus = Literal["none", "running", "done", "failed"]
TargetKind = Literal["Workload", "Pod", "Service"]

_DNS_NAME = r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$"


class RcaRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$",
        description="Namespace to diagnose (its dependencies are included); empty = whole cluster",
    )
    target_kind: TargetKind | None = Field(
        default=None, description="Focus on one object; leave empty to diagnose the whole namespace"
    )
    target_name: str | None = Field(default=None, pattern=_DNS_NAME)
    lookback_minutes: int | None = Field(
        default=None, ge=15, le=1440, description="How far back to look for causes"
    )
    with_report: bool = Field(
        default=True, description="Let the AI check the top hypotheses and write a report"
    )
    provider: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)


class RcaStep(BaseModel):
    key: str
    label: str
    status: Literal["running", "done", "error"]


class HypothesisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    event_id: str
    score: float
    chain: list[str]
    rules: list[str]
    verdict: Literal["confirmed", "refuted", "unclear"] | None
    feedback: Literal["correct", "wrong"] | None = Field(
        default=None, description="An engineer's judgement of this cause"
    )
    feedback_by_email: str | None = None


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correct: bool = Field(description="True: this is the root cause. False: it is not")


class WeightOut(BaseModel):
    key: str = Field(description="rule:<id> or type:<event type>")
    positive: int
    negative: int
    factor: float = Field(description="Multiplier applied to the rule weight or type prior")
    updated_at: datetime


class RcaRunSummary(BaseModel):
    id: uuid.UUID
    trigger: RcaTrigger
    requested_by_email: str
    namespace: str
    target_kind: TargetKind | None
    target_name: str | None
    window_start: datetime
    window_end: datetime
    status: RcaStatus
    error: str | None
    report_status: ReportStatus
    created_at: datetime
    finished_at: datetime | None
    top_cause: str | None = Field(description="Summary of the rank-1 hypothesis, for lists")
    top_cause_type: str | None


class RcaRunOut(RcaRunSummary):
    steps: list[RcaStep]
    warnings: list[str]
    graph: dict[str, Any] | None = Field(
        description="events (with evidence), edges (cause, effect, rule, weight, why), seeds"
    )
    hypotheses: list[HypothesisOut]
    report: dict[str, Any] | None
    llm_trace_id: str | None
    approval_id: uuid.UUID | None


class RcaRunPage(BaseModel):
    items: list[RcaRunSummary]
    total: int


class ProposeFixOut(BaseModel):
    approval_id: uuid.UUID
    title: str
    status: str


__all__ = [
    "FeedbackIn",
    "HypothesisOut",
    "WeightOut",
    "ProposeFixOut",
    "RcaRunCreate",
    "RcaRunOut",
    "RcaRunPage",
    "RcaRunSummary",
    "RcaStep",
    "ReportRequest",
]
