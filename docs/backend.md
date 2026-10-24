# Backend design and decisions

The backend (`services/api`) owns the database, authentication, account isolation, the HTTP API,
review orchestration, versioning, the approval state machine, the audit trail, failure handling and
the LLM provider adapter. This file records the design decisions and guarantees behind it. For
setup and commands see [`services/api/README.md`](../services/api/README.md); for every route and
payload see [`services/api/API.md`](../services/api/API.md); for the shared status strings and
JSON Schemas see [`contract/README.md`](../contract/README.md).

## Product model: individual accounts

InkLoom is an individual-user app (DECISIONS.md, decision 1): one email is one private account that
owns several brands. A user sees only their own brands, sources, content and reviews, checks drafts
against their brand's approved documents, and approves their own content.

This was implemented without changing tables, columns, enums, routes or field names:

- Each `organisation` row is one user's private account; registration creates it.
- Roles no longer gate anything: every active membership holds every permission
  (`auth/permissions.py`). Registration writes `role = "admin"`, which means account owner.
- Risk-based routing is off: new reviews get `required_reviewer_role = null` (the UI shows "Any
  approver"). The column and migration 0008 are kept.
- Approval guards that remain: the review is finished, the version is current, and no cited source
  was replaced or withdrawn since the review ran.
- Isolation between accounts is the security boundary: another account's id answers `404`,
  identical in code and message to an id that does not exist (`test_cross_account_isolation.py`,
  `test_tenant_scoping.py`).

## Principles

- Missing evidence means `unverified`, never `false`.
- The engine analyses, the backend authorises, the frontend displays. No component takes another's
  authority, and the backend re-checks everything the engine returns.
- `completed` means analysis finished; it never means approved. Approval is never inferred from a
  successful AI response.
- Safe errors only: a stable error code, a message without internals, and a request id. No stack
  traces or raw provider errors.
- The engine runs in-process as a library and never gets its own database.

## Governance invariants (enforced on the server)

```text
if not authenticated or membership not active: deny
if evidence source not in the brand's authorised, approved scope: reject the result, log an integrity error
if analysis failed or evidence is invalid: block approval
if current_version_id != reviewed_version_id: reject the stale approval
never infer approval from a successful AI response
```

`organisation_id`, `user_id` and role are derived from the authenticated membership only; the same
values in a request body or query string are ignored.

## Shared contract values

- Verification status: `supported | contradicted | unverified | conflicting_sources | not_applicable`
- Severity: `low | medium | high | critical`
- Evidence relation: `supports | contradicts | context`
- Review states: `draft, queued, analysing, completed, needs_human_review, changes_requested,
  approved, rejected, failed, source_changed`
- Finding fields: `finding_id`, `category`, `severity`, `original_text`, `span_start`, `span_end`
  (one `span` object in the API), `check_type` (`rule | retrieval | semantic`), `explanation`,
  `verification_status`, `suggested_correction`, `requires_human_review`. Evidence: `source_id`,
  `source_version_id`, `quote`, `relation`.

## Review workflow

```text
POST /api/reviews (brand_id, text)
 1. corpus = the brand's APPROVED documents, latest version of each
 2. result cache (per account): a hit replays the stored result with zero provider calls
 3. provider chain: a confidential source in scope -> Ollama only; otherwise Gemini -> Groq -> OpenRouter -> Ollama
 4. no provider configured -> one labelled stub finding (category "stub", "[STUB OUTPUT] ...")
 5. engine, in-process:
      ClaimExtractor -> BM25 retrieval -> ClaimVerifier
      CONTRADICTED -> ClaimCorrector (re-check on): an evidence-backed rewrite
      NOT_ENOUGH_EVIDENCE -> ClaimSoftener: safer wording, kept only if softening_guard.py passes
 6. the backend re-validates every citation against its own copy of the source; a bad one
    downgrades that finding to unverified and drops its suggestion
 7. each finding gets a category (contradicted_claim / unsupported_claim / supported_claim / engine_error)
 8. every provider call (correction and re-check included) is logged to external_call_log, metadata only
 9. status = completed (everything supported) or needs_human_review
```

Brand rules (`evaluate_rules`) run on every review, before and independent of the claim checks,
with no model call, and are never cached. Why the backend drives the engine's components claim by
claim instead of calling `verify_request` is explained in the backend README, "Why the backend runs
its own claim pipeline".

## Provider adapter, cache and idempotency

- The engine never holds API keys: model calls go through the backend's `LLMProvider` chain.
- Provider and model come from environment variables only; no model id is hard-coded.
- Each call has a fixed timeout. Only 429, 5xx and timeouts are retried, a bounded number of times,
  then the chain falls through to the next provider. Invalid JSON or output that fails the schema
  counts as a provider failure.
- If every provider fails, the affected claims become `engine_error` findings (or the review is
  `failed`) with a safe error code; never approved.
- Result cache key: content hash + source versions + engine config + Intent-lock phrases +
  organisation id. The organisation id is mandatory, so accounts never share cache entries.
- Idempotency keys on `POST /api/reviews` and rerun: a duplicate returns the first result and makes
  no second model call. The key is claimed in the review's own transaction.
- Submission rate limits apply per user and per account.
- Confidential routing: if any source in scope is `confidential`, no cloud provider is ever
  constructed; only local Ollama is tried, and without it the review gets the labelled stub.
- Every review stores the provider, model id and prompt version it used.

## Versioning, approval and audit

- Content versions are immutable, numbered and hashed; exactly one version per item is current. A
  reviewed version is never overwritten; an old approval stays historical only.
- A rerun starts a new review of an explicit version; the old review is untouched.
- Review state changes follow a fixed state machine (`approval_rules.py`); invalid transitions
  answer `409` and change nothing.
- Approve is blocked when analysis failed, the review is stale, or a cited source was superseded
  after the review ran. Two decisions on one review are serialised with a row lock
  (`SELECT ... FOR UPDATE`).
- The audit log is append-only and records every state change (submit, source approval, review,
  edit, request changes, approve, reject, rerun, Dismiss, comments) in the same transaction as the
  change. Audit events never contain emails, names or comment text.

## Source lifecycle (InkWatch)

- Source states: `draft -> approved -> superseded | archived`. Every source version is kept, with
  what each historical review used.
- Withdrawing an approved source flips every dependent approved content version to
  `source_changed` and returns it for review, with audit events.
- Uploading a new source version stores section hashes and flips only dependents whose cited
  section changed (`section_diff.py`).
- A `source_changed` version cannot be approved until it is re-reviewed.

## Self-serve onboarding

`POST /api/auth/register` creates an account, an `admin` (owner) membership and a starter brand in
one transaction. Route shapes are in `API.md`; behaviour not covered there:

- Optional fields default as follows when omitted or blank: `display_name` -> `null`;
  `organisation_name` -> `"<display_name or the email's local part>'s workspace"`; `brand_name` ->
  `"My brand"`.
- The password limit is 8 characters to 72 **bytes** (bcrypt's limit); count bytes, not
  characters, in any client-side check.
- `role` or `organisation_id` in the body are ignored; every registration creates a brand-new
  account. Emails are stored lower-cased and matched case-insensitively.
- The organisation `slug` is a URL-safe form of the name plus 8 random hex characters, so equal
  names never collide.
- Registration is rate-limited on `request.client.host` only, never `X-Forwarded-For`. Behind a
  proxy all visitors may share the proxy's address.
- `account.registered`'s audit event records only the brand id.
- An uploaded draft's bytes are never stored, only its extracted text. Empty, unreadable or
  over-100,000-character text is rejected with `422`; scanned (image-only) PDFs extract no text.
- By design there is no email verification, password reset, invite flow or way to join another
  account.

## Safer wording for unverified claims

The engine's `ClaimSoftener` proposes a safer wording for an unverified claim; the backend keeps it
only if `softening_guard.py` passes. The product rules:

1. Never invent facts: the wording may only remove or soften what the claim already says, with no
   new numbers, names, places, features or comparisons.
2. Remove or soften the unsupported part, and keep everything else.
3. Never replace one unproven ranking or superlative with another ("number one", "#1", "best",
   "leading", "fastest", "only"): "India's number one" -> "India's leading" is not a fix.
4. Keep product names, prices and dates unchanged.
5. The finding stays `unverified`. The wording is stored in `safer_wording`, never in
   `suggested_correction`, and is labelled "Safer wording, not evidence-backed". Nothing is applied
   automatically.

A softener exception is logged by type name only and leaves the review unaffected.

## Trust Scorecard contract

The Scorecard page parses the backend's own `EvaluationOut` (`GET /api/evaluations/latest`), not
the engine's file-based `evaluation-summary-v1`. `EvaluationOut` must never gain a `contract` key:
the page treats a response with one as the older format.

The two reports define their rates differently, so they must never be shown side by side under the
same label:

| Metric | Backend `EvaluationOut` | Engine `evaluation-summary-v1` |
|---|---|---|
| Catch rate | Claims that should be flagged and were flagged (CONTRADICTED or NOT_ENOUGH_EVIDENCE) | `contradicted_recall`: CONTRADICTED only |
| False-positive rate | SUPPORTED claims flagged at all | Non-CONTRADICTED claims flagged CONTRADICTED |
| Scope | Verifier only, run per account from the app | Full pipeline, a CLI / CI artifact of `eval/run_eval.py` |

Held-out is the figure to quote; runs where more than 20% of claims got no verdict are refused and
not stored.

## Open decisions

- May a review run without any provider (the stub) be marked ready to publish? Today: yes.
- Should a dismissal carry over to the matching finding of a re-check? Today: no.

## Pending actions

- Choose the AI provider keys (`services/api/AI_PROVIDER_KEYS.md`), then run and record one real
  evaluation.
- Choose a host, deploy (backend README, "Deploy"), seed once without `--reset`, run the smoke test
  against the public URL, and tag the release.
- Record the fallback demo video.

## Known limitations

- The rate limiter is in-process memory (single worker). Idempotency keys and the evaluation's
  10-minute limit are in the database.
- No invites, organisation switcher, password reset or email verification (by design).
- Source conflict detection across documents at upload time, hash-linked audit verification,
  change-impact events and audit pack export are not built.
- Not deployed (no host chosen).
