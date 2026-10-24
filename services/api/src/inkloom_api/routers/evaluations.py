"""GET /api/evaluations/latest and POST /api/evaluations - the Trust Scorecard page (frontend
lib/additions/analytics.ts, `Evaluation`).

`latest` answers 404 until the account has run one: the Scorecard page treats 404 as "not
available yet", whereas a 200 with missing numbers would render "undefined" / "Invalid Date".

`POST` runs the engine's labelled evaluation synchronously through this backend's provider chain
(evaluation_runner.py), bounded by the engine's call budget, and stores the result. No provider
configured -> 409 and nothing is stored. A run where too many claims got no verdict (provider
outages, rate limits, the time limit; `eval_max_provider_failure_rate`, default 20%) -> 409 and
nothing is stored either, since its numbers would describe the outage, not the checker. At most
one run per user per 10 minutes, stored or discarded (counted from the audit trail, so it survives a
restart), and never two at once for the same user.
"""

from __future__ import annotations

import math
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership
from ..config import Settings, get_settings
from ..db import get_db
from ..engine.pipeline import external_call_logger
from ..engine.provider import build_provider
from ..evaluation_runner import COVERAGE_VERIFIER_ONLY, EvaluationUnavailableError, provider_mode, run_evaluation
from ..models import AuditEvent, EvaluationRun

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])

_NO_PROVIDER = (
    "no AI provider is configured on this server, so the evaluation cannot run; "
    "set one up in services/api/.env (see API.md) and try again"
)

_in_flight: set[uuid.UUID] = set()
_in_flight_lock = threading.Lock()


class PerCheckOut(BaseModel):
    check: str
    catch_rate: float | None
    false_positive_rate: float | None
    n: int


class RatioOut(BaseModel):
    numerator: int
    denominator: int
    value: float | None


class SplitOut(BaseModel):
    n: int
    catch_rate: RatioOut
    false_positive_rate: RatioOut


class EvaluationOut(BaseModel):
    # The Scorecard page's `Evaluation` type, exactly:
    catch_rate: float | None
    false_positive_rate: float | None
    per_check: list[PerCheckOut]
    sample_size: int
    run_at: datetime
    # Additive:
    id: uuid.UUID
    status: str
    engine_prompt_version: str | None
    dataset_version: str
    limits_note: str
    latency_ms_p50: float | None
    provider_failure_rate: float | None
    coverage: str
    by_split: dict[str, SplitOut] | None  # null for runs stored before per-split metrics existed
    provider_mode: str | None

    @classmethod
    def from_model(cls, run: EvaluationRun) -> "EvaluationOut":
        m = run.metrics
        return cls(
            catch_rate=m["catch_rate"]["value"],
            false_positive_rate=m["false_positive_rate"]["value"],
            per_check=[PerCheckOut(**entry) for entry in m["per_check"]],
            sample_size=run.sample_size,
            run_at=run.ran_at,
            id=run.id,
            status=run.status,
            engine_prompt_version=run.engine_prompt_version,
            dataset_version=run.dataset_version,
            limits_note=run.limits_note,
            latency_ms_p50=m.get("latency_ms_p50"),
            provider_failure_rate=m.get("provider_failure_rate"),
            coverage=m.get("coverage", COVERAGE_VERIFIER_ONLY),
            by_split=m.get("by_split"),
            provider_mode=provider_mode(m.get("model_ids", [])),
        )


@router.get("/latest", response_model=EvaluationOut)
def latest_evaluation(
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> EvaluationOut:
    run = (
        db.query(EvaluationRun)
        .filter(EvaluationRun.organisation_id == auth.organisation_id)
        .order_by(EvaluationRun.ran_at.desc(), EvaluationRun.created_at.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no evaluation has been run yet")
    return EvaluationOut.from_model(run)


_ATTEMPT_EVENTS = ("evaluation.run", "evaluation.discarded")


def _enforce_interval(db: Session, auth: AuthContext, settings: Settings) -> None:
    """Counts every run that actually called the provider - stored or discarded - from the
    audit trail, so the limit survives a restart and a discarded run can't be retried at once.
    A request refused before any call (no provider configured) writes no event and isn't counted."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=settings.eval_min_interval_seconds)
    latest = (
        db.query(AuditEvent.created_at)
        .filter(
            AuditEvent.actor_user_id == auth.user_id,
            AuditEvent.event_type.in_(_ATTEMPT_EVENTS),
            AuditEvent.created_at >= since,
        )
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    if latest is not None:
        minutes = max(1, round(settings.eval_min_interval_seconds / 60))
        # Seconds until the newest counted attempt leaves the window. Errors.py copies the
        # Retry-After header into the body as error.retry_after (same as the review rate limit).
        wait = max(1, math.ceil(settings.eval_min_interval_seconds - (now - latest.created_at).total_seconds()))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"an evaluation can be run once every {minutes} minutes; try again later",
            headers={"Retry-After": str(wait)},
        )


@router.post("", response_model=EvaluationOut, status_code=status.HTTP_201_CREATED)
def create_evaluation(
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EvaluationOut:
    _enforce_interval(db, auth, settings)
    with _in_flight_lock:
        if auth.user_id in _in_flight:
            # How long the running one can take at most (its time limit), so a retry after it
            # meets a finished run.
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "an evaluation is already running for this account",
                                headers={"Retry-After": str(max(1, math.ceil(settings.eval_deadline_seconds)))})
        _in_flight.add(auth.user_id)
    try:
        run_id = uuid.uuid4()
        # The labelled set is synthetic, so the normal (non-confidential) chain is used.
        provider = build_provider(
            confidential=False, on_attempt=external_call_logger(db, auth.organisation_id, f"eval-{run_id}")
        )
        if not provider.configured_providers:
            raise HTTPException(status.HTTP_409_CONFLICT, _NO_PROVIDER)
        try:
            result = run_evaluation(provider, settings)
        except EvaluationUnavailableError as error:
            db.rollback()  # drop any call-log rows from a run that produced nothing
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None

        failure_rate = result.metrics["provider_failure_rate"] or 0.0
        if failure_rate > settings.eval_max_provider_failure_rate:
            # The calls really happened, so their call-log rows and an audit event are kept; the
            # misleading numbers are not.
            failed = round(failure_rate * result.sample_size)
            log_audit_event(
                db, organisation_id=auth.organisation_id, actor_user_id=auth.user_id,
                event_type="evaluation.discarded", entity_type="evaluation_run", entity_id=run_id,
                details={"sample_size": result.sample_size, "claims_without_verdict": failed},
                request_id=f"eval-{run_id}",
            )
            db.commit()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"the AI provider could not answer {failed} of {result.sample_size} test claims (rate limits, "
                "outages or the time limit), so this run was not saved - its numbers would describe the "
                "provider, not the checker. Try again later.",
            )

        run = EvaluationRun(
            id=run_id,
            organisation_id=auth.organisation_id,
            status=result.status,
            ran_at=result.ran_at,
            engine_prompt_version=result.engine_prompt_version,
            dataset_version=result.dataset_version,
            sample_size=result.sample_size,
            metrics=result.metrics,
            limits_note=result.limits_note,
            created_by=auth.user_id,
        )
        db.add(run)
        log_audit_event(
            db,
            organisation_id=auth.organisation_id,
            actor_user_id=auth.user_id,
            event_type="evaluation.run",
            entity_type="evaluation_run",
            entity_id=run_id,
            details={"status": result.status, "sample_size": result.sample_size, "dataset_version": result.dataset_version},
            request_id=f"eval-{run_id}",
        )
        db.commit()
        db.refresh(run)
        return EvaluationOut.from_model(run)
    finally:
        with _in_flight_lock:
            _in_flight.discard(auth.user_id)
