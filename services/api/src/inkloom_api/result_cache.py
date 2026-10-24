"""Phase 5 task 5: result cache keyed by content hash + source versions + engine config +
organisation ID. Organisation ID is mandatory in the key so tenants never share a cache entry,
even for byte-identical content checked against byte-identical sources (00_CONTEXT.md: tenant
isolation is never optional, not even as a cache optimisation).

"Engine config" here means the engine's own contract version (the input/output schema this
backend and the engine agree on) - not which specific provider/model happened to answer, since
that varies run to run by design (the fallback chain tries whichever is configured, in order);
pinning a cache key to "whichever model answered last time" would make it miss almost always.

Only a genuine completed analysis is cached - never a stub result (no provider configured) and
never a provider-infrastructure failure (`failed`), since both represent transient facts about
*this run*, not a durable fact about the content, and caching a transient failure would make it
stick forever even after the problem clears.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from inkloom_verify.schemas import CONTRACT_VERSION
from sqlalchemy.orm import Session

from .engine.corpus import CorpusEntry
from .models import ContentVersion, EvidenceLink, Finding, ResultCache, Review
from .statuses import CheckType


def compute_cache_key(
    organisation_id: uuid.UUID, content_version: ContentVersion, corpus: list[CorpusEntry]
) -> str:
    source_fingerprints = sorted(f"{entry.brand_source_id}:{entry.document.text_sha256}" for entry in corpus)
    payload = {
        "organisation_id": str(organisation_id),
        "content_sha256": content_version.text_sha256,
        "sources": source_fingerprints,
        "engine_contract_version": CONTRACT_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_cached_report(db: Session, cache_key: str) -> dict | None:
    row = db.query(ResultCache).filter_by(cache_key=cache_key).one_or_none()
    return row.report if row else None


def store_report(db: Session, cache_key: str, review_id: uuid.UUID, report: dict) -> None:
    if db.query(ResultCache).filter_by(cache_key=cache_key).one_or_none() is not None:
        return  # a concurrent request already cached this exact key; first writer wins
    db.add(ResultCache(cache_key=cache_key, review_id=review_id, report=report))


def serialize_review_outcome(db: Session, review: Review) -> dict:
    """Everything needed to replay this review's result onto a different `Review` row later.
    Rule findings are left out: rules run fresh on every review (engine/brand_rules.py), since a
    brand's rules can change while the content and its sources stay the same."""
    findings = (
        db.query(Finding).filter(Finding.review_id == review.id, Finding.check_type != CheckType.RULE.value).all()
    )
    return {
        "report_status": review.report_status,
        "engine_provider": review.engine_provider,
        "engine_model_id": review.engine_model_id,
        "prompt_version": review.prompt_version,
        "engine_contract_version": review.engine_contract_version,
        "findings": [
            {
                "category": f.category,
                "severity": f.severity,
                "original_text": f.original_text,
                "span_start": f.span_start,
                "span_end": f.span_end,
                "check_type": f.check_type,
                "explanation": f.explanation,
                "verification_status": f.verification_status,
                "suggested_correction": f.suggested_correction,
                "requires_human_review": f.requires_human_review,
                "engine_claim_id": f.engine_claim_id,
                "evidence": [
                    {
                        "source_id": str(e.source_id) if e.source_id else None,
                        "source_version_id": str(e.source_version_id) if e.source_version_id else None,
                        "quote": e.quote,
                        "relation": e.relation,
                        "cited_section_hash": e.cited_section_hash,
                    }
                    for e in db.query(EvidenceLink).filter_by(finding_id=f.finding_id).all()
                ],
            }
            for f in findings
        ],
    }


def materialize_cached_report(db: Session, review: Review, report: dict) -> None:
    """Writes `Finding`/`EvidenceLink` rows onto `review` from a previously cached report. This
    review was never actually sent to any provider - `served_from_cache` records that."""
    review.report_status = report["report_status"]
    review.engine_provider = report["engine_provider"]
    review.engine_model_id = report["engine_model_id"]
    review.prompt_version = report["prompt_version"]
    review.engine_contract_version = report["engine_contract_version"]
    review.served_from_cache = True
    for f in report["findings"]:
        finding = Finding(
            review_id=review.id,
            category=f["category"],
            severity=f["severity"],
            original_text=f["original_text"],
            span_start=f["span_start"],
            span_end=f["span_end"],
            check_type=f["check_type"],
            explanation=f["explanation"],
            verification_status=f["verification_status"],
            suggested_correction=f["suggested_correction"],
            requires_human_review=f["requires_human_review"],
            engine_claim_id=f["engine_claim_id"],
        )
        db.add(finding)
        db.flush()
        for e in f["evidence"]:
            db.add(
                EvidenceLink(
                    finding_id=finding.finding_id,
                    source_id=uuid.UUID(e["source_id"]) if e["source_id"] else None,
                    source_version_id=uuid.UUID(e["source_version_id"]) if e["source_version_id"] else None,
                    quote=e["quote"],
                    relation=e["relation"],
                    cited_section_hash=e["cited_section_hash"],
                )
            )
