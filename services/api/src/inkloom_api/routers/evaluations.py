"""`GET /api/evaluations/latest`: the latest evaluation report's summary, for the Trust Scorecard.

Any active member may read it (the same rule as `GET /api/brands`): it is a benchmark of the
verification engine on a synthetic, labelled dataset, not tenant data. This backend does not
compute any metric: it serves the summary the engine's evaluation runner wrote
(`services/verification/eval/reports/<timestamp>.summary.json`, contract `evaluation-summary-v1`),
after the engine's own loader re-validates it and marks it stale if the dataset changed since.

Responses (always 200 for an authenticated member, so the frontend can tell "no evaluation yet"
apart from "route missing"): `state` is `available`, `incomplete` (the newest run stopped; its error
is included) or `none` (no report yet). A report that breaks the contract is a 500 with a generic
message; its contents are never echoed.

`POST /api/evaluations` (running an evaluation from the web) is deliberately not provided: a run
can call a paid model and takes minutes. Evaluations run from the command line or CI.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from inkloom_verify.evaluation.summary import SummaryInvalid, latest_summary

from ..auth.dependencies import AuthContext, get_current_membership
from ..config import Settings, get_settings

logger = logging.getLogger("inkloom_api.evaluations")
router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


@router.get("/latest")
def latest_evaluation(
    auth: AuthContext = Depends(get_current_membership),
    settings: Settings = Depends(get_settings),
) -> dict:
    reports_dir = Path(settings.evaluation_reports_dir)
    try:
        summary = latest_summary(reports_dir, reports_dir.parent / "datasets.lock.json")
    except SummaryInvalid:
        logger.error("evaluation summary in %s does not match its contract", reports_dir.name)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "the latest evaluation report could not be read") from None
    return summary.model_dump(mode="json")
