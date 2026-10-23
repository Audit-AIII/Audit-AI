# Engine security (Member 2)

This covers the claim-verification engine in `services/verification` only. Authentication,
tenant management, storage, the HTTP API and hosting belong to other members. Where the engine
depends on them, that dependency is listed as a requirement below, not assumed to be met.

Tests: [`tests/test_security.py`](tests/test_security.py), plus the guard, extraction,
verification, correction, budget, API and adapter suites. Last run on 2026-10-23 (Phase 7,
second run): 890 passed, Python 3.14.6, Windows.

## What the engine guarantees, and what it assumes

**Guaranteed by engine code and covered by tests:**

1. **Content and evidence are data, not instructions.** Submitted text and reference passages
   only reach a model inside a JSON data block in the user message:
   - quotes, control characters, `<` and `>` are escaped, so no text can close the block or
     imitate its tags;
   - the system prompts are constants;
   - this is tested with nine injection payloads across all three LLM stages, each checked to
     round-trip exactly as data.
2. **Model output can't cause actions.** Every reply is parsed as JSON and validated against a
   closed Pydantic model (`extra="forbid"`, with size caps on every string and list). Then
   deterministic code decides what is kept. Nothing a model returns is used as a URL, path,
   command, module or tool name. A static test checks that the engine modules don't import
   `subprocess`, `socket`, `pickle`, `requests`, `shutil` or similar, and don't call `eval`,
   `exec`, `compile`, `open` or `os.system`. Network access is limited to the OpenRouter adapter,
   which only posts to its configured `https://` base URL and never follows redirects. A
   dynamic test runs extraction, verification and correction with a hostile model while file,
   socket and process access are blocked. `os` may be imported only by the two configuration
   entry points (`providers/openrouter.py` and `api.py`), and only `os.environ` may be used.
3. **Evidence and citations belong to the current request.**
   - The verifier refuses passages that aren't exact slices of this request's documents. It
     returns `ERROR` and never calls the model.
   - The citation guard only accepts quotations from passages retrieved for that claim (PROMPTS.md).
   - `scope.check_report_scope(request, report)` re-checks a whole report: ids, content hash, the
     reference set, every passage (exact slice and an id derived from provenance), every
     citation and every correction. It reports violations as ids, never as text.
4. **No state crosses requests.** Retrievers, verifiers, guards and correctors are built per
   request. There are no module-level caches or result stores. A test interleaves two tenants'
   requests over one shared provider and gets exactly the results of running each alone.
5. **Credentials stay out of code, logs and errors.**
   - The key comes only from the `OPENROUTER_API_KEY` environment variable and is held as a
     `SecretStr`.
   - Every configured key is registered for redaction. Redaction is installed on the adapter's
     logger, and `security.install_redaction` attaches it to any handler.
   - Errors from the provider carry a fixed message: the provider's own error text is dropped,
     because moderation errors can echo submitted content.
   - A test runs the full flow with a provider error that echoes content and the key, and
     checks that neither appears in the logs or in the error.
6. **No content in logs.** Engine logs carry claim ids, verdicts, codes, counts, model ids and
   HTTP statuses, never content, evidence, prompts or replies. This is tested at DEBUG level.
7. **Text the model writes is cleaned before storage.** Rationales and decline reasons have
   control characters, bidi overrides and zero-width characters removed, and are truncated.
8. **Inputs are validated.** Request limits, id patterns and text hashes are enforced by the
   contracts (CONTRACTS.md). Pathological replies are malformed output, not crashes:
   - JSON nested deeply enough to raise `RecursionError` (found and fixed in this phase);
   - responses over 2 MB;
   - more than 400 statements, or over-long quotes, ids or rationales.
9. **The HTTP endpoint (`POST /v1/verify`, Phase 2) has no authentication of its own.**
   - It must be mounted inside Member 3's app with `authenticated_tenant`, which refuses a body
     `tenant_id` that isn't the token's organisation (403).
   - The development app is unauthenticated and must never be exposed. It serves canned results
     only when `INKLOOM_ENGINE_MODE=fake` is set.
   - Bodies over the size limit are refused before parsing.
   - Every report is scope-checked against its request before it is returned, whatever engine
     produced it.

10. **Each request has a bounded model-call budget** (Phase 7, `providers/budget.py`). By
    default a request is limited to 200 calls, 1,000,000 estimated tokens and a 300 s deadline,
    all configurable through `PipelineConfig.budget`. Provider-side retries count as calls.
    - A refused call is `LIMIT_EXCEEDED`, which isn't retryable.
    - At extraction it fails the report and stops further batches. At verification the claim
      becomes `ERROR`. At correction the attempt is `FAILED` and the verdict is kept.
    - Tests sweep every call limit from 1 to 8 and show that a budget stop never creates or
      changes a verdict.
11. **Reference sets are loaded by the backend, for the authenticated tenant only** (public
    contract, Phase 2; this replaces the Phase 7 `reference_set_access` hook).
    `create_verify_router(..., reference_set_loader=...)` asks the backend's loader for the
    documents of `(authenticated tenant, reference_set_id)`.
    - The request body carries no tenant and no documents, and both fields are refused if sent.
    - No documents is 404 (no probing for other tenants' ids); an exception, or documents that
      break the contract, is 500. In each case the engine is never called.
    - The router refuses to start without `authenticated_tenant`, except in the development app.
    - Ownership is decided by Member 3's loader, not by the engine.
12. **No failure becomes `SUPPORTED`.** A test sweeps every `ProviderError` type, unexpected
    exceptions (`RuntimeError`, `ValueError`, `KeyError`) and malformed or verdict-shaped replies
    at extraction and verification, using a model that would otherwise answer `SUPPORTED`. None
    of them yields `SUPPORTED`, a `COMPLETED` report, or a report without an error and a review
    flag.

**Assumed, not proven by engine tests:**

| Assumption | Why it isn't tested here | Who can close it |
|---|---|---|
| The request's `references` are exactly the documents this tenant may use, and `tenant_id` is the caller's real tenant | The engine has no access to accounts or brands; it treats `references` as the authorised evidence set | Member 3 (Phase 2 and 4 tests) |
| Tenant isolation end to end: API, database, cache, queues | Only the engine's in-process boundary exists to test. **Tenant isolation is not proven by these tests.** | Member 3 |
| A real model treats the data block as data | All tests use scripted models; no live model has been run | Live evaluation with a key (EVAL.md) |
| OpenRouter honours `data_collection: deny` and keeps traffic confidential | Third-party behaviour | Team / provider terms |
| TLS verification and proxy settings | httpx defaults are used: TLS verified, and `HTTP(S)_PROXY` from the environment is honoured. Not tested. | Deployment owner |
| Thread safety when one provider object is shared across threads | Not exercised; the secret registry is lock-protected and httpx clients are documented as thread-safe | Phase 8 pipeline |
| Cost and denial-of-service bounds | The per-request budget (guarantee 10) caps calls and estimated tokens, and is tested with scripted providers. It hasn't been load-tested. Tokens are *estimated* (characters/4 plus the output allowance), not billed counts. The deadline is checked between calls, so one call already running can overrun it by up to models × (max_retries+1) × 30 s plus backoff. Nothing limits requests per tenant. | Member 3 rate limits; benchmarking with a key |
| Unicode look-alike tags (`＜/content_json＞`) don't confuse a model | They pass through as data; how a model reads them is untested | Live evaluation |

## Integration requirements

**Member 3 (backend, auth, tenancy):**

1. **Build `references` only from approved sources** of the authenticated organisation and
   brand. Derive `tenant_id` from the authenticated membership, never from a request body. The
   engine can't check either.
2. **Before saving, run `check_report_scope(request, report)`** (or your Phase 4 validator, which
   overlaps it). On `ScopeViolation`, mark the review `failed`. Never save a partial result.
3. **Never log or return `str(ValidationError)`.** Pydantic embeds the offending input, which can
   be document text (there's a test showing this). Use `extraction.describe_validation_error`
   or field names only.
4. **Attach `security.install_redaction` to your log handlers**, or apply equivalent redaction,
   so third-party loggers are covered too.
5. **Confidential sources must not reach a cloud model.** The engine doesn't receive source
   sensitivity, so either route confidential reviews away from the LLM stages before calling
   the engine, or agree a `sensitivity` field on `ReferenceDocument` (a contract change).
6. **Provider ownership.** If your adapter replaces the engine's OpenRouter adapter, it should
   implement `LLMProvider` and keep the same properties: no redirects, a response size cap,
   fixed error messages without provider text, no content in logs, and keys only from the
   environment.
7. **Rate-limit and cache per organisation** (your Phase 5). The engine has no notion of
   callers or quotas.
8. **Map `ProcessingError` to your safe error format.** Engine messages are safe to show; don't
   add stack traces.

**Member 1 (frontend):**

1. **Render every engine string as plain text.** Never render it as HTML or Markdown, and never
   auto-link it. Claim text, quotes, rationales, warnings and issue details can all contain
   attacker-chosen text, including URLs, because content and evidence are untrusted and
   rationales are written by a model.
2. Label `model_rationale` as model-written. It is never evidence.
3. Never hold provider credentials client-side. The engine only reads them from the server
   environment.

## Credentials and configuration

- The only credential is `OPENROUTER_API_KEY`, read from the environment.
  [`.env.example`](.env.example) lists variable names with empty values, and a test enforces that.
  `.env` files are git-ignored; `.env.example` is explicitly kept.
- The base URL must be `https://`. Models are configuration, not code.
- **Git history:** the scan found no real credentials. A dummy test key
  (`sk-or-v1-0123…`) was committed in Phase 4; it was never a real key. Its replacement is
  obviously fake (`sk-or-v1-TEST-ONLY-NOT-A-REAL-KEY-…`). History wasn't rewritten because the
  branch is shared, so a credential scanner may still flag the old commit.
- A test checks that source, examples and `.env.example` contain no credential-shaped strings.

## Dependencies

- `pyproject.toml` keeps compatible ranges (`pydantic>=2.10,<3`, `rank_bm25>=0.2.2,<0.3`,
  `httpx>=0.27,<1`, extras `api` and `dev`), so Member 3's backend can resolve against them.
- **`constraints.txt` (Phase 7)** pins every package to the exact version that was tested and
  audited, from a `pip freeze` on Python 3.14.6. CI installs with `-c constraints.txt`.
  - numpy 2.5.4 needs Python ≥ 3.12, so it is pinned only there; on 3.11 pip chooses numpy
    itself.
  - A `pip install --dry-run` for Linux resolved on 3.12 (numpy 2.5.4) and on 3.11 (numpy
    2.4.6). The 3.11 simulation applied the marker by hand, because pip evaluates markers
    against the running interpreter.
  - Neither version has been run locally, and numpy 2.4.6 hasn't been audited locally either
    (CI audits each lane).
  - No hashes (`--require-hashes`) yet.
- `pip-audit` 2.10.1 on 2026-10-23 (Phase 7), over the tested environment: **"No known
  vulnerabilities found"**, exit 0. Earlier, on 2026-10-22, the venv's own `pip` 26.1.2 had
  PYSEC-2026-3721; it was upgraded.

  Re-run `python -m pip_audit` before each release.

## Phase 7 checklist (evaluated 2026-10-23)

Status key:
- **DONE**: implemented and covered by a test that was run.
- **PARTIAL**: implemented here, but part of it depends on someone else or is untested.
- **NOT DONE**: not implemented, or not verifiable here.

Test names are in `tests/`.

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Prompt-injection tests, content and reference documents | DONE (scripted models) | `test_security::test_payloads_are_encoded_as_data_in_every_stage`, `test_pipeline::test_injected_content_cannot_produce_approved_claims`, `::test_injected_reference_document_is_evidence_text_not_instructions`, `test_verification::test_injected_passage_cannot_close_the_data_block_or_reach_the_system_prompt`, `test_retrieval::test_injected_*`, dataset injection records. **No live model has been tested.** |
| 2 | Retrieved evidence is untrusted | DONE | Evidence goes only into escaped data blocks (guarantee 1); verbatim and provenance checks (guarantee 3); `test_security::test_system_prompts_never_contain_request_text` |
| 3 | Document instructions can't override the rules | DONE in code; PARTIAL for model behaviour | The rules are enforced after the model, by the guard and scope checks, so an obeyed injection can only produce downgraded or valid-quote answers. `test_verification::test_compromised_model_fabricating_evidence_is_downgraded`. A valid quote of injected text with a wrong verdict still passes (Remaining risks). |
| 4 | Model output triggers no tools, files, shell or URLs | DONE | `test_security::test_hostile_output_triggers_no_file_network_or_process_access`, `::test_engine_code_has_no_dangerous_capabilities`, `::test_redirects_are_not_followed_so_the_key_stays_put` |
| 5 | Provider timeouts | DONE | 30 s per call (`INKLOOM_LLM_TIMEOUT_SECONDS`, ≤ 300); `test_openrouter::test_error_mapping`, `::test_network_failure`; plus the request deadline (guarantee 10) |
| 6 | Bounded retries, only for retryable errors | DONE | 2 retries by default (≤ 5) with exponential backoff and a 20 s `Retry-After` cap. 400/404/413/422 move to the next model; 401/402/403 stop. `test_openrouter::test_transient_errors_are_retried_with_backoff`, `::test_request_rejection_moves_to_the_next_model_without_retrying`, `::test_account_errors_stop_immediately`, `::test_rate_limit_honours_retry_after_with_a_cap` |
| 7 | Bounded request and document sizes | DONE | Content 100,000 characters, references 5,000,000 in total, 200 claims, body limit before parsing, a 2 MB response cap. `test_api::test_oversized_bodies_are_refused_before_parsing`, `test_inputs::test_reference_count_limit`, `::test_total_reference_size_limit`, `test_extraction::test_oversized_input_is_rejected_without_a_call`, `test_security::test_oversize_*` |
| 8 | Cost or token limits | DONE (estimated tokens) | Guarantee 10; `test_budget.py` (21 tests). Tokens are estimated, not billed counts. |
| 9 | Reference-set and tenant isolation at the real boundary | PARTIAL | Engine boundary: body tenant vs authenticated tenant (403), the reference-set hook (404), and report scope checks. Tests: `test_api::test_tenant_mismatch_is_forbidden`, `::test_another_tenants_reference_set_is_not_found_and_never_reaches_the_engine`, `test_retrieval::test_the_same_reference_set_id_in_two_tenants_never_shares_evidence`, `test_security::test_results_from_another_tenant_are_rejected_even_with_the_same_doc_id`. **The real boundary is Member 3's auth and database. They haven't mounted the router or supplied the hook, so end-to-end tenant isolation is not proven.** |
| 10 | Coordinate with the auth owner, don't replace them | DONE | The router takes Member 3's dependency and hook; the engine has no auth code. Usage is documented in INTEGRATION.md. Member 3's files are untouched. |
| 11 | Keys and sensitive data redacted from logs | DONE | `test_openrouter::test_key_never_appears_in_errors_or_logs`, `::test_content_is_not_logged`, `test_security::test_full_run_logs_no_content_evidence_or_credentials`, `::test_redaction_reaches_application_handlers`, `::test_no_credentials_in_source_or_examples`. The budget's usage log carries only counts. |
| 12 | Dependencies pinned | DONE (no hashes) | `constraints.txt`; CI installs with it |
| 13 | Vulnerability scan run | DONE | pip-audit 2.10.1: no known vulnerabilities (above) |
| 14 | Malformed requests, fabricated citations, cross-request contamination, unauthorised reference sets | DONE | Malformed: `test_api::test_invalid_request_fixtures_get_a_safe_422`, `::test_malformed_bodies_get_a_safe_422`. Fabricated: `test_verification_eval::test_no_fabricated_quotation_survives_on_the_evaluation_set`, the evaluation's fabricator gate (0 accepted). Cross-request: `test_security::test_interleaved_requests_do_not_share_state`, `::test_citations_cannot_name_another_requests_passages`, `test_pipeline::test_foreign_evidence_inside_the_pipeline_fails_the_report`. Unauthorised set: the `test_api::test_reference_set_*` tests. |
| 15 | Failures never silently become SUPPORTED | DONE | `test_security::test_no_failure_at_any_stage_becomes_a_supported_verdict` (32 cases), `::test_an_uncited_supported_answer_is_downgraded_not_accepted`, `test_budget::test_no_call_limit_ever_creates_or_changes_a_verdict`, 18/18 evaluation fault cases |
| 16 | Assumptions and unresolved dependencies documented | DONE | This file: the assumptions table, the integration requirements and the list below |

## Phase 7, second run (2026-10-23): what changed since the checklist above

**New attack surface from Phases 1–6, found and fixed.** Contract 0.2.0 added two fields written
by a model and shown to reviewers: `Claim.normalized_text` (the extractor) and
`Correction.replacement_text` (the corrector). Their word-level checks ignore characters that
aren't words, so a probe got through:
- a **bidi override** (U+202E), which can reverse what a reviewer reads ("Trojan Source");
- a line break followed by a **Markdown heading**;
- for corrections, `Lisbon` + U+202E.

Now:
1. `security.has_hidden_characters` flags control characters (line breaks included), bidi
   overrides and isolates, and zero-width characters.
2. The extractor rejects such a rewording (`rewrite_rejected`) and keeps the claim's exact source
   text.
3. The corrector refuses such a replacement (`unsupported_addition`).
4. The contract refuses them in `normalized_text` and `replacement_text`, as a second layer.
   Content-derived fields (`text`, `original_text`) are untouched, because authors' line breaks
   are theirs.

Tests: `test_security.py`, 7 hidden characters × extractor and corrector, plus the contract.

**Conflict check versus injected documents.** Phase 4 made the guard read every retrieved
passage, hostile ones included. `test_an_injected_document_can_force_review_but_never_approval`
shows the effect is one-way: a planted document with a different figure downgrades an answer to
NOT_ENOUGH_EVIDENCE (a person decides), and it can't make a false figure SUPPORTED while an
approved source disagrees. It can still win when **no** approved source mentions the figure
(`v1-032`, unchanged).

**CI.** The Python 3.11 lane's dependency audit failed on `3595e96`; 3.12 passed. The job log
needs repository access, so the cause is **not confirmed**. The likely cause is checked: Python
3.11's venv ships setuptools 65.5.0, and pip-audit reports four advisories for it
(PYSEC-2022-43012, PYSEC-2025-49, PYSEC-2026-1918, PYSEC-2026-3447). The 3.12 lane has no
setuptools, and numpy 2.4.6 (3.11 only) audits clean. The workflow now upgrades pip and
setuptools before auditing. Python 3.11 isn't installed locally, so the fix is unrun until CI
runs.

**Dependencies.** pip-audit 2.10.1 over the tested environment: "No known vulnerabilities
found", exit 0. `constraints.txt` still matches it exactly.

**Backend review (read-only).** Member 3's commits add Gemini, Groq, Ollama, fallback and retry
providers on the engine's `LLMProvider`, and their own engine pipeline. Checked against
integration requirement 6:

| Item | Finding |
|---|---|
| Confidential sources (requirement 5) | **Handled by Member 3**: any confidential source in scope routes the review to local Ollama only (`review_runner.py`, `engine/pipeline.py`) |
| Independent evidence check | **Handled by Member 3**: `engine/evidence_validator.py` re-checks every citation against their own source copies |
| Provider text in errors | **Gemini embeds the provider's message** in client and server errors (`gemini.py` `_map_client_error`, `ServerError`). Moderation errors can echo submitted content into stored errors. The engine's adapter uses fixed messages for this reason. |
| Exception text in errors | Gemini, Groq and Ollama put `str(httpx error)` into timeout and connect messages; this can include the request URL |
| Key redaction | No backend provider calls `security.register_secret`, and nothing attaches `install_redaction` |
| Response size and nesting | Groq and Ollama call `response.json()` with no size cap and no `RecursionError` handling (the engine adapter has both, after a deeply nested reply crashed it) |
| Engine safeguards in their pipeline | Their pipeline calls the stages directly, so it doesn't get `check_report_scope`, the call budget, corrections, or `reference_set_id` on passages. `verify_request` provides all four. |

These are Member 3's files, and I haven't edited them. The request list is in INTEGRATION.md.

**Unresolved (Phase 7, second run):**

1. **Tenant isolation end to end is not proven.** The engine boundary is tested. Member 3's
   auth, database scoping and their own tenant tests exist, but I haven't run them here (no
   backend environment; they need Postgres), and their pipeline doesn't use the engine's scope
   check.
2. **The backend provider findings above are open** until Member 3 acts on them.
3. **No live model** has been red-teamed or evaluated (`OPENROUTER_API_KEY` is not set).
4. **CI's 3.11 fix is unrun**, and nothing is committed.
5. No per-tenant rate limits, load test or fuzzing; the token limit is an estimate.
6. **Contract version.** Phases 4, 5 and 7 tightened or extended enums and validation
   (`unsupported_name`, `conflicting_evidence`, `drops_unit`, hidden-character checks) inside
   0.2.0. Whether to call this 0.3.0 is undecided.

## File, network and process operations within Member 2's scope

| Where | What | Why it's acceptable |
|---|---|---|
| `providers/openrouter.py` | HTTPS POST to the configured base URL | The only network call; no redirects, 2 MB cap, timeout |
| `evaluation/runner.py` | `git rev-parse` / `git status` with fixed arguments, a 5 s timeout and no shell | Records the commit in evaluation reports; developer tool only |
| `evaluation/*`, `json_schema.py` | Read datasets and write reports and schemas at paths given on the command line | Developer CLIs; never fed model output |

## Remaining risks

- **Prompt injection isn't solved, only contained.** A model can still be talked into a wrong
  verdict. The guard then requires every quote to exist verbatim in this request's evidence,
  and the evaluation measures verdict accuracy. Since prompts Phase 6:
  - a quote from a passage sentence that gives instructions is refused (`instruction_text`);
  - a claim that gives instructions is never SUPPORTED.

  A valid quote of a planted false *fact*, or of an instruction worded so the narrow detector
  misses it, still passes the guard (dataset record `v1-032`; PROMPTS.md "Prompt security").
- **Strings written by the model are displayed.** They're cleaned and length-capped, but their
  content is attacker-influenced. That's why plain-text rendering is required of Member 1.
- No fuzzing, load test or live-model red-teaming has been done yet.
