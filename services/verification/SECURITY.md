# Engine security (Member 2)

This covers the claim-verification engine in `services/verification` only. Authentication,
tenant management, storage, the HTTP API and hosting belong to other members. Where the engine
depends on them, that dependency is listed as a requirement below, not assumed to be met.

Tests: [`tests/test_security.py`](tests/test_security.py), plus the guard, extraction,
verification, correction and adapter suites. Last run on 2026-10-22: 509 passed.

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

**Assumed, not proven by engine tests:**

| Assumption | Why it isn't tested here | Who can close it |
|---|---|---|
| The request's `references` are exactly the documents this tenant may use, and `tenant_id` is the caller's real tenant | The engine has no access to accounts or brands; it treats `references` as the authorised evidence set | Member 3 (Phase 2 and 4 tests) |
| Tenant isolation end to end: API, database, cache, queues | Only the engine's in-process boundary exists to test. **Tenant isolation is not proven by these tests.** | Member 3 |
| A real model treats the data block as data | All tests use scripted models; no live model has been run | Live evaluation with a key (EVAL.md) |
| OpenRouter honours `data_collection: deny` and keeps traffic confidential | Third-party behaviour | Team / provider terms |
| TLS verification and proxy settings | httpx defaults are used: TLS verified, and `HTTP(S)_PROXY` from the environment is honoured. Not tested. | Deployment owner |
| Thread safety when one provider object is shared across threads | Not exercised; the secret registry is lock-protected and httpx clients are documented as thread-safe | Phase 8 pipeline |
| Cost and denial-of-service bounds | Limits exist but haven't been load-tested. Worst case per request: about 2×⌈sentences/40⌉ extraction calls, 2 per claim for verification (with repair), and 4 per contradicted claim for correction and re-check, with at most 200 claims. | Member 3 rate limits; benchmarking |
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

- Runtime dependencies: `pydantic>=2.10,<3`, `rank_bm25>=0.2.2,<0.3`, `httpx>=0.27,<1` (plus
  their transitive dependencies, such as numpy). Version ranges only, with no lock file. A lock
  file or hashes are recommended before deployment.
- `pip-audit` (added to the dev extras) on 2026-10-22:
  - the project's dependencies: **no known vulnerabilities**;
  - the venv's own `pip` 26.1.2 had PYSEC-2026-3721; it was upgraded, and a re-run reports none.

  Re-run `python -m pip_audit` before each release.

## File, network and process operations within Member 2's scope

| Where | What | Why it's acceptable |
|---|---|---|
| `providers/openrouter.py` | HTTPS POST to the configured base URL | The only network call; no redirects, 2 MB cap, timeout |
| `evaluation/runner.py` | `git rev-parse` / `git status` with fixed arguments, a 5 s timeout and no shell | Records the commit in evaluation reports; developer tool only |
| `evaluation/*`, `json_schema.py` | Read datasets and write reports and schemas at paths given on the command line | Developer CLIs; never fed model output |

## Remaining risks

- **Prompt injection isn't solved, only contained.** A model can still be talked into a wrong
  verdict. The guard then requires every quote to exist verbatim in this request's evidence,
  and the evaluation measures verdict accuracy. But a valid quote of injected text with a
  wrong verdict passes the guard (dataset record `v1-032`, PROMPTS.md).
- **Strings written by the model are displayed.** They're cleaned and length-capped, but their
  content is attacker-influenced. That's why plain-text rendering is required of Member 1.
- No fuzzing, load test or live-model red-teaming has been done yet.
