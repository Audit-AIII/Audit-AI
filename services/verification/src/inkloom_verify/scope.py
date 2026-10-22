"""Request-scope checks: everything in a report must come from the request it answers.

The engine keeps no state between requests (SECURITY.md), so evidence can only cross requests
if a caller mixes them up. These checks catch that before a report leaves the engine: every
passage, citation and correction must trace back to this request's own content and reference
documents, exactly.

They do not decide which documents a tenant may use. The engine treats the request's
``references`` as the authorised evidence set; choosing that set is the backend's job.
"""

from __future__ import annotations

from collections.abc import Iterable

from inkloom_verify.chunking import passage_id_for
from inkloom_verify.schemas import ClaimResult, ReferenceDocument, VerificationReport, VerificationRequest


class ScopeViolation(Exception):
    """Something in a result does not belong to the request. Messages carry ids, never text."""

    def __init__(self, violations: list[str]) -> None:
        super().__init__(f"{len(violations)} scope violation(s): " + "; ".join(violations[:10]))
        self.violations = violations


def result_violations(request: VerificationRequest, result: ClaimResult) -> list[str]:
    """Ways one claim result does not belong to ``request``."""
    content = request.content.text
    documents: dict[str, ReferenceDocument] = {d.doc_id: d for d in request.references}
    claim_id = result.claim.claim_id
    found = []
    if not result.claim.source_span.fits(len(content)):
        found.append(f"{claim_id}: source_span is outside this request's content")
    for passage in result.evidence:
        document = documents.get(passage.doc_id)
        if document is None or not passage.matches(document):
            found.append(f"{claim_id}: passage {passage.passage_id} is not from this request's documents")
        elif passage.passage_id != passage_id_for(document.doc_id, document.text_sha256, passage.span):
            found.append(f"{claim_id}: passage id {passage.passage_id} does not match its provenance")
    for citation in result.citations:
        document = documents.get(citation.doc_id)
        if document is None or not citation.matches(document):
            found.append(f"{claim_id}: citation of {citation.passage_id} does not quote this request's documents")
    correction = result.correction
    if correction is not None:
        if not correction.target_span.fits(len(content)) or correction.target_span.slice(content) != correction.original_text:
            found.append(f"{claim_id}: correction does not replace this request's content")
        for citation in correction.citations:
            document = documents.get(citation.doc_id)
            if document is None or not citation.matches(document):
                found.append(f"{claim_id}: correction cites outside this request's documents")
    return found


def report_violations(request: VerificationRequest, report: VerificationReport) -> list[str]:
    """Ways a report does not answer ``request``."""
    found = []
    if report.request_id != request.request_id:
        found.append("request_id differs from the request")
    if report.tenant_id != request.tenant_id:
        found.append("tenant_id differs from the request")
    if report.reference_set_id != request.reference_set_id:
        found.append("reference_set_id differs from the request")
    if report.content_sha256 != request.content.text_sha256 or report.content_length != len(request.content.text):
        found.append("content hash or length differs from the request")
    expected = {(d.doc_id, d.version, d.text_sha256) for d in request.references}
    if {(r.doc_id, r.version, r.text_sha256) for r in report.references} != expected:
        found.append("references differ from the request's documents")
    for result in report.results:
        found.extend(result_violations(request, result))
    return found


def check_report_scope(request: VerificationRequest, report: VerificationReport) -> None:
    """Raises ScopeViolation unless everything in ``report`` comes from ``request``."""
    found = report_violations(request, report)
    if found:
        raise ScopeViolation(found)


def check_results_scope(request: VerificationRequest, results: Iterable[ClaimResult]) -> None:
    """Raises ScopeViolation unless every result comes from ``request``."""
    found = [v for result in results for v in result_violations(request, result)]
    if found:
        raise ScopeViolation(found)
