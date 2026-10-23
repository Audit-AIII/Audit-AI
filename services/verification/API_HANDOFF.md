# Verification engine: public API handoff

For Members 1 and 3. This describes `POST /v1/verify` and its public contract as implemented in
[`src/inkloom_verify/api_contract.py`](src/inkloom_verify/api_contract.py) and
[`src/inkloom_verify/api.py`](src/inkloom_verify/api.py).
[CONTRACTS.md](CONTRACTS.md) holds the full contract, including the engine's internal 0.2.0
models. If this document and the code disagree, the code and its tests win.

**Integration status (checked 2026-10-23 at `c4df588`): not integrated.**
- **Member 3's backend** doesn't mount `POST /v1/verify`. It calls the engine's internal stages
  directly (`services/api/src/inkloom_api/engine/pipeline.py`).
- **Member 1's frontend** reads Member 3's `GET /api/reviews/{id}`, not this endpoint.
- Nothing below has been confirmed by either team.

---

## 1. Request

`POST /v1/verify`, `Content-Type: application/json`. Schema:
[`schemas/public_verify_request.schema.json`](schemas/public_verify_request.schema.json).

```json
{
  "request_id": "req_123",
  "content": {"id": "c1", "text": "Our plan costs $49/month and includes 5 seats."},
  "reference_set_id": "ref_brand_2026",
  "options": {"suggest_corrections": true, "max_claims": 50}
}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `request_id` | string | yes | Id pattern `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. Echoed in the response. |
| `content.id` | string | yes | Id pattern |
| `content.text` | string | yes | Not empty or whitespace only. At most `max_content_chars` (the router's setting; at most 100,000). |
| `reference_set_id` | string | yes | Id pattern. Resolved by the backend's loader for the **authenticated** tenant. |
| `options.suggest_corrections` | boolean | no (default `true`) | Strict boolean (no `"true"`, no `1`) |
| `options.max_claims` | integer | no (default `200`) | Strict whole number, 1–200 |

**Refused:** any other field. That includes `tenant_id` (the tenant comes only from
authentication) and `references` (the documents come only from the loader).

## 2. Response (200)

Schema: [`schemas/public_report.schema.json`](schemas/public_report.schema.json). Every field is
always present in responses. A field that doesn't apply is `null` or `[]`.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `"0.1.0"` | On the report and on every claim, verdict and evidence item |
| `request_id` | string | The request's |
| `claims[]` | array of `{claim, verdict}` | In content order |
| `claims[].claim.claim_id` | string `^clm_[A-Za-z0-9_-]{1,64}$` | |
| `claims[].claim.text` | string | Exactly the content at `span` |
| `claims[].claim.span` | `{start: int, end: int}` | Section 6 |
| `claims[].verdict.status` | enum | Section 3 |
| `claims[].verdict.confidence` | number 0–1 | `0.0`, `0.33`, `0.67` or `1.0` (below) |
| `claims[].verdict.evidence[]` | array of `{schema_version, doc_id, location, quote}` | Section 4 |
| `claims[].verdict.correction` | object or `null` | Section 5 |
| `claims[].verdict.needs_human_review` | boolean | |
| `claims[].verdict.error_code` | string or `null` | Only on `ERROR` (section 8) |
| `metadata.content_hash` | string | Lowercase hex SHA-256 of `content.text`, UTF-8 |
| `metadata.errors[]` | array of `{code, message}` | Request-level problems in a report that still has results (section 8) |
| `metadata.prompt_versions` | object | The prompt version actually sent per stage, e.g. `{"extract_claims": "extract-claims-v1", "verify_claim": "verify-claim-v1"}`. Keys are `extract_claims`, `verify_claim` and `correct_claim`; a stage that made no model call is absent (added in prompts Phase 1). |

**`confidence` is not a probability.** It's a fixed map of the engine's evidence strength:
- none → 0.0;
- weak → 0.33 (the support comes only from a lower-ranked passage);
- moderate → 0.67;
- strong → 1.0.

It has never been calibrated.

**`needs_human_review`** is true for every verdict except `SUPPORTED`, and also for `SUPPORTED`
with confidence below 0.67.

## 3. Verdict values

| `status` | Meaning | Evidence | Correction | Review |
|---|---|---|---|---|
| `SUPPORTED` | The references back the claim | At least one item | never | Only if confidence < 0.67 |
| `CONTRADICTED` | The references say otherwise | At least one item | An outcome, when corrections are requested | always |
| `NOT_ENOUGH_EVIDENCE` | Not decidable from the references, including when they disagree with each other | none required; the engine sends none | never | always |
| `ERROR` | This claim couldn't be checked | none | never | always; `error_code` says why |

`NOT_ENOUGH_EVIDENCE` means *unverified*, never *false*.

## 4. Evidence validation

Every evidence item is a quotation checked in code before it's returned:
- the `quote` is exactly the text at `location` in document `doc_id`, after normalising only
  whitespace and quote marks;
- it comes from a passage retrieved for this claim, from this request's reference set;
- it's at least two words, and doesn't drop a "not" in its clause.

For `SUPPORTED`, the quotes must also carry the claim's numbers, units, dates and qualifiers ("up
to"), and its names must appear in the cited passages.

If the documents disagree about the claim's figure, the answer is downgraded to
`NOT_ENOUGH_EVIDENCE`. A model's answer that fails any check is also downgraded to
`NOT_ENOUGH_EVIDENCE`: never kept, never repaired.

`doc_id` is the backend's document id from the loader. **Titles and versions aren't in the
response;** take them from your own sources.

## 5. Corrections

- **Only for `CONTRADICTED`, and only when the request asks (`options.suggest_corrections`, default
  true) _and_ the server allows it** (`PipelineConfig.correct_contradicted`). A request can't turn on
  what the server turned off.
- When it's false, or the server has corrections off, no verdict carries a correction and the
  engine doesn't attempt one.
- If the request asked but the server has them off, `metadata.errors` says so:
  `INVALID_REQUEST`, "Corrections were requested but are disabled on this server." (prompts
  Phase 4)
- When it's true, every `CONTRADICTED` verdict carries one of three outcomes:
  - `{"status": "proposed", "span", "original_text", "replacement_text", "evidence"}`;
  - `{"status": "needs_human_review"}` (no safe correction exists);
  - `{"status": "failed"}` (the correction step couldn't run).
- **A proposed correction:**
  - `span` is in **content** coordinates, inside the claim's span, and `original_text` is the
    content there;
  - every word, number with its unit, date and name it adds comes from its `evidence`;
  - it drops no unit or qualifier, changes few words, and re-checks as `SUPPORTED`.
- The correction never replaces the verdict: the claim stays `CONTRADICTED`.

## 6. Spans and offsets

- `span` and `location` are **half-open `[start, end)` in Unicode code points**: Python string
  indexes, `Array.from(text)` in JavaScript.
- They are **not** UTF-16 units (`text.length`, `text.slice`) and not bytes. They differ for
  emoji and other characters outside the Basic Multilingual Plane.
- `span` indexes into `content.text`. `location` indexes into the reference document's text.

## 7. Errors

Every non-200 response uses one envelope:

```json
{"error": {"code": "RATE_LIMITED", "message": "The AI provider is rate limiting requests; retry later.", "request_id": "req_123", "retry_after": 20}}
```

`retry_after` (whole seconds) appears only on 429, which also sends the `Retry-After` header.
Messages are fixed per code: nothing from a provider, a document or the request is echoed.

| HTTP | `code` | When |
|---|---|---|
| 400 | `INVALID_INPUT` | Malformed JSON, schema violation, empty or over-long content, body too large. The message lists field locations only. |
| 404 | `REFERENCE_SET_NOT_FOUND` | The loader returned `None`: an unknown set, or another tenant's (the same answer either way) |
| 409 | `REFERENCE_SET_EMPTY` | The loader returned an empty list |
| 422 | `UNPARSEABLE_MODEL_OUTPUT` | No results: the model output was still invalid after one repair attempt |
| 429 | `RATE_LIMITED` | No results: the provider rate-limited. `retry_after` is the provider's value, else 30 s (configurable). |
| 504 | `PROVIDER_TIMEOUT` | No results: the provider didn't answer in time |
| 503 | `PROVIDER_NOT_CONFIGURED`, `PROVIDER_QUOTA_EXCEEDED`, `PROVIDER_ERROR`, `LIMIT_EXCEEDED` | No results, for these reasons; also the development (fake) engine |
| 500 | `INTERNAL_ERROR` | An unexpected failure, a loader failure, unusable documents, or a report that doesn't answer its request (from the host app's handler) |

**`request_id` in errors:** the body's, once the body is valid. Before that, the host's
`request_id_provider`, else the `X-Request-ID` header, else a new id.

**Known gaps** (strict expected-failure tests in `tests/test_contract_e2e.py`):
- A wrong method or an unknown path returns FastAPI's default `{"detail": ...}` body, not the
  envelope. This happens in the dev app and in Member 3's handlers.
- A chunked body (no `Content-Length`) isn't size-checked before parsing.

## 8. Partial failure

- **One claim's failure stays with that claim:** it becomes `ERROR` with its own `error_code`,
  no evidence, no correction, confidence 0, and review required. Its id, text, span and position
  are kept.
- **Every other claim's result is unchanged,** including `NOT_ENOUGH_EVIDENCE` results.
- **What counts as a claim's failure:** a provider error (its own code), or an unexpected
  exception (`INTERNAL_ERROR`).
- **A correction step that fails** keeps the `CONTRADICTED` verdict, with correction status
  `failed`.
- **A report in which every claim failed** is still a 200.
- **Problems that aren't about one claim,** such as sentences the model didn't classify, are
  listed in `metadata.errors` beside the results.
- **No results at all** (for example, extraction failed) → the HTTP errors in section 7.
- **A result that doesn't belong to its request** fails the whole run (500).
- **Report codes vs HTTP codes:** reports keep the engine's codes. The HTTP code for a run with no
  results maps one to one from them:

  | Report (engine) code | HTTP status and code |
  |---|---|
  | `MALFORMED_MODEL_OUTPUT` | 422 `UNPARSEABLE_MODEL_OUTPUT` |
  | `PROVIDER_RATE_LIMITED` | 429 `RATE_LIMITED` |
  | `PROVIDER_TIMEOUT` | 504 `PROVIDER_TIMEOUT` |
  | `INTERNAL_ERROR` | 500 `INTERNAL_ERROR` |
  | anything else | 503, the same code |

## 9. Schema versions

| Contract | Field | Value | Where |
|---|---|---|---|
| Public (this document) | `schema_version` | `"0.1.0"` | The report and every claim, verdict and evidence item; any other value is refused |
| Internal (Member 3's in-process use) | `contract_version` | `"0.2.0"` | `VerificationRequest`, `VerificationReport`, `EngineProvenance`; `"0.1.0"` is refused |

Both are drafts. Several additions were made inside each version without a bump (section 13);
**freezing or bumping them is an open decision.**

## 10. Fixtures

In [`examples/public/`](examples/public/). This is the repository's fixture location; there is no
`tests/fixtures/`.

| File | Use |
|---|---|
| `supported.json`, `contradicted.json`, `not_enough_evidence.json`, `error.json` | One complete Report per status. For UI states, and for checking a client's parser. |
| `mixed_report.json` | Two failures beside three kept results: the partial-failure case |
| `report.json` | A real pipeline run (scripted model), converted to the public form |
| `fixtures.json` | The content and reference documents behind each fixture, so spans and quotes can be checked |
| [`examples/api/`](examples/api/) | A request, a 200 response, and 400 / 404 / 409 / 503 error bodies |

All of these are fictional data, are validated by tests, and are kept current.

## 11. Running the contract tests

From `services/verification` (Python 3.11+; no API key needed and no external calls):

```sh
python -m pip install -e ".[dev]" -c constraints.txt
python -m pytest -q tests/test_api_contract.py tests/test_api.py tests/test_api_errors.py \
    tests/test_partial_failure.py tests/test_public_fixtures.py tests/test_contract_e2e.py \
    tests/test_examples_and_json_schema.py
python -m pytest -q                                  # everything
python eval/run_eval.py --check-baseline             # evaluation with regression gates
PYTHONPATH=src python -m inkloom_verify.json_schema  # regenerate schemas/ after a model change
INKLOOM_REGENERATE_EXAMPLES=1 python -m pytest -q tests/test_api.py tests/test_api_contract.py  # regenerate examples
```

## 12. Validating your integration

**Member 3 (backend):**
1. **Mount the router** in your app with your auth, your loader and your request id:
   ```python
   from inkloom_verify.api import create_verify_router
   from inkloom_api.logging import get_request_id
   app.include_router(create_verify_router(
       engine, authenticated_tenant=tenant_of_membership,
       reference_set_loader=load_approved_documents, request_id_provider=get_request_id))
   ```
2. **Loader semantics:** return `None` for an unknown set or one this tenant may not use, `[]`
   for a known set with no approved documents, and otherwise a list of `ReferenceDocument`
   (with the stored `text_sha256`). Raising gives 500.
3. **Check it:** `tests/test_api.py::test_router_mounted_in_the_backends_error_handling` already
   mounts the router inside your real `install_error_handlers` and `RequestIdMiddleware`
   (read-only import). Run it after any change to `errors.py` or `logging.py`.
4. **Your engine imports:** `tests/test_contract_e2e.py::test_member_3_still_finds_every_engine_name_it_imports`
   fails if an engine change removes a name your code imports (28 today).
5. **Validate your stored or forwarded reports** against `schemas/public_report.schema.json`.
6. **Suggested, on your side:**
   - register a handler for `starlette.exceptions.HTTPException`, so 404/405 use the envelope;
   - include the engine and prompt versions in your result-cache key, since behaviour changed
     inside contract 0.2.0.

**Member 1 (frontend):**
1. **You consume Member 3's API**, not this endpoint. Your contract is
   `contract/schemas/finding.schema.json` and `review.schema.json`, which a test checks the
   engine's mapping against. Nothing here changes what you call.
2. **If you render engine reports directly:** generate types from
   `schemas/public_report.schema.json`, and parse the five fixtures in `examples/public/` as test
   inputs (one per UI state).
3. **Offsets are code points.** Your `lib/text/codepoints.ts` `segment` helper is the right tool.
   Check it against content containing an emoji.
4. **Render engine strings as plain text:** claim text, quotes and corrections. Never HTML,
   Markdown or auto-linked text.
5. **`unverified` / `NOT_ENOUGH_EVIDENCE` is not "false",** and `confidence` is not a percentage
   of certainty.

## 13. Contract changes made during implementation

**Breaking (all made on 2026-10-23, under the approvals recorded in CONTRACTS.md):**

| # | Previous contract | New contract | Reason | Affected consumers | Version impact | Coordination |
|---|---|---|---|---|---|---|
| 1 | `Claim.text` could be the model's rewording of the source | `Claim.text` is exactly `content[start:end]`; the rewording is in `Claim.normalized_text` | The spec requires the offset rule | Member 3 (in-process): reads `claim.source_span.slice(...)`, so unaffected by reading; untested | Internal `0.1.0` → `0.2.0` | Tell Member 3 that new reviews store `engine_contract_version = "0.2.0"` |
| 2 | Internal `contract_version` was `"0.1.0"` | `"0.2.0"`; payloads stating `"0.1.0"` are refused | Follows from #1 | Anyone sending internal requests with an explicit version (none found) | Internal bump | Same note to Member 3 |
| 3 | `POST /v1/verify` took the internal `VerificationRequest` (`tenant_id`, inline `references`, `contract_version`) | It takes the public `VerifyRequest` (`request_id`, `content{id,text}`, `reference_set_id`, `options`). `tenant_id` and `references` are refused. | Approved Phase 2 spec. The tenant comes only from authentication; documents only from the backend. | Any `/v1/verify` caller: **none in the repository** (Member 3 doesn't mount it, Member 1 doesn't call it) | New public contract, `schema_version` 0.1.0 | Member 3 must supply `reference_set_loader` (and `authenticated_tenant`) if they mount it |
| 4 | `/v1/verify` returned the internal `VerificationReport`, including `FAILED` reports with HTTP 200 | It returns the public `Report`. A run with no results is an HTTP error (section 7). | Approved Phase 1–3 decisions | As #3 | Public 0.1.0 | As #3 |
| 5 | Errors: 422 `VALIDATION_ERROR`, 403 `FORBIDDEN` (body tenant mismatch), 404 `NOT_FOUND` | 400 `INVALID_INPUT`, 404 `REFERENCE_SET_NOT_FOUND`, 409 `REFERENCE_SET_EMPTY`, 422 `UNPARSEABLE_MODEL_OUTPUT`, 429 `RATE_LIMITED` + `retry_after`, 504 `PROVIDER_TIMEOUT`, 503 / 500 (403 no longer happens, since the body has no tenant) | Approved Phase 3 mapping and envelope | As #3; the router answers these itself inside Member 3's app | Public 0.1.0 | Member 3: pass `request_id_provider` |
| 6 | `create_verify_router(engine, authenticated_tenant=None, reference_set_access=None)` | `create_verify_router(engine, *, reference_set_loader, authenticated_tenant, ...)`. `reference_set_access` is removed; auth is required outside the dev app. | Phase 2 loader decision | Python callers of the router: none outside the engine | n/a (code API) | Member 3, if they mount |
| 7 | The fake engine's canned results were served by the dev endpoint | Fake mode answers 503 `PROVIDER_NOT_CONFIGURED` | Approved: canned results can't be labelled in a public Report | Local development without a key | n/a | None |

**Behaviour changes with the same shape:**
- One claim's unexpected exception is now that claim's `ERROR` (`INTERNAL_ERROR`) instead of
  failing the whole run (Phase 4).
- Figure conflicts between documents are downgraded to `NOT_ENOUGH_EVIDENCE`.
- Corrections that mispair units or drop them are refused.

**Additive (no consumer change required; strict enum parsers must accept the new values):**
- **Public, inside 0.1.0:** `metadata.errors`; `metadata.prompt_versions` (prompts Phase 1).
- **Internal, inside 0.2.0:**
  - `EvidencePassage.reference_set_id`;
  - `ProcessingError.retry_after_seconds`;
  - guard reasons `unsupported_name` and `conflicting_evidence`;
  - review reason `conflicting_evidence`;
  - correction issue `drops_unit`;
  - control, bidi and zero-width characters refused in `normalized_text` and `replacement_text`.

  Whether these warrant 0.3.0 is still undecided.

## 14. Open items

1. **No integration confirmed:** neither team has mounted, called or validated this endpoint.
2. **Contract versions:** freeze public 0.1.0 and internal 0.2.0 as they are, or bump them for
   the additions above.
3. **Known gaps:**
   - routing errors outside the envelope;
   - chunked bodies not size-checked;
   - the published schema marks always-present response fields as optional;
   - no envelope schema in OpenAPI.

   Fixes are proposed and await approval.
4. **No live-model run:** `confidence`, accuracy and citation validity on a real model are
   unmeasured. No API key was found in the environment.
5. **Not committed:** none of this work has been committed or pushed.
