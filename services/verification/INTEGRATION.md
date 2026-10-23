# Integrating the verification engine

This is for Member 3 (backend), who calls the engine, and Member 1 (frontend), who displays its
results through the backend. It describes the engine as built and tested on 2026-10-22, against
Member 3's published contract in [`contract/`](../../contract/README.md) (draft v0.1.0).

## Architecture

```
VerificationRequest (content + reference documents chosen by the backend)
  │
  ▼ inkloom_verify.pipeline.verify_request(request, provider)
  1. Claim extraction       extraction.py   LLM call per 40 sentences; meaning checks; verbatim fallback
  2. Evidence retrieval     retrieval.py    BM25 over this request's documents only; no LLM
  3. Claim verification     verification.py one LLM call per claim, given only that claim's passages
  4. Citation guard         citation_guard.py  every quote checked against the retrieved passage
  5. Correction             correction.py   CONTRADICTED claims only; evidence-only, minimal, re-checked
  6. Score + scope check    schemas.ReportScore, scope.check_report_scope
  ▼
VerificationReport (results, errors, status COMPLETED | PARTIAL | FAILED, score, provenance)
```

- **One entry point:** `verify_request` is a plain function, so the backend calls the engine
  in-process (`contract/README.md`). There is no engine HTTP service, and none is needed.
- **No exceptions for engine-side problems.** `verify_request` doesn't raise for content, model
  or provider problems. They become `ERROR` results, request-level `errors`, and a `PARTIAL` or
  `FAILED` status. Unexpected exceptions, and reports that fail their own scope check, become a
  `FAILED` report with `INTERNAL_ERROR`.
- **Provider calls go through `LLMProvider`.** Today that is `providers.openrouter.OpenRouterProvider`.
  A backend-owned adapter can replace it if it implements the same small interface (SECURITY.md,
  requirement 6).

## Environment setup

```sh
cd services/verification
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest                       # 538 tests; no network, no keys needed
```

Requires Python 3.11+ (tested on 3.14.6). LLM stages need two environment variables, which are
**never committed**; [`.env.example`](.env.example) lists them with empty values:

| Variable | Required | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | OpenRouter key, server-side only |
| `INKLOOM_LLM_MODELS` | yes | Comma-separated OpenRouter model ids, tried in order. Copy exact ids from openrouter.ai/models (team choice: Gemini Flash, then Llama). |
| `INKLOOM_LLM_TIMEOUT_SECONDS`, `INKLOOM_LLM_MAX_RETRIES`, `INKLOOM_LLM_SEED`, `INKLOOM_LLM_STRUCTURED_OUTPUT`, `INKLOOM_LLM_DATA_COLLECTION`, `OPENROUTER_BASE_URL` | no | See PROMPTS.md |

The engine reads only the process environment. It doesn't load `.env` files itself.

To run the documented example request against a live model:

```sh
PYTHONPATH=src python -m inkloom_verify.pipeline --request examples/end_to_end/request.json --out reports/e2e.json
```

> The current public endpoint, its error mapping and the contract change log are in
> [API_HANDOFF.md](API_HANDOFF.md). This file keeps the history and the in-process notes.

## For Member 3: calling the engine

**Security requests from the engine's Phase 7 review (2026-10-23).** These are read-only findings
in your files, which I haven't changed:

1. **Gemini errors:** use fixed messages (status code and category only), not `error.message`.
   Provider text can echo the submitted content.
2. **Timeout and connect errors (Gemini, Groq, Ollama):** use `type(error).__name__`, not
   `str(error)`.
3. **Keys:** call `inkloom_verify.security.register_secret(key)` when each provider is built,
   and attach `install_redaction` to your log handlers.
4. **Responses:** cap the body size (the engine's adapter uses 2 MB) and treat `RecursionError`
   from JSON parsing as malformed output.
5. **Strict JSON (prompts Phase 5):** parse model replies with
   `inkloom_verify.providers.base.parse_json_object` instead of `json.loads` in your Gemini, Groq
   and Ollama adapters. `json.loads` silently merges duplicate keys (the last value wins) and
   accepts `NaN`.
6. **Pipeline:** call `inkloom_verify.pipeline.verify_request(request, provider)` instead of
   chaining the stages. You get the report-scope check, the call budget, corrections and
   `reference_set_id` on every passage. Your evidence validator still runs on its output.

Already done on your side (verified by reading): confidential sources go to local Ollama only,
and the independent evidence validator.

**Contract 0.2.0 (2026-10-23).**
- `Claim.text` is now exactly the content at `source_span`. Your `pipeline.py` already stores
  `claim.source_span.slice(content)`, so nothing changes for you.
- The standalone rewording, if any, is the new `Claim.normalized_text`.
- `CONTRACT_VERSION` is `"0.2.0"`, so new reviews will store that in `engine_contract_version`.
- Passages may carry `reference_set_id`.

See CONTRACTS.md, "Changes in 0.2.0".

```python
# services/api: add the engine as a dependency, e.g. `pip install -e ../verification`
from inkloom_verify.pipeline import verify_request
from inkloom_verify.providers.openrouter import OpenRouterProvider
from inkloom_verify.providers.base import ProviderNotConfiguredError
from inkloom_verify.schemas import VerificationRequest
from inkloom_verify.integration import finding_fields

request = VerificationRequest(
    request_id=str(review.id),                 # yours (contract/README.md, decision 8)
    tenant_id=str(org_id),                     # from the authenticated membership only
    content={"content_id": str(content_version.id), "text": content_version.text},
    references=[                               # approved sources of this brand only
        {"doc_id": str(sv.id), "version": str(sv.version_number), "title": source.name, "text": sv.text}
        for source, sv in approved_source_versions
    ],
)
try:
    provider = OpenRouterProvider.from_env()   # build once per process and reuse
except ProviderNotConfiguredError:
    ...                                        # review -> failed, error code PROVIDER_NOT_CONFIGURED
report = verify_request(request, provider)     # never raises for content/model/provider problems
findings = [finding_fields(r, content_version.text) for r in report.results]
```

**Mapping to your contract.** `integration.finding_fields` implements your proposed mapping, and
`tests/test_pipeline.py` validates its output against your `finding.schema.json` and
`review.schema.json`:

| Your field | From the engine |
|---|---|
| `verification_status` | `SUPPORTED`→`supported`, `CONTRADICTED`→`contradicted`, `NOT_ENOUGH_EVIDENCE`→`unverified`, `ERROR`→`unverified` (your decision 2) |
| `original_text`, `span` | the claim's `source_span` in the content (code points) |
| `suggested_correction` | the source text with the correction applied (`integration.corrected_text`). Only set when `correction_attempt.status` is `proposed`. |
| `requires_human_review` | `result.requires_human_review`: true unless `SUPPORTED`, and true for `SUPPORTED` on `weak` evidence |
| `explanation` | `model_rationale`: model-written, cleaned, never evidence |
| `evidence[]` | the citations: `quote`, and `relation` (`supports` / `contradicts`). `doc_id` is whatever you passed as `doc_id`; the recommended value is `source_version_id`. |
| `engine_claim_id` (your DB column) | `claim.claim_id` |
| `reviews.status` | Not from a single field. `FAILED` → `failed`. Otherwise, if `report.score.requires_human_review` → `needs_human_review`, else `completed`. **Never `approved`.** |
| `reviews.report_status`, `engine.*` | `report.status`, `report.provenance.provider`, `.model_id`, `.prompt_versions`, `report.contract_version` |
| `error_summary` | `report.errors[*].message`, or a result's `error.message`. These are safe to show. |

Fields you own and the engine never sets: `finding_id`, `severity`, `category`, `check_type`,
evidence `id`, `source_id`.

**Required before going live** (from SECURITY.md):

1. Choose `references` only from approved sources of the authenticated organisation and brand.
2. Run `scope.check_report_scope(request, report)` again on your side if the report is stored
   and reloaded. The engine already runs it before returning.
3. Never log `str(ValidationError)`.
4. Attach `security.install_redaction` to your log handlers. Your `logging.py` doesn't redact yet.
5. Route confidential sources away from cloud providers.
6. Rate-limit per organisation. Each claim costs one or more model calls.
7. `reviews.prompt_version` is a single string, but the engine uses three versioned prompts
   (`report.provenance.prompt_versions`). Store the dict as JSON, or store all three.

## Serving `POST /v1/verify` from the backend (Phase 2)

Mount the engine's router in `services/api/src/inkloom_api/main.py`. **That is Member 3's file;
this change is theirs to make**:

```python
from inkloom_verify.api import create_verify_router
from inkloom_verify.pipeline import PipelineEngine
from inkloom_verify.providers.openrouter import OpenRouterProvider

def authenticated_tenant(auth: AuthContext = Depends(get_current_membership)) -> str:
    return str(auth.organisation_id)                        # the tenant comes from the token only

def reference_set_loader(tenant_id: str, reference_set_id: str) -> list[ReferenceDocument] | None:
    ...  # this organisation's approved source documents for the set, or None; your query, your session

engine = PipelineEngine(OpenRouterProvider.from_env())     # raises ProviderNotConfiguredError if unset
app.include_router(create_verify_router(engine, authenticated_tenant=authenticated_tenant,
                                        reference_set_loader=reference_set_loader))
```

**The public request (Phase 2) carries a `reference_set_id` but no documents and no tenant.**
- Your loader is called with the authenticated tenant, never anything from the body.
- Returning None or an empty list gives 404 `NOT_FOUND`, the same answer for "not yours" and
  "doesn't exist". An exception gives 500. In both cases the engine is never called.
- You decide what a reference set is: for example, a brand's latest approved sources.
- Confidential-source routing stays yours.
- `authenticated_tenant` is required: the router refuses to start without it, outside the
  development app.

Your existing error handlers and `RequestIdMiddleware` then apply unchanged. A test mounts the
router inside your real `install_error_handlers` and `RequestIdMiddleware` (imported read-only
from `services/api/src`). It checks the 200, 400, 404 and 503 responses, and that `request_id`
matches your `X-Request-ID`.

**Error mapping (Phase 3):**
- The router answers its own errors in the shared envelope: 400 `INVALID_INPUT`, 404
  `REFERENCE_SET_NOT_FOUND`, 409 `REFERENCE_SET_EMPTY`, and 422 / 429 / 504 / 503 for runs with no
  results (CONTRACTS.md, "HTTP endpoint"). So your handlers don't turn them into 422
  `VALIDATION_ERROR` or `INTERNAL_ERROR`.
- **Pass `request_id_provider=get_request_id`** (from `inkloom_api.logging`), so a 400 raised before
  the body is valid carries your request id.
- **Your loader must return None for an unknown set**, and an empty list only for a set that
  exists with no documents. The two give different answers (404 vs 409).
- Only 500s still go through your handler.

Two notes for Member 3:

- **Your `HTTPException` handler maps only 401/403/404/409**, so any other status becomes
  `INTERNAL_ERROR`. The router therefore reports an over-size body as a validation error (422
  `VALIDATION_ERROR`), not as a 413.
- **Your `errors.py` uses `status.HTTP_422_UNPROCESSABLE_ENTITY`**, which current Starlette
  deprecates in favour of `HTTP_422_UNPROCESSABLE_CONTENT`. The value is the same 422. The tests
  surface this as a deprecation warning.

For local development without the backend (no authentication, so never expose it):

```sh
INKLOOM_ENGINE_MODE=live PYTHONPATH=src python -m uvicorn inkloom_verify.api:create_dev_app --factory --port 8000
# http://127.0.0.1:8000/docs   (fake mode answers 503: no canned results on the public endpoint)
```

The development app serves one example reference set (the documents of
`examples/verification_request.json`, under its `reference_set_id`) for its unauthenticated
development tenant.

Example payloads: [`examples/api/`](examples/api/) contains the request, a 200 response (scripted
model, real pipeline), and 422, 404 and 503 errors. A test keeps them in sync.

## For Member 1

- **Your review screen (`app/app/review/page.tsx`) is static markup today:** no data types, no
  `fetch`. Rendering a real response needs a typed client for Member 3's `GET /api/reviews/{id}`
  (`contract/schemas/review.schema.json`). For layout work before then,
  `examples/api/verify_response.json` (the public engine Report) and
  `contract/examples/review_success.json` show the shapes. Source titles aren't in the engine's
  Report (Evidence carries `doc_id`); they come from the backend's sources.
- **Display data comes through Member 3's API**, not from the engine directly. The engine's
  strings are untrusted: render claim text, quotes, explanations and corrections **as plain
  text**. No HTML, no Markdown, no auto-linked URLs.
- **Offsets are Unicode code points** (`Array.from(text)`), as both contracts state.
- **`unverified` means "missing evidence", not false.**
- **`completed` is not approved.** The report's `requires_human_review` and reasons explain why
  a person must look.

## Example payloads

These are in [`examples/end_to_end/`](examples/end_to_end/) and are kept in sync by a test:

- `request.json`: a `VerificationRequest` built from the documented reference documents of
  dataset v1 (the Lumen Pods fact sheet and company facts; synthetic, see EVAL.md).
- `report.scripted.json`: the `VerificationReport` that `verify_request` produced for it with
  **a scripted model, not a live LLM**. It shows every shape: a `SUPPORTED` result, a
  `CONTRADICTED` result with a re-checked correction, a `NOT_ENOUGH_EVIDENCE` result, an `ERROR`
  result (a scripted timeout), status `PARTIAL`, and a score that requires human review. Use it
  for shapes, not as a quality sample.
- `backend_findings.json`: `integration.finding_fields` for each result.

Field-by-field schemas are in [`schemas/`](schemas/) (JSON Schema) and [CONTRACTS.md](CONTRACTS.md).

## What has been measured, and what hasn't

Results from 2026-10-22, at commit `b8bf75c` with the Phase 6–8 changes uncommitted:

| Measurement | Result | What it establishes |
|---|---|---|
| Unit and integration tests | **538 passed** (29 end-to-end pipeline tests) | The workflow, safeguards and failure handling behave as specified **with scripted model replies** |
| Live end-to-end run and live evaluation (`--verifier openrouter`) | **Not run**: no `OPENROUTER_API_KEY` or `INKLOOM_LLM_MODELS` here; both commands exit 2 with the configuration message | Nothing about real model accuracy |
| Verdict accuracy, per-class P/R/F1, abstention rate and citation validity **of the live engine** | **Not measured** | Requires the live run |
| Abstain baseline on dataset v1 (50 records) | 28.0% accuracy (14/50); held-out 33.3% (5/15) | A floor only |
| BM25 retrieval: gold evidence among the top 5 passages | 94.4% (34/36); held-out 90.0% (9/10) | Real. Misses: v1-021 (coverage gate), v1-027 ("cost" vs "Price") |
| Citation guard on all 39 gold quotes, and corrupted versions | 39/39 accepted; 145/145 fabricated or misattributed versions rejected | The guard enforces verbatim, in-request evidence. **It is not the live engine's citation validity.** |
| Correction checks on 46 labelled candidate edits | 28/28 bad edits rejected; 17/18 good edits accepted | The checks behave as designed on known patterns (labels written by me, unreviewed) |
| Dependency audit (`pip-audit`) | No known vulnerabilities | As of this date |

**Citation validity on the evaluation set has not been measured for the engine.** By
construction, any citation in an accepted `SUPPORTED` or `CONTRADICTED` result has passed the
guard. The contract makes any other result unconstructible, and the guard rejected every
corrupted quote above. That is a design guarantee, not a measured rate. The definition of done
for this phase requires the measured figure, so **this phase remains incomplete until the live
evaluation is run.**

**Tenant isolation:**
- **Engine boundary: tested.**
  - No state crosses requests.
  - Two tenants run through one provider stay separate.
  - Foreign evidence is refused before reaching a model.
  - A report containing foreign evidence fails the pipeline.
- **API, database and cache: not tested by me.** Member 3's `tests/test_tenant_scoping.py`
  exists but needs Postgres. Docker wasn't running on this machine, and I didn't set up the
  local Postgres for it, so those tests were not run.

## Known limitations and failure examples

- **Retrieval is lexical.** "Lumen Pods cost €99" never retrieves "Price: €129", so the engine
  can only answer `NOT_ENOUGH_EVIDENCE`, and the claim goes to a person. There's a test for this.
- **A model persuaded by injected text can quote it verbatim and pass the guard** (dataset record
  v1-032). Only verdict accuracy, which needs the live run, measures this.
- **Strict checks reject some good output:** paraphrased corrections ("cannot" vs "not"),
  inflections, spelled-out numbers. These become human-review items.
- **No model call runs in parallel.** A 200-claim request makes hundreds of sequential calls.
- **Both datasets are synthetic, small (50 verification records, 19 correction cases) and
  unreviewed by a person.**
- **Severity, `conflicting_sources` and confidential routing** are open cross-member decisions
  (CONTRACTS.md, questions 12–15).
