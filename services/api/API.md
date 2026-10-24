# INKLOOM AI backend — API reference and setup

InkLoom is an **individual-user app**: one email = one private account, owning several brands.
The user checks drafts against their brand's approved documents, gets evidence for every finding
(claims without evidence are **unverified**, never "false"), sees suggested safer rewrites, and
marks their own content ready to publish. No teams, roles or reviewer tiers.

Status (2026-10-24): every route below is live, verified against a real PostgreSQL database
(288 tests, `README.md` → "Test") and over real HTTP (`scripts/smoke_test.py`), including real
AI reviews through Gemini (`gemini-3.5-flash-lite`).

## Setup, start to finish

### 1. Create `.env`

```sh
cd services/api
cp .env.example .env
```

Fill in `AUTH_SECRET_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) and one AI
provider (see "AI providers" below). `DATABASE_URL`'s default matches `docker-compose.yml`.

`main.py` calls `load_dotenv()` first, so every key in `.env` reaches the real process environment —
the engine (`inkloom_verify`) reads some provider settings straight from `os.environ`.

### 2. Start Postgres

```sh
docker compose up -d        # needs Docker Desktop running
```

### 3. Install and migrate

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]" -e ../verification -c constraints.txt   # exact tested versions; macOS/Linux: .venv/bin/python
.venv/Scripts/python -m alembic upgrade head              # migrations 0001-0012
```

### 4. Seed two demo accounts (optional)

```sh
.venv/Scripts/python scripts/seed.py            # --reset to delete and reseed them
```

Two individual demo users (`asha@seed.inkloom.demo`, `ben@seed.inkloom.demo`), each with a private
account, two brands, approved brand documents, and content in every state: completed,
needs_human_review, approved, changes_requested, source_changed (a withdrawn document), an item
with two versions, and "India's number one …" claims flagged unverified. Demo reviews use the
offline scripted provider (model id `scripted/demo-v1`) — no API key needed — and everything is
labelled `[SEEDED]`. The shared demo password is printed at the end.

### 5. Run

```sh
.venv/Scripts/python -m uvicorn inkloom_api.main:app --reload
```

`GET http://localhost:8000/health` → `{"status": "ok"}`. Swagger UI at `/docs`.

### 6. Smoke test (server running)

```sh
.venv/Scripts/python scripts/smoke_test.py      # BASE_URL=... to point elsewhere
```

Registers a fresh user → uploads a document → reviews a draft → lists reviews → fetches the review →
analytics → latest evaluation (404 before any run) → approves. No seed data needed.

## AI providers

Tried in this fixed order on every call, falling through on any failure: **Gemini → Groq →
OpenRouter `:free` → local Ollama** (only Ollama for confidential sources). Configure at least one in
`.env`; `.env.example` documents each, with the model ids verified on 2026-10-24:

| Provider | Variables | Verified id |
|---|---|---|
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL` | `gemini-3.5-flash-lite` (recommended, ~1s/call); `gemini-3.6-flash` works but is slower |
| OpenRouter | `OPENROUTER_API_KEY`, `INKLOOM_LLM_MODELS` | `nvidia/nemotron-3.5-super-vl:free` |
| Groq | `GROQ_API_KEY`, `GROQ_MODEL` | not configured here |
| Ollama | `OLLAMA_MODEL` (`OLLAMA_BASE_URL`) | not configured here |

Pick ids from the providers' live lists (Gemini: ai.google.dev/gemini-api/docs/models; OpenRouter:
`https://openrouter.ai/api/v1/models` — a model without `response_format` in `supported_parameters`
answers 404 here). With **no** provider configured, reviews still complete with one clearly labelled
placeholder finding (`category: "stub"`, explanation starting `[STUB OUTPUT]`), and
`POST /api/evaluations` answers 409.

Content sent for review leaves the machine for the configured cloud provider (see `DISCLOSURE.md`).

## Conventions

- Every route except `/health`, `POST /api/auth/login` and `POST /api/auth/register` needs
  `Authorization: Bearer <access_token>`.
- **Scope comes only from the token.** Every id in a path or query is checked against the caller's
  own account; another account's id answers `404`, identical (code and message) to an id that does
  not exist.
- **Errors**: `{"error": {"code", "message", "request_id"}}`. Codes: `UNAUTHENTICATED` (401),
  `FORBIDDEN` (403 — not raised for an active account any more), `NOT_FOUND` (404), `CONFLICT` (409),
  `VALIDATION_ERROR` (422 — field locations only, never the submitted value), `RATE_LIMITED` (429),
  `INTERNAL_ERROR` (500). Every response carries `X-Request-ID`, errors included (a 500's
  `request_id` matches it). An unknown path is `404 NOT_FOUND`; a wrong method on a known path is
  `405` with code `NOT_FOUND`. A caller-supplied `X-Request-ID` is reused only if it is 1–128 of
  `A-Z a-z 0-9 . _ -`; otherwise a new one is generated.
- **Text fields** (titles, names, notes, draft text, uploaded file contents) must not contain a NUL
  (`\u0000`) character: `422 VALIDATION_ERROR` naming the field (PostgreSQL cannot store it).
- `span` offsets are Unicode **code points** into the submitted text, not UTF-16 units.
- Reviews run **synchronously**: the POST response is the finished result.
- Every state change writes an audit event; provider calls are logged (metadata only) to
  `external_call_log`.

## Accounts and roles

`POST /api/auth/register` creates a private account (an organisation with one membership) and
returns `role: "admin"`, which simply means **account owner**. Roles no longer grant or restrict
anything; risk-based routing is off, so `required_reviewer_role` is `null` on every new review (the
UI shows "Any approver"). The user approves their own content. Guards that still apply on approve
(409): the review must be finished (`completed` / `needs_human_review`), the version must be the
current one, and no cited source may have been withdrawn or replaced since the review ran.

## Routes

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness + DB check |
| `POST /api/auth/register` | Sign up: account + starter brand + token |
| `POST /api/auth/login` | Email + password → token |
| `GET /api/auth/me` | Current session |
| `GET /api/brands` | The user's brands (dashboard list, with review stats) |
| `POST /api/brands` | Create a brand |
| `GET /api/brands/{brand_id}/sources` | A brand's documents |
| `POST /api/brands/{brand_id}/sources` | Upload a document (.txt/.pdf/.docx), optionally approved at once |
| `POST /api/brands/{brand_id}/sources/{source_id}/approve` | Approve a draft document |
| `POST /api/brands/{brand_id}/sources/{source_id}/withdraw` | Withdraw an approved document; approved dependents → `source_changed` |
| `POST /api/brands/{brand_id}/sources/{source_id}/versions` | New version of a document; flips only dependents whose cited section changed |
| `GET /api/brands/{brand_id}/rules` · `PUT .../rules` | **New.** The brand's terminology / compliance / accessibility rules |
| `POST /api/reviews` | Check pasted text |
| `POST /api/reviews/upload` | Check an uploaded draft file |
| `GET /api/reviews` | **New.** The review queue: list the user's reviews |
| `GET /api/reviews/{review_id}` | One review |
| `POST /api/reviews/{review_id}/rerun` | Re-check the same version |
| `POST /api/content/{content_item_id}/versions` | Save an edit as a new version and check it |
| `GET /api/content/{content_item_id}/history` | Versions, reviews and decisions |
| `POST /api/content-versions/{content_version_id}/approve` | Mark ready to publish |
| `POST /api/content-versions/{content_version_id}/request-changes` | Send back (`changes_requested` / `rejected`) |
| `GET` / `PUT /api/content-versions/{content_version_id}/locks` | **New.** Intent-lock: the writer's must-keep phrases |
| `POST /api/findings/{finding_id}/dismiss` · `.../restore` | **New.** Dismiss a finding / undo it |
| `GET` / `POST /api/findings/{finding_id}/comments` | **New.** Comments on a finding |
| `GET /api/analytics/brand-risk` | **New.** Insights numbers |
| `GET /api/evaluations/latest` | **New.** Latest Trust Scorecard run |
| `POST /api/evaluations` | **New.** Run the labelled evaluation |

### `POST /api/auth/register`

Body: `{"email", "password", "display_name"?, "organisation_name"?, "brand_name"?}` (password 8+
characters, ≤ 72 bytes). **201**:

```json
{
  "access_token": "eyJ...", "token_type": "bearer", "expires_in": 43200,
  "user": {"id": "...", "email": "ada@example.com", "display_name": null},
  "organisation": {"id": "...", "name": "ada's workspace", "slug": "ada-s-workspace-3f9a1c2b"},
  "role": "admin",
  "brand": {"id": "...", "name": "My brand", "description": null, "approved_source_count": 0,
            "created_at": "2026-10-24T10:00:00Z", "review_count": 0, "open_review_count": 0, "last_review_at": null}
}
```
409 duplicate email (case-insensitive), 422 bad input, 429 more than 5 sign-ups per IP per 10 minutes.
Detail: `member3_backend/HANDOFF_self_serve_onboarding.md`.

### `POST /api/auth/login` · `GET /api/auth/me`

Login body `{"email", "password"}` → same shape as register minus `brand`. 401 `invalid email or
password` for any failure (indistinguishable on purpose). `me` → `{"user", "organisation", "role"}`.

### `GET /api/brands` — dashboard list

Oldest first (the sign-up brand is `[0]`). Review stats are real counts; zero / `null` when none.

```json
[
  {
    "id": "...", "name": "My brand", "description": null, "approved_source_count": 1,
    "created_at": "2026-10-24T09:00:00Z",
    "review_count": 5,
    "open_review_count": 2,
    "last_review_at": "2026-10-24T11:42:10Z"
  }
]
```
- `review_count`: every review of this brand's content.
- `open_review_count`: reviews **waiting for the user's decision** = the latest review of each content
  item's *current* version, in `completed` or `needs_human_review`. A review left on an older version,
  or superseded by a rerun, is not counted (approving it would be refused).
- `last_review_at`: newest review's `created_at`, or `null`.

`POST /api/brands` body `{"name", "description"?}` → 201 `BrandOut` (stats 0 / null); 409 duplicate name.

### Brand documents

`GET /api/brands/{id}/sources` →
```json
[{"id": "...", "brand_profile_id": "...", "title": "Fact Sheet", "status": "approved", "sensitivity": "normal",
  "source_type": "txt", "latest_version": 1, "created_at": "...", "updated_at": "..."}]
```
`POST` (multipart): `file`, `title`, `sensitivity` (`normal` | `confidential`), `approve` (`true` to
approve on upload) → 201 one item of the above. `.../withdraw` body `{"status": "superseded" |
"archived", "reason"}` → `{"source", "reason", "flipped": [{"content_version_id", "review_id"}]}`.
`.../versions` (multipart `file`) → `{"source", "version_number", "flipped"}`. A confidential source
in scope keeps the whole review on local Ollama only.

### Brand rules — `GET` / `PUT /api/brands/{id}/rules`

The checks are the engine's (`inkloom_verify.rules`; rule kinds and fields:
`services/verification/RULES_HANDOFF.md`, JSON Schema `services/verification/schemas/brand_rules.schema.json`).
`PUT` body `{"rules": {...}}` — a `BrandRules` object **without** `rule_set_id` / `version` (the
backend sets `rule_set_id = "brand-<id>"` and bumps `version` on every save) — or `{"rules": null}`
to remove them. Both answer `{"brand_id", "rules"}` (the stored object, or `null`).

```json
{"rules": {"prohibited_terms": [{"rule_id": "no-guarantee", "term": "guaranteed",
                                 "approved_alternative": "designed", "severity": "high"}],
           "required_terms": [{"rule_id": "req-company", "term": "Lumen Goods"}]}}
```
- Validated when saved: malformed or contradictory rules, or a NUL character → **422** whose message
  names fields and rule ids only (e.g. `conflicting rules: a requires a term that b prohibits`),
  never a configured value; nothing is stored.
- No rules (`null`) still runs the default accessibility checks on every review. `{}` is the same,
  saved explicitly.
- Every save is audited (`brand.rules_updated` / `brand.rules_cleared`). Reviews use the rules as
  they are when the review runs. Another account's brand → 404.

### `POST /api/reviews` · `POST /api/reviews/upload`

Body `{"brand_id", "title"?, "text"}` (text ≤ 100,000 chars), or multipart `brand_id`, `title`?, `file`.
Optional `Idempotency-Key` header (1–200 visible ASCII characters, else `422`) replays the first
response, also to a request sent while the first is still running (it waits for it). If the first
is still running after ~15 s, the second gets `409` "still being processed" — retry it. The same
key with a different body is `409`. A request that fails frees its key. Rate-limited per user and
account.
**201** with the Review shape below. `status`:

| `status` | When |
|---|---|
| `completed` | Every claim supported (or nothing to check) and no rule finding — **never** means approved |
| `needs_human_review` | At least one claim contradicted / unverified / errored, a rule finding, brand rules that could not (fully) run, or stub mode |
| `failed` | No approved document for the brand, or claim extraction failed (`error_summary` says why). Rule findings may still be listed. |

### Review shape (all review routes)

```json
{
  "id": "...",
  "content_version_id": "...",
  "content_item_id": "...",
  "brand_id": "...",
  "brand_name": "Kora Phones",
  "title": "Kora X2 launch ad",
  "version_number": 1,
  "text": "The Kora X2 is India's number one smartphone. It packs a 6,000 mAh battery.",
  "status": "needs_human_review",
  "report_status": null,
  "engine": {"provider": "fallback", "model_id": "gemini:gemini-3.5-flash-lite",
             "prompt_version": "extract-claims-v1", "contract_version": "0.2.0"},
  "error_summary": null,
  "served_from_cache": false,
  "required_reviewer_role": null,
  "started_at": "...", "completed_at": "...", "created_at": "...", "updated_at": "...",
  "findings": [
    {
      "finding_id": "...",
      "category": "unsupported_claim",
      "severity": "medium",
      "original_text": "The Kora X2 is India's number one smartphone.",
      "span": {"start": 0, "end": 45},
      "check_type": "retrieval",
      "explanation": "None of the approved documents mention market rankings.",
      "verification_status": "unverified",
      "suggested_correction": null,
      "requires_human_review": true,
      "evidence": []
    },
    {
      "finding_id": "...",
      "category": "contradicted_claim",
      "severity": "high",
      "original_text": "It packs a 6,000 mAh battery.",
      "span": {"start": 46, "end": 75},
      "check_type": "retrieval",
      "explanation": "The fact sheet gives a 5,000 mAh battery, not 6,000 mAh.",
      "verification_status": "contradicted",
      "suggested_correction": "It packs a 5,000 mAh battery.",
      "requires_human_review": true,
      "evidence": [
        {"id": "...", "source_id": "...", "source_version_id": "...", "quote": "Battery: 5,000 mAh.",
         "relation": "contradicts", "source_title": "Kora X2 Product Fact Sheet", "source_version_number": 1}
      ]
    }
  ]
}
```

- **`category`** (real runs): `contradicted_claim`, `unsupported_claim` (unverified — no evidence
  either way, including a citation this backend's own validator rejected), `supported_claim`,
  `engine_error` (that one claim could not be checked). `stub` marks the no-provider placeholder.
  `null` only on findings written before this field was filled.
- **`suggested_correction`**: the **whole `original_text` rewritten**, so the UI can do
  `draft.replace(original_text, suggested_correction)`. For contradicted claims it comes from the
  engine's corrector, is backed by the cited quote and re-verified as supported, and is dropped if
  this backend's evidence validation downgrades the finding. It is **evidence-backed only**: always
  `null` on unverified claims. A suggestion is only ever offered — nothing is applied automatically.
- **`safer_wording`** (unverified claims only): the engine's softened wording
  (`inkloom_verify.softening.ClaimSoftener`), also the whole `original_text` rewritten. **Not
  evidence-backed** — label it "Safer wording, not evidence-backed". Kept only if it passes this
  backend's rule check (`softening_guard.py`: no new numbers, no unproven rankings, names, prices and
  dates unchanged), else `null`; the finding stays `unverified`.
- **`verification_status: "conflicting_sources"`**: the brand's approved documents disagree about
  the claim (the engine's citation guard caught it), so it was not decided either way; the
  explanation says so and it always needs a person. Category stays `unsupported_claim`.
- **`review_reasons`** (claim findings; additive): why a person must decide - the engine's own
  values, `[]` when `requires_human_review` is false, `null` on rule and stub findings and on rows
  from before this field:

  | Value | Meaning |
  |---|---|
  | `contradicted` | an approved document says otherwise |
  | `not_enough_evidence` | no document backs it, the documents disagree, or this backend's own citation check rejected the engine's quote |
  | `error` | the claim could not be checked (provider failure, or the decision policy itself failed) |
  | `weak_evidence` | supported, but not by the best-matching passage |
  | `below_policy_strength` | supported, but on less than strong evidence |
  | `compound_under_cited` | supported, but the claim joins several facts and rests on one quote |

  The last three are on **supported** claims: show "supported, but please check: ..." rather than a
  problem.
- **`evidence[].source_title` / `source_version_number`**: the document and the version the quote was
  actually taken from (still the old number after the document gets a new version).
- `brand_name`, `content_item_id`, `title`, `version_number`, `text`: `null` only on very old rows.
- `required_reviewer_role`: always `null` on new reviews (routing is off).

**Rule findings** (brand rules and the default accessibility checks; they run on every review,
before and independent of the claim checks, with no model call, and are never served from cache):

```json
{
  "finding_id": "...", "check_type": "rule", "category": "terminology", "severity": "high",
  "original_text": "Guaranteed", "span": {"start": 0, "end": 10},
  "explanation": "\"Guaranteed\" is a prohibited term.", "verification_status": "not_applicable",
  "suggested_correction": "designed", "requires_human_review": true, "evidence": [],
  "rule_id": "no-guarantee", "rule_type": "prohibited_term", "scope": "text",
  "suggestion_basis": "brand_rule", "source_ids": []
}
```
- `category`: `terminology`, `brand_compliance` or `accessibility`. `verification_status` is always
  `not_applicable` — a rule check is not a verdict on a claim. Always `requires_human_review`.
- `scope: "document"`: something is missing (a required term, a disclaimer); the span anchors on the
  draft's first line — show it as about the whole draft.
- `suggested_correction` (terminology only) replaces `original_text`; `suggestion_basis` says why:
  `brand_rule` (configured) or `approved_document` (the rule is quoted from an approved document,
  which is then in `evidence` / `source_ids`). Evidence is kept only if that document is one of the
  brand's current approved documents and the quote is really in it; otherwise it is dropped, and so
  is an `approved_document` suggestion. Claim findings have these five fields `null`.

On the review:
- **`rules_status`**: `complete` (every check ran), `incomplete` (a check failed — never show the
  draft as rule-clean), `not_applied` (nothing ran: the stored rules no longer validate, or the
  rules module failed; `error_summary` says why, no rule finding is made up), `null` on reviews
  from before rules existed.
- **`rule_checks`**: one `{"rule_id", "rule_type", "category", "status", "findings", "reason"}` per
  rule; `status` is `passed`, `violated`, `not_checkable` (the draft has nothing to inspect — no
  links, headings, images, media or colours; show **"not checked"**, never "passed") or `error`.
  `null` when the rules did not run.

### `GET /api/reviews` — review queue

Query: `status` (repeatable — any matches), `brand_id` (optional), `limit` (default 50, 1–100),
`offset` (default 0). **200**: a plain JSON **array** of full Review objects (above), newest first,
from the caller's account only. Empty → `[]`. Another account's `brand_id` → 404. Bad
`status`/`limit`/`offset`/`brand_id` → 422.

```
GET /api/reviews?status=needs_human_review&status=completed&limit=20
```

### `POST /api/reviews/{id}/rerun` · content versions · decisions

- `rerun` → 201 a new Review of the same version (the old review is untouched).
- `POST /api/content/{content_item_id}/versions` body `{"text"}` → 201
  `{"content_version_id", "version_number", "is_current": true, "review": <Review>}`.
- `GET /api/content/{content_item_id}/history` →
  `{"content_item_id", "title", "versions": [{"id", "version_number", "is_current", "created_by",
  "created_at", "reviews": [{"id", "status", "created_at"}], "decisions": [<ApprovalEvent>]}]}`.
- `POST /api/content-versions/{id}/approve` → 201 ApprovalEvent:
  `{"id", "content_version_id", "version_number", "action": "approved", "actor_user_id", "note": null, "created_at"}`.
  409 if not decidable, stale, or a cited document was withdrawn/replaced ("rerun the review first").
- `POST /api/content-versions/{id}/request-changes` body `{"decision": "changes_requested" | "rejected",
  "note"?}` → 201 ApprovalEvent. 409 only if the review is not decidable.

### Intent-lock — `GET` / `PUT /api/content-versions/{id}/locks`

`PUT` body `{"locked_phrases": ["₹2,499", "Lumen Pods"]}` replaces the version's list → `{"content_version_id",
"locked_phrases"}`. Exact, case-sensitive phrases (the engine's rules: at most 50, each 1–200
characters, duplicates dropped; anything else → 422). A phrase that occurs n times must still occur
n times.
- **Enforced on the server, whatever the engine does:** the corrector and softener get the locks, and
  the backend re-checks every suggestion (claim corrections, safer wording, rule suggestions) before
  storing it. A lock-breaking suggestion is never stored or offered.
- Locks set **after** a review ran: a stored suggestion that would break them is withheld when read
  (`suggested_correction` / `safer_wording` `null`, `withheld_by_intent_lock: true`). Re-run for a
  suggestion that keeps them. Locks are part of the result-cache key.
- A new version (`POST /api/content/{id}/versions`) inherits the current version's locks. The
  user's own edits are **warned, not blocked**: the response has `lock_warnings: [{"phrase",
  "occurrences_before", "occurrences_after"}]` for every locked phrase the edit kept fewer times
  than the previous version (empty when all are kept); the version is saved either way.
- The review shape carries `locked_phrases`. Audited as `content_version.locks_updated` (count only).

### Dismiss and comments — `/api/findings/{finding_id}/...`

- `POST .../dismiss` (optional body `{"note"}`) → 201 `{"id", "finding_id", "action": "dismissed", "note",
  "actor_user_id", "created_at"}`; already dismissed → 409. `POST .../restore` undoes it; not dismissed
  → 409. While dismissed, the finding has `"dismissal": {"by_user_id", "at", "note"}` (else `null`).
- **Dismissing never changes the finding** (verdict, evidence, explanation, suggestions) or the
  review's status. Dismissed is **not** "supported": show "Dismissed by you", never "verified".
  A re-run creates new findings; dismissals don't carry over.
- `GET .../comments` → oldest first `[{"id", "finding_id", "author_user_id", "body", "created_at"}]`;
  `POST .../comments` `{"body"}` (1–2000 characters, not blank) → 201 one comment. Each finding
  has `comment_count`.
- Audited as `finding.dismissed` / `finding.restored` / `finding.commented` (the comment text is
  never in the audit log). Another account's finding → 404 like a random id.

### `GET /api/analytics/brand-risk` — Insights

Query: `brand_id` (the page always sends it; omitted = every brand in the account), `days`
(default 30, 1–365). **200**, computed only from real rows for reviews created in the period:

```json
{
  "top_categories": [{"category": "unsupported_claim", "count": 4}, {"category": "contradicted_claim", "count": 2}],
  "median_turnaround_minutes": 95.0,
  "re_review_rate": 0.25,
  "queue_age_minutes": {"median": 180.0, "oldest": 2880.0},
  "sample_size": 12,
  "dismissed_finding_rate": {"numerator": 1, "denominator": 6, "value": 0.1667}
}
```
- `top_categories`: finding counts by `category`, excluding `stub`, `supported_claim` and null;
  descending; top 6.
- `median_turnaround_minutes`: review created → its first decision; `null` if none decided.
- `re_review_rate`: share of the period's content items with 2+ versions; `null` if no items.
- `queue_age_minutes`: now − created for the period's reviews waiting for a decision (same definition
  as `open_review_count`); `null`s if none.
- `sample_size`: reviews counted. Zero reviews → `{"top_categories": [], "median_turnaround_minutes":
  null, "re_review_rate": null, "queue_age_minutes": {"median": null, "oldest": null}, "sample_size": 0}`.
- `dismissed_finding_rate` (additive): of the period's flagged findings (the same set
  `top_categories` counts), how many the user has dismissed. Only each finding's latest decision
  counts (dismissed then restored = not dismissed). `value` is `null` when nothing is flagged. A
  live false-positive signal from the user's own decisions, not a measured accuracy.
- Another account's `brand_id` → 404; bad `days` → 422.

### `GET /api/evaluations/latest` · `POST /api/evaluations` — Trust Scorecard

`POST` runs the engine's labelled claim-verification evaluation
(`services/verification/eval/dataset.jsonl`, 80 claims: 25 supported, 32 contradicted, 23 without
evidence; refused if it no longer matches the engine's label lock) synchronously through this
backend's provider chain, bounded by the engine's call budget (`EVAL_MAX_CALLS`,
`EVAL_DEADLINE_SECONDS`). Takes ~1–4 minutes. **201**, and `GET .../latest` returns the same:

```json
{
  "catch_rate": 1.0,
  "false_positive_rate": 0.0,
  "per_check": [
    {"check": "verification", "catch_rate": 1.0, "false_positive_rate": 0.0, "n": 80},
    {"check": "numeric", "catch_rate": 1.0, "false_positive_rate": 0.0, "n": 26},
    {"check": "absent_fact", "catch_rate": 1.0, "false_positive_rate": null, "n": 9}
  ],
  "sample_size": 80,
  "run_at": "2026-10-24T01:31:02Z",
  "id": "...",
  "status": "partial",
  "engine_prompt_version": "verify-claim-v1",
  "dataset_version": "dataset.jsonl@0516b9b8ce5b",
  "limits_note": "Measured on 80 labelled claims from the engine's own test set (...). This is a small test set: it shows the checker was tested, not a universal accuracy figure, ...",
  "latency_ms_p50": 1098.0,
  "provider_failure_rate": 0.0364,
  "coverage": "verifier_only",
  "by_split": {
    "dev": {
      "n": 55,
      "catch_rate": {"numerator": 37, "denominator": 37, "value": 1.0},
      "false_positive_rate": {"numerator": 0, "denominator": 18, "value": 0.0}
    },
    "heldout": {
      "n": 25,
      "catch_rate": {"numerator": 18, "denominator": 18, "value": 1.0},
      "false_positive_rate": {"numerator": 0, "denominator": 7, "value": 0.0}
    }
  },
  "provider_mode": "live"
}
```
- `catch_rate` = claims labelled contradicted or no-evidence that were flagged (contradicted or
  unverified) / all such claims — recall on claims that should be flagged.
- `false_positive_rate` = claims labelled supported that were flagged / all supported claims.
- A claim with no verdict (provider failure, budget) counts as not flagged and is reported in
  `provider_failure_rate`; `status` is `partial` when there were any. `null` = zero denominator.
- `per_check`: `verification` overall, then one entry per labelled kind of hard case (numeric, date,
  named_entity, prompt_injection, …), largest first.
- Model-reported confidence is never used.
- **No `contract` key**, ever: the Scorecard page tells this shape from the engine's older
  `evaluation-summary-v1` by "has `catch_rate` and `per_check`, and no `contract` key". New fields
  are additive only.

Additive fields (the Scorecard's `Evaluation` type is unchanged):

- `coverage`: what the numbers measure. Always `"verifier_only"` today: each labelled claim goes
  through BM25 retrieval over its reference documents, the verifier and the engine's citation guard
  (`run_eval.py --pipeline verifier`). **Not** covered: claim extraction from a draft, suggested
  corrections, this backend's own citation re-validation, or the human-review decision.
  `"full_pipeline"` is reserved for a run that goes through the whole review path. Runs stored
  before this field existed are reported as `"verifier_only"`, which is correct, because the runner
  has never measured anything else.
- `by_split`: the same `catch_rate` and `false_positive_rate` for the dataset's `dev` and
  `heldout` records, each with its own `numerator` / `denominator` (`null` value = zero
  denominator), plus `n` = records in that split. Held-out records are never used to choose the
  engine's thresholds, so **held-out is the figure to quote**; the pooled top-level numbers mix in
  the dev records the engine was tuned on. Held-out is small (25 claims: 18 to flag, 7 supported),
  so one claim moves its catch rate by ~6 points and its false-positive rate by ~14. `null` for runs stored before this field existed (their per-claim
  results were not kept, so the split cannot be recomputed).
- `provider_mode`: who answered, from the model ids that actually replied. `"live"` = only real
  models, `"scripted"` = only the offline scripted provider (tests / demo seed, model ids
  `scripted/…`), `"mixed"` = both, `null` = no model answered.

The engine's own full report (all metrics, per split, both pipeline modes) is a CLI / CI artifact
from `services/verification/eval/run_eval.py`, not an endpoint.

Errors: `GET .../latest` with no run yet → **404** `no evaluation has been run yet`. `POST` with no
provider configured → **409**, nothing stored. `POST` where more than 20% of claims got no verdict
(`EVAL_MAX_PROVIDER_FAILURE_RATE`) → **409** "…was not saved…", nothing stored (its real calls stay in
`external_call_log`). More than one run per user per 10 minutes (stored or discarded) → **429**.

## Known limits

- Rate limiting is in-process memory (single worker); idempotency keys and the evaluation's
  10-minute limit are in the database.
- No org switcher, no invites, no password reset, no email verification (individual accounts).
- A full `pytest` run wipes the database (the migrations round-trip test) — reseed afterwards with
  `scripts/seed.py --reset`.
- Image, video and colour accessibility checks only see what is in the text (Markdown / HTML);
  uploads don't pass their images or media to the rules yet, so those checks are `not_checkable`.
- Not deployed yet.
