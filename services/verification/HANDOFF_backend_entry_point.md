# Handoff to Member 3 (backend): one entry point into the engine

**Why:** `services/api/src/inkloom_api/engine/pipeline.py` re-implements extraction, retrieval and
verification, so the pipeline that CI protects (`verify_request`) is not the one real reviews use.
It also never passes brand rules, so the engine's rule findings never appear in real reviews.
Either call the engine as below, or document in `services/api/README.md` why the backend keeps its
own copy.

## The call

```python
from inkloom_verify.pipeline import verify_request
from inkloom_verify.schemas import VerificationRequest

report = verify_request(VerificationRequest(...), provider)   # never raises for content or model problems
```

`VerificationRequest` fields: `request_id`, `tenant_id`, optional `reference_set_id`,
`content` (`content_id`, `text`), `references` (a list of `doc_id`, `version`, `title`, `text`,
approved sources only) and optional `rules` (`BrandRules`). A full example is in
`examples/verification_request.json`.

The report has `results` (one per claim), `errors`, `status` (COMPLETED, PARTIAL or FAILED),
`score`, provenance, and **`rule_findings`**.

## Passing brand rules

`rules` is deterministic: no model call, so these findings stand even if a provider fails.

```json
"rules": {
  "rule_set_id": "brand-123-v1",
  "prohibited_terms": [{"rule_id": "p1", "term": "cheap", "approved_alternative": "affordable"}],
  "product_names":    [{"rule_id": "n1", "approved_name": "Lumen Pods", "variants": ["LumenPods"]}],
  "disclaimers":      [{"rule_id": "d1", "disclaimer": "Results vary.", "trigger_terms": ["battery"]}],
  "numeric_limits":   [{"rule_id": "x1", "subject": "battery", "units": ["hours"], "maximum": 24}],
  "required_terms":   [],
  "style": {}
}
```

- `"style": {}` switches on the accessibility and tone checks with defaults: ALL-CAPS runs
  (3+ words), emoji runs (more than 2), vague link text ("click here"), missing image alt text.
  Use `"style": null` or omit it to switch them off.
- A rule may carry `"source": {"doc_id": ..., "quote": ...}`, which must be one of the request's
  reference documents and an exact quote from it. Only a rule with a source can produce a
  `suggested_correction`; otherwise the finding has none.

## What a rule finding looks like

Always `check_type: "rule"`, `category: "rule_violation"`, `verification_status: "not_applicable"`,
`requires_human_review: true`. Fields: `finding_id`, `rule_id`, `rule_type`
(required_term, prohibited_term, product_naming, required_disclaimer, numeric_limit,
all_caps_run, emoji_run, vague_link_text, missing_alt_text), `severity`, `original_text`, `span`,
`explanation`, `source_ids`, `evidence`, `suggested_correction`.

## What the backend still has to do

1. Store a `BrandRules` object per brand (or per account) and pass it on every review. The engine
   applies only the rules it is given.
2. Persist `rule_findings` next to claim findings, as the same finding shape for the frontend.
3. Map a claim result with conflicting evidence to `conflicting_sources` for the frontend (see
   `CONTRACTS.md` for the engine's verdict names).
4. Keep a rule finding from ever clearing a review: `requires_human_review` is always true.

## Open point for Darsh and Krish

Trust Scorecard: either the backend runs the evaluation (`POST /api/evaluations`), or the engine
serves a report file. Pick one and update `API.md` so the frontend builds against one contract.
