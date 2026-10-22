# Verification engine contracts (v0.1.0, draft)

Contracts between the INKLOOM claim-verification engine (Member 2) and its callers. They are
defined once, in [`src/inkloom_verify/schemas.py`](src/inkloom_verify/schemas.py), and exported as
JSON Schema to [`schemas/`](schemas/) for callers who don't use Python.

**Status: draft.** None of these decisions has been agreed with Members 1 and 3 yet. Each
decision that affects them is listed under [Open integration questions](#open-integration-questions).
Until they sign off, any field may still change.

The engine's input is text that has already been extracted. Uploads, file storage, PDF/DOCX
parsing, authentication and tenant management belong to other members and are not part of
these contracts.

---

## Conventions

| Topic | Rule |
|---|---|
| Offsets | Half-open `[start, end)` indexes into the text, counted in **Unicode code points** (Python `str` indexes). They are **not** UTF-8 byte offsets and **not** UTF-16 code units (JavaScript `string.length`). The two units differ for emoji and other characters outside the Basic Multilingual Plane. |
| Text | Never trimmed or normalised. Offsets only make sense against the exact text they were computed from. |
| Text hashes | `text_sha256` is the lowercase hex SHA-256 of the text encoded as UTF-8. On input it is optional: if omitted, the engine computes it; if supplied, it must match; `null` is rejected. Every passage and citation carries the hash of the document it quotes (`doc_text_sha256`), which pins it to one exact version of that document. |
| Unknown fields | Rejected (`extra="forbid"`). |
| Immutability | Models are frozen once validated. |
| Versioning | `contract_version` is `"0.1.0"`. If omitted, it defaults to that value. Any other value is rejected. |

## Identifiers

| ID | Issued by | Format |
|---|---|---|
| `tenant_id`, `doc_id`, `content_id`, `request_id`, `record_id` | Caller (other members) | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`, treated as opaque by the engine. UUIDs fit this pattern. Slashes, spaces and non-ASCII characters are rejected. |
| `claim_id` | Engine | `clm_` + 1–64 characters from `[A-Za-z0-9_-]` |
| `passage_id` | Engine | `psg_` + 1–64 characters from `[A-Za-z0-9_-]` |

The prefixes stop a claim id from being accepted where a passage id is expected, and the reverse.
Claim ids are **unique only within one report**; they are not global ids.

The retriever builds each passage id from the first 24 hex characters of
`SHA-256(doc_id, doc_text_sha256, start, end)`. The same passage of the same document version
therefore gets the same id in every run, whatever order the documents arrive in. Callers should
still treat passage ids as opaque. The ids in `examples/` follow this form, and the scope check
rejects a passage id that doesn't.

## Models

| Model | Purpose |
|---|---|
| `VerificationRequest` | Caller → engine. One piece of content plus 1–50 reference documents, and an optional `reference_set_id`. |
| `InputContent` | The text under review. |
| `ReferenceDocument` | One approved source of truth: `doc_id`, optional `version` and `title`, `text`, `text_sha256`. |
| `ReferenceDescriptor` | A reference document without its text (`doc_id`, `version`, `text_sha256`). Used for provenance in reports. |
| `SourceSpan` | `{start, end}` offsets. |
| `Claim` | One atomic, checkable statement: `claim_id`, `text` (possibly reworded so it stands alone), `source_span` in the content. |
| `EvidencePassage` | A verbatim excerpt of one reference document, with the document's `doc_id`, `doc_text_sha256`, `span` and `retrieval` provenance (method, score, rank). |
| `ClaimVerificationInput` | **Everything the verifier may see:** one claim and 1–8 passages. It has no field for the reference documents, and adding one is rejected. |
| `Verdict` | `SUPPORTED`, `CONTRADICTED`, `NOT_ENOUGH_EVIDENCE`, `ERROR`. |
| `Citation` | `doc_id`, `doc_text_sha256`, `passage_id`, `quote`, `quote_span` (in **document** coordinates). |
| `Correction` | `target_span` in the content, `original_text`, `replacement_text`, and 1 or more `citations`. |
| `ProcessingError` | `code`, `stage`, client-safe `message`, `retryable`, optional `claim_id`. |
| `ClaimResult` | One claim with its `verdict`, `evidence`, `citations`, optional `correction`, optional `error`, optional `model_rationale`, `evidence_strength` and `requires_human_review`. |
| `VerificationReport` | Engine → caller. `status`, `results`, request-level `errors`, `references` (descriptors), the request's `reference_set_id`, `provenance`, `score`. |
| `EngineProvenance` | `engine_version`, `contract_version`, `retrieval_method`, `provider` (added in Phase 8), `model_id` (every model that answered, comma-separated), `prompt_versions`. |
| `EvalRecord`, `GoldEvidence` | One labelled line of the evaluation JSONL. Gold evidence is located by `doc_id` + `span`, not by `passage_id`, so labels survive changes to how documents are split into passages. |

## Validation rules

### Requests

- `reference_set_id` (optional; added in the contract-reconciliation Phase 1) names the set of
  reference documents the backend chose for this request. It's opaque: the engine never looks it
  up, and the backend still sends the documents themselves in `references`. It uses the same
  pattern as other caller-issued ids (UUIDs fit). The report echoes it unchanged, and the scope
  check rejects a report whose `reference_set_id` differs from its request's.

- `content.text` must be 1–100,000 characters and must not be whitespace-only.
- There must be at least 1 and at most 50 references.
- Each reference's text must be 1–1,000,000 characters and not whitespace-only.
- The references together must not exceed 5,000,000 characters.
- `doc_id` must be unique within a request.
- `request_id`, `tenant_id`, `content` and `references` are required.
- A request with **no references is rejected**: verifying content against nothing is a caller error. See question 4.

### Claims and evidence

- A passage's `text` must be exactly `span.length` characters. `EvidencePassage.matches(document)` checks it against the original document's text and hash.
- A citation's `quote` must be exactly `quote_span.length` characters. `Citation.matches(document)` checks it against the original document's text and hash.
- `ClaimVerificationInput` requires 1–8 passages with no duplicate `passage_id`s.
- A claim with zero retrieved passages never reaches the verifier. The engine records `NOT_ENOUGH_EVIDENCE` for it directly.

### Verdicts (`ClaimResult`)

| Verdict | Citations | Correction | Error |
|---|---|---|---|
| `SUPPORTED` | at least 1, required | not allowed | not allowed |
| `CONTRADICTED` | at least 1, required | optional | not allowed |
| `NOT_ENOUGH_EVIDENCE` | not allowed | not allowed | not allowed |
| `ERROR` | not allowed | not allowed | required |

Additional rules:

- **`evidence_strength`** (Phase 5) is `strong`, `moderate`, `weak` or `none`: an ordinal label
  from fixed rules, **not a probability and not calibrated** (see [Score](#score-verificationreportscore)).
- **`requires_human_review`** is `true` for every verdict except `SUPPORTED`, **and for `SUPPORTED`
  when `evidence_strength` is `weak`** (the approved Phase 5 policy). Missing evidence,
  contradictions, failures and thin support therefore always go to a person.
- **Neither field can be inflated.** Both are filled in from the other fields when omitted, and
  a supplied value that disagrees with the rules is rejected. `requires_human_review` maps
  directly to Member 3's per-finding flag. The report-level `score.requires_human_review` stays
  separate, and also covers request-level errors, citation downgrades and corrections that need
  review.
- Every citation must point to a passage listed in `evidence`, from the same document and the same document hash.
- The citation's `quote_span` must fall inside that passage's span, and `quote` must be **exactly** the passage text at that position. Paraphrases are rejected, and so are duplicate citations.
- `evidence` may be non-empty for `NOT_ENOUGH_EVIDENCE`. It shows the passages that were considered but did not settle the claim.
- `error.claim_id`, when set, must equal the claim's id.
- **`model_rationale` is not evidence.** It is model-written text, shown for display only and limited to 2,000 characters. No rule accepts it in place of a citation; a `SUPPORTED` verdict with a rationale and no citation is rejected.
- **`citation_guard`** (optional; set by the verifier, added in Phase 5) records what the model answered (`model_verdict`), whether the citation guard downgraded it (`downgraded`), and every rejected citation (`rejected`, each with a `reason` and, when known, the `passage_id`). The contract enforces the policy:
  - a downgraded result must be `NOT_ENOUGH_EVIDENCE`, and its `model_verdict` must have been `SUPPORTED` or `CONTRADICTED`;
  - a downgrade must list at least one rejection;
  - any rejection means a downgrade, so **a result whose citations failed the guard cannot be `SUPPORTED` or `CONTRADICTED`**;
  - without a downgrade, `model_verdict` equals `verdict`;
  - an `ERROR` result has no `citation_guard`.

  Rejection reasons are `no_citation`, `unknown_passage`, `passage_provenance_invalid`,
  `quote_not_found`, `quote_too_short` and `partial_quote_drops_negation`. Since Phase 4 there
  are also three support checks for SUPPORTED answers, which carry no `passage_id`:
  `unsupported_quantity`, `unsupported_date` and `missing_qualifier`. See
  [PROMPTS.md](PROMPTS.md#citation-guard).

### Corrections

- `original_text` must be exactly `target_span.length` characters.
- `target_span` must fall inside the claim's `source_span`. This keeps the edit minimal.
- `replacement_text` must be non-blank and different from `original_text`.
- Every citation on a correction must also be a citation of the same result.
- **Any number the replacement introduces must appear in a cited quote.** Numbers already in the original don't need new support, and thousands separators are ignored (`1,200` counts as `1200`).

  This is the only fact check enforced by the contract itself. Checking names, units and meaning, and re-verifying the corrected text, is the correction stage's job (Phase 6).
- **`correction_attempt`** (added in Phase 6) records every attempt:
  - `status` is `proposed`, `needs_human_review` (with `issues`, each a `code` and an optional `detail`) or `failed` (with an `error`);
  - `recheck_verdict` is the verdict of the corrected claim, when it was re-checked.
- Contract rules for corrections:
  - attempts exist only on `CONTRADICTED` results;
  - a `correction` requires an attempt with status `proposed`, and a `proposed` attempt requires the `correction`;
  - a `proposed` attempt has no issues and no error, and if it was re-checked the re-check was `SUPPORTED`.
- Issue codes: `model_declined`, `no_citation`, `unknown_citation`, `target_not_found`, `no_change`, `unsupported_addition`, `drops_qualifier`, `not_minimal`, `recheck_not_supported`, `recheck_unavailable`, `invalid_correction`. See [PROMPTS.md](PROMPTS.md#prompt-correct-claim-v1).

### Reports

| `status` | Meaning | Rule |
|---|---|---|
| `COMPLETED` | Every claim has a non-`ERROR` verdict. | No `ERROR` verdicts and no request-level errors. Zero claims is allowed (content with nothing to check). |
| `PARTIAL` | Some results are usable. | At least 1 result, and at least one `ERROR` verdict or request-level error. |
| `FAILED` | Nothing is usable. | No results, and at least 1 request-level error. |

Additional rules:

- `claim_id` must be unique within a report.
- Every claim's `source_span` must fit within `content_length`.
- Every passage must come from a document listed in `references`, with the same `doc_id` **and** the same `text_sha256`.

### Errors

`ProcessingError.message` is shown to clients. It must never contain secrets, prompts, raw provider responses or document text. It is limited to 500 characters, and `retryable` must be a JSON boolean.

| Code | Typical stage | Retryable |
|---|---|---|
| `INVALID_REQUEST` | request | no |
| `LIMIT_EXCEEDED` | request / any LLM stage | no. Also the per-request model-call budget (calls, estimated tokens, deadline; Phase 7, `providers/budget.py`). A claim stopped by the budget is `ERROR`, never a verdict. |
| `PROVIDER_NOT_CONFIGURED` | any LLM stage | no. Credentials or models aren't set, so AI checks are unavailable (added in Phase 4). |
| `PROVIDER_TIMEOUT` | extraction / verification / correction | yes |
| `PROVIDER_RATE_LIMITED` | any LLM stage | yes |
| `PROVIDER_QUOTA_EXCEEDED` | any LLM stage | no |
| `PROVIDER_ERROR` | any LLM stage | depends |
| `MALFORMED_MODEL_OUTPUT` | any LLM stage | yes |
| `INTERNAL_ERROR` | any | no |

Stages: `request`, `extraction`, `retrieval`, `verification`, `citation_validation`, `correction`, `scoring`.

### Evaluation records

- `ERROR` is never a valid label.
- A `SUPPORTED` or `CONTRADICTED` label requires gold evidence. A `NOT_ENOUGH_EVIDENCE` label must not have any.
- Gold evidence must name a reference document in the record, and its span must fit inside that document.
- Each gold evidence `quote` must be exactly the document text at its span.
- `label_rationale` is required. `categories` must use known `EvalCategory` values, with no
  duplicates. `split` is `dev` (the default) or `heldout`. `reviewed_by` stays empty until a
  person has checked the label.

These evaluation fields were added in Phase 3. They are used only by the evaluation harness and
don't change any request or report that other members exchange with the engine. See
[EVAL.md](EVAL.md).

## Score (`VerificationReport.score`)

The engine-side score is `ReportScore`, computed from the results by `ReportScore.compute`.
The report rejects a score that doesn't match its results. It is **not** a confidence, quality
or truth probability. It answers three questions, each with its own numbers:

| Question | Fields |
|---|---|
| What did verification find? | `claims`, `supported`, `contradicted`, `not_enough_evidence`, `errors` |
| How much of the checked content is backed by evidence? | `evidence_coverage`: `supported`, `checked`, `value` |
| Does a person need to look, and why? | `requires_human_review`, `review_reasons`, plus `citations_rejected`, `corrections_proposed`, `corrections_need_review` |

- **`evidence_coverage.value` = supported / checked.** *checked* counts `SUPPORTED`,
  `CONTRADICTED` and `NOT_ENOUGH_EVIDENCE` results; `ERROR` results weren't checked and are
  counted separately. The value is `null` when nothing was checked, never 0% or 100%. This is
  the number behind the frontend's "Evidence coverage" bar (DESIGN.md §17C, "68% supported").
  Unverified claims count against coverage, because missing evidence never counts as support.
- **`requires_human_review`** is true when any reason applies:
  - `contradicted_claims` or `unverified_claims`;
  - `processing_errors` (an `ERROR` result or a request-level error);
  - `citations_rejected` (the guard downgraded an answer);
  - `corrections_need_review`;
  - `weak_evidence` (a `SUPPORTED` claim rests only on weak evidence; Phase 5).

  It is a routing signal, never an approval. Approval always belongs to a person (Member 3's
  governance rules).
- **No thresholds.** None have been approved. The score never turns coverage into pass/fail; a
  report with 99% coverage and one contradicted claim still requires review. The 85% / 15%
  targets in DESIGN.md §17G are evaluation targets for the Trust Scorecard, not report thresholds.

**Kept separate:**

| Signal | Where it lives | Feeds the score? |
|---|---|---|
| Retrieval relevance (BM25 score, rank) | `EvidencePassage.retrieval` | No. It ranks passages for one claim only and isn't comparable across claims. |
| Verification verdict | `ClaimResult.verdict` | Yes, as counts |
| Citation validity | `ClaimResult.citation_guard` | Only as a count of downgrades. A rejected citation can never raise coverage, because it turns the answer into `NOT_ENOUGH_EVIDENCE`. |
| Model-reported confidence | Not collected. The verifier and corrector schemas have no confidence field, and a reply that adds one is rejected. | No |
| Evidence strength | `ClaimResult.evidence_strength` | Only as the `weak_evidence` review reason |

### Evidence strength (per claim, Phase 5)

The approved stand-in for a confidence score. It's an ordinal label computed by
`schemas.evidence_strength`, enforced by the contract, and **never a probability**. It has not
been calibrated against outcomes. Rules, applied in order:

| Label | When |
|---|---|
| `none` | The verdict is `NOT_ENOUGH_EVIDENCE` or `ERROR`. That includes every answer the citation guard downgraded, so **a rejected citation can't be rescued** by retrieval rank, retrieval score or anything the model says. |
| `weak` | A definite verdict, but no accepted citation comes from the top-ranked retrieved passage |
| `strong` | A citation comes from the top-ranked passage, **and** either there are two or more accepted citations, or the verdict is `SUPPORTED` and the claim contains figures (digits), all of which the support checks matched in the quotes |
| `moderate` | Otherwise: one accepted citation, from the top-ranked passage |

**Inputs:**
- **The verifier's output:** only its verdict, after the guard.
- **Citation-guard results:** accepted citations, and passing the support checks.
- **Retrieval:** only the rank of cited passages. Raw BM25 scores aren't comparable across claims, so they're never used.

**What it doesn't mean:**
- `strong` isn't "probably true", and `weak` isn't "probably false".
- It says how directly the accepted evidence was found, nothing more.

**Threshold:** one, approved. A `SUPPORTED` claim with `weak` evidence requires human review.
There are no other thresholds.

**Limitations:**
- Rank 1 depends on BM25, so a paraphrased or lexically distant source can make good evidence
  look `weak`.
- Two citations from the same passage count as two.
- Whether the label predicts verdict correctness hasn't been measured; that needs live-model
  results.

## Mapping to Member 3's shared values

Member 3's planning notes (`member3_backend/00_CONTEXT.md`) define the verification statuses
`supported | contradicted | unverified | conflicting_sources | not_applicable`, and a findings
table with `suggested_correction` and `requires_human_review`. The proposed mapping isn't agreed
yet:

| Engine | Member 3 |
|---|---|
| `SUPPORTED` | `supported` |
| `CONTRADICTED` | `contradicted` |
| `NOT_ENOUGH_EVIDENCE` | `unverified` |
| `ERROR` | no finding status; the review should go to `failed` or `needs_human_review` (their rule: "never fail open") |
| none | `conflicting_sources`: the verifier currently folds conflicting evidence into `NOT_ENOUGH_EVIDENCE` and can't report it separately |
| `correction.replacement_text` (only when `correction_attempt.status` is `proposed`) | `suggested_correction` |
| `ReportScore.requires_human_review` | review state `needs_human_review` |

## HTTP endpoint: `POST /v1/verify` (walking skeleton, Phase 2)

Code: [`api.py`](src/inkloom_verify/api.py). The body is a `VerificationRequest` and the 200
response is a `VerificationReport` (`null` fields omitted). The engine ships a **router**, not a
server. The backend mounts it inside its own app, where its authentication, request-id middleware
and error handlers apply (INTEGRATION.md).

Errors use the backend's shape (`contract/README.md`): `{"error": {"code", "message", "request_id"}}`.

| Situation | HTTP | `error.code` |
|---|---|---|
| Malformed JSON, schema violation, or a body over the size limit | 422 | `VALIDATION_ERROR`. The message lists field locations only, never submitted values. |
| Body `tenant_id` is not the authenticated tenant | 403 | `FORBIDDEN` |
| Unexpected failure, including an engine returning a report that doesn't answer the request | 500 | `INTERNAL_ERROR` ("an internal error occurred") |
| A processing failure inside the engine (provider down, malformed model output, …) | **200** | No HTTP error. The report's `status` is `PARTIAL` or `FAILED`, and its `errors` say what went wrong. |

The response header `X-Inkloom-Engine-Mode` names the engine that answered.

**Engines behind the endpoint.** Since Phase 4 the real engine is
`pipeline.PipelineEngine` (`X-Inkloom-Engine-Mode: live`): extraction, retrieval, verification
and the citation guard. Corrections are off until Phase 5. The development app serves it with
`INKLOOM_ENGINE_MODE=live`, and fails at startup with the configuration message if
`OPENROUTER_API_KEY` or `INKLOOM_LLM_MODELS` is missing. The labelled fake engine below remains
for work without a key, and is used only with `INKLOOM_ENGINE_MODE=fake`.

**The fake engine** ([`fake_engine.py`](src/inkloom_verify/fake_engine.py)).
- **Evidence is retrieved for real:** BM25 over the request's own reference set, using the
  same request-scoped retriever as the pipeline. (Phase 3 replaced the Phase 2 hard-coded
  retriever, and the development-only `fixed` retrieval method was removed with it.)
- **Verdicts are canned,** assigned by claim position. A claim with no retrieved evidence is
  always `NOT_ENOUGH_EVIDENCE`.

**No AI verification is performed, and every response says so:**

- the `X-Inkloom-Engine-Mode: fake` header;
- `provenance.provider = "fake"`, `model_id = "fake/canned-v1"`;
- a request-level `PROVIDER_NOT_CONFIGURED` error, so the status is never `COMPLETED` and
  `score.requires_human_review` is always true;
- `FAKE ENGINE` at the start of every rationale.

The development server only serves it when asked: `INKLOOM_ENGINE_MODE=fake`.

## Limits (provisional)

| Limit | Value |
|---|---|
| Content | 100,000 characters |
| References per request | 50 |
| Characters per reference | 1,000,000 |
| Reference characters per request | 5,000,000 |
| Claims per report | 200 |
| Characters per claim | 1,000 |
| Passages per claim | 8 |
| Characters per passage | 4,000 |
| Passages indexed per corpus | 50,000 (retrieval) |

## Retrieval

Code: [`chunking.py`](src/inkloom_verify/chunking.py) and
[`retrieval.py`](src/inkloom_verify/retrieval.py).

Retrieval takes one claim plus the reference documents of one request and returns up to
`top_k` `EvidencePassage`s, best first. It is lexical (BM25), deterministic, and never calls a
model. Every returned passage is an exact slice of a supplied document. Nothing is summarised,
rewritten or generated.

**Interface.** Callers depend on the `EvidenceRetriever` protocol: a `method` attribute and
`retrieve(claim, top_k=None) -> list[EvidencePassage]`. `BM25Retriever` is the only
implementation. Adding another method also requires a new `RetrievalMethod` value, which is a
contract change.

### Passage splitting (`ChunkingConfig`)

Both strategies first split the document into paragraphs at blank lines, then into segments at
line breaks and sentence ends (`.`, `!`, `?`, `…` followed by whitespace). Common abbreviations
such as `e.g.`, `Inc.` and `No.` don't end a sentence. Decimals such as `4.5` are safe because no
whitespace follows the dot.

**`tokens` (the default since the retrieval phase): chunks of 200–400 tokens with overlap.**

1. Any segment longer than `max_tokens` is cut into windows of `max_tokens` words.
2. Consecutive segments are packed into a chunk until it reaches `target_tokens`. A chunk never
   exceeds `max_tokens` or 4,000 characters. Chunks may cross paragraph breaks.
3. Each next chunk starts early enough to repeat at least `overlap_tokens` of the previous one.
   Overlap is whole sentences.
4. A short final chunk is extended backwards to at least `min_tokens`, where the document is
   long enough.
5. A document shorter than `min_tokens` becomes a single chunk.

Tokens are whitespace-separated words. That's an approximation of model tokens (roughly 1.3
model tokens per English word), chosen so that chunking needs no tokenizer dependency.

| Setting | Default | Allowed |
|---|---|---|
| `target_tokens` | 300 | 20–600, and `min_tokens` ≤ target ≤ `max_tokens` |
| `min_tokens` | 200 | 10–600 |
| `max_tokens` | 400 | 20–600 |
| `overlap_tokens` | 50 | 0–300, and below `min_tokens` |

**`sentences`** (the previous default, still available): windows of `sentences_per_passage`
segments of one paragraph, advancing by `stride` and shrunk to fit `max_passage_chars`.

| Setting | Default | Allowed |
|---|---|---|
| `sentences_per_passage` | 2 | 1–10 |
| `stride` | 1 | 1 to `sentences_per_passage` (a larger stride would skip text) |
| `max_passage_chars` | 1,000 | 50–4,000 |

**Settings for the other strategy are refused, not ignored.** For example,
`ChunkingConfig(sentences_per_passage=1)` without `strategy="sentences"` is an error, so a
stale configuration can't silently change how documents are split.

**Scoping.** `BM25Retriever.for_request(request)` indexes exactly the request's `references` and
records `(tenant_id, reference_set_id)` as its scope; the pipeline uses it. Retrievers keep no
shared state: no index cache and no class-level data. So two tenants, or two reference sets,
never see each other's passages, even when they use the same `reference_set_id` or `doc_id`.
The engine still never looks a reference set up; the backend sends the documents.

### Ranking (`RetrievalConfig`)

| Setting | Default | Meaning |
|---|---|---|
| `top_k` | 5 | Number of passages returned, 1–8 (the contract's per-claim maximum). It can be overridden per call. |
| `k1`, `b` | 1.5, 0.75 | Standard BM25 parameters. |
| `min_matched_terms` | 1 | Minimum number of distinct claim terms a passage must contain. |
| `min_term_coverage` | 0.25 | Minimum fraction of the claim's distinct terms a passage must contain. |
| `suppress_overlaps` | off | Skip a passage that overlaps one already selected from the same document. |

- **Tokenisation.** Text is NFKC-normalised and case-folded, and split into word and number
  tokens. Thousands separators are removed (`1,200` becomes `1200`) and decimals stay whole
  (`4.5`). A small English stopword list is dropped; it deliberately keeps negations such as
  `not`, `no` and `never`. Each claim term is counted once.
- **IDF.** Scoring uses `rank_bm25.BM25Okapi` with the Lucene IDF,
  `log(1 + (N − n + 0.5)/(n + 0.5))`, in place of rank_bm25's floored Okapi IDF. The stock IDF
  goes negative on small corpora: with a single passage, every term scores below zero. With
  the Lucene IDF, a passage that shares no terms scores exactly 0, and any shared term scores
  above 0.
- **Ordering.** Results are ordered by score; ties go to the earlier document, then the earlier
  position.
- **Duplicates.** Passages whose text is identical after case-folding and whitespace collapsing
  are returned once. The highest-ranked copy wins, which on a tie is the earliest document.
- **No relevant passage.** If no passage passes the relevance gate, `retrieve` returns `[]`. The
  claim then goes to `NOT_ENOUGH_EVIDENCE` without reaching the verifier.

### Input handling

| Input | Result |
|---|---|
| Empty list of documents | The retriever builds, and every claim gets `[]`. |
| Missing, blank or malformed `doc_id`; blank `text`; wrong `text_sha256` | `pydantic.ValidationError`, raised by the `ReferenceDocument` contract. |
| A single document, mapping or string passed in place of a list | `RetrievalError` |
| Duplicate `doc_id`s | `RetrievalError` |
| A document with no searchable terms (only symbols or stopwords) | Indexed as nothing; it never matches. |
| Malformed claim | `pydantic.ValidationError` |
| `top_k` outside 1–8, or not an integer | `RetrievalError` |
| More than 50,000 passages | `RetrievalLimitError` |

### Untrusted text

Document text is only tokenised and counted. It is never interpreted, followed, fetched or
executed, and retrieval opens no files or network connections. Tests block `open` and sockets
to prove this. Passage ids and scores are computed from offsets and counts, so text that
imitates them, such as `"passage_id": "psg_fake"`, has no effect.

An injected instruction is still returned **verbatim** when it is lexically relevant to a claim,
because evidence is never edited. The defences against such text reaching the model are in later
phases: the verifier prompt marks passages as untrusted data (Phase 5), and citations are checked
deterministically against the source (Phases 1 and 5).

### Known limitations

- **Lexical only.** BM25 misses paraphrases and synonyms ("dishwasher safe" vs. "machine
  washable"), and there's no stemming ("hour" doesn't match "hours"). Retrieval recall@k will be
  measured in Phase 8. A dense or hybrid retriever would be a scope change.
- **English-only stopwords.** Other languages still tokenise, but common words in them are not
  removed.
- **Keyword stuffing.** A passage that repeats a claim's words ranks high. BM25's term-frequency
  saturation limits this but doesn't stop it, so the verifier must still judge the content.
- **Ranking favours shared names.** For "The Lumen Bottle is made from 90% recycled steel", a
  header sentence that only names the product can outrank the sentence about the steel. The
  defaults return both (`top_k` = 5), but with a small `top_k` the evidence can be pushed out.
- **Overlap suppression is off by default.** With overlapping windows it dropped the
  evidence-bearing window in testing, so overlapping passages are returned and use up `top_k`
  slots.
- **Rule-based sentence splitting.** It can split after unlisted abbreviations, and it does not
  split sentences that have no whitespace after the full stop.
- **Code-point offsets.** These need conversion in a JavaScript UI (integration question 1).
- **One index per corpus.** The index is built in memory for each retriever; nothing is
  persisted or shared between requests. Scoring is a Python loop over all passages per query
  term, so very large corpora with many claims will be slow. This has not been benchmarked yet.

## Sample payloads

These files are full, validated examples. The tests load every one of them and check them
against each other: the report answers the request, and every passage, citation and correction
matches the original text exactly.

**Valid fixtures.** Each one validates and round-trips through JSON, and the request and reports
pass the scope check against each other:

- [`examples/verification_request.json`](examples/verification_request.json): includes a `reference_set_id`
- [`examples/verification_report.json`](examples/verification_report.json): `COMPLETED`; one `SUPPORTED`, one `CONTRADICTED` with a proposed correction, one `NOT_ENOUGH_EVIDENCE`
- [`examples/verification_report_failed.json`](examples/verification_report_failed.json): `FAILED` with `PROVIDER_NOT_CONFIGURED` and no results
- [`examples/claim_result_error.json`](examples/claim_result_error.json): an `ERROR` result
- [`examples/end_to_end/`](examples/end_to_end/): a `PARTIAL` report produced by the pipeline (scripted model), and its mapping to Member 3's findings

**Invalid fixtures.** [`examples/invalid/`](examples/invalid/) holds 14 payloads, each with exactly
one defect. [`examples/invalid/cases.json`](examples/invalid/cases.json) lists, for each one:

- the model it targets;
- what is wrong;
- the text the engine's error summary (`describe_validation_error`) contains;
- whether the exported **JSON Schema alone** rejects it.

**JSON Schema catches only 5 of the 14.** The other nine break cross-field rules that only the
Pydantic models enforce:

- the content hash;
- whitespace-only content;
- citations that must point into `evidence`;
- verbatim quotes;
- the verdict/citation, correction and error rules;
- the review flag;
- report status.

Member 3 (Python) should validate with `inkloom_verify.schemas`, not the JSON Schema files. Member 1
receives Member 3's API, not engine payloads.
- [`examples/eval_records.jsonl`](examples/eval_records.jsonl): evaluation records

### Request (abridged)

```json
{
  "contract_version": "0.1.0",
  "request_id": "req-2026-10-22-0001",
  "tenant_id": "tenant-acme",
  "content": {
    "content_id": "draft-launch-email-v2",
    "text": "The Lumen Bottle keeps drinks cold for up to 24 hours. It is made from 90% recycled steel. Lumen was founded in 2015."
  },
  "references": [
    {
      "doc_id": "spec-sheet",
      "version": "v3",
      "title": "Lumen Bottle Product Specification",
      "text": "Lumen Bottle Product Specification. Insulation: keeps drinks cold for up to 24 hours and hot for up to 12 hours. Body: 18/8 stainless steel with 70% recycled content."
    }
  ]
}
```

`text_sha256` was omitted here and is computed by the engine.

### One `CONTRADICTED` result from the report (abridged)

The hash values are shortened as `…` for readability; the example file has them in full.

```json
{
  "claim": {
    "claim_id": "clm_0002",
    "text": "The Lumen Bottle is made from 90% recycled steel.",
    "source_span": { "start": 55, "end": 90 }
  },
  "verdict": "CONTRADICTED",
  "evidence": [
    {
      "passage_id": "psg_796412a63320eb0e15bd336c",
      "doc_id": "spec-sheet",
      "doc_text_sha256": "4518ea23…",
      "span": { "start": 113, "end": 166 },
      "text": "Body: 18/8 stainless steel with 70% recycled content.",
      "retrieval": { "method": "bm25", "score": 3.91, "rank": 1 }
    }
  ],
  "citations": [
    {
      "doc_id": "spec-sheet",
      "doc_text_sha256": "4518ea23…",
      "passage_id": "psg_796412a63320eb0e15bd336c",
      "quote": "70% recycled content",
      "quote_span": { "start": 145, "end": 165 }
    }
  ],
  "correction": {
    "target_span": { "start": 71, "end": 74 },
    "original_text": "90%",
    "replacement_text": "70%",
    "citations": [ { "...": "the same citation as above" } ]
  },
  "model_rationale": "The specification states 70% recycled content, not 90%."
}
```

## Open integration questions

These are decisions made in this draft that could break another member's integration. I have
recorded them here rather than settling them without you.

**For whoever owns parsing and storage (Member 1 or 3):**

1. **Offset units.** Spans count Unicode code points. If the UI is JavaScript, it must convert them before highlighting text (for example with `Array.from(text)`), or we switch to UTF-16 offsets. Which do you want?
2. **Text identity.** Will the text you send be byte-for-byte the text you store and display? If parsing or normalising happens again after verification, every offset and hash becomes invalid.
3. **Document identity.** Are `doc_id`s stable across versions, with `version` changing, or does each version get a new `doc_id`? Is the ID pattern compatible with your IDs (UUIDs and slugs both pass)?
4. **Empty reference set.** Is a request with no references a caller error (current rule: rejected), or should it return `NOT_ENOUGH_EVIDENCE` for every claim?
5. **Size limits.** Do the provisional limits fit your largest real brand guidelines and content? Will you split larger inputs into chunks, or should the engine?

**For whoever owns tenants, auth and the API layer:**

6. **Tenant id.** Should `tenant_id` be in the request body (current design), or come only from the authenticated context? If it's in the body, the API layer must reject a body `tenant_id` that differs from the caller's.
7. **Validation error responses.** FastAPI's default 422 response echoes the offending input, which can include document text. Who owns that error handler? The engine side plans to strip input values (Phase 7).
8. **Request and report IDs.** Who generates `request_id`? Do reports need to be stored and looked up later? That would be outside Member 2's scope.

**For Member 3 (from their planning notes, raised in Phase 6):**

12. **Status mapping.** Do you accept the mapping above? Should the verifier report
    `conflicting_sources` separately? That needs a contract change and a prompt change.
13. **Provider ownership.** Your Phase 5 says Member 3 owns the provider adapter and the engine
    must not call a provider directly. The engine already has an OpenRouter adapter behind the
    `LLMProvider` interface (Member 2, Phase 4). Your adapter could implement that interface, and
    the engine would accept it unchanged. Which one runs in production?
14. **Confidential sources.** These must never reach a cloud provider. The engine doesn't see
    source sensitivity today, so routing must be decided before the engine is called, or the
    request needs a sensitivity field.
15. **Severity.** Your findings have `severity`. The engine doesn't assign it. Who does?

**For whoever owns the review queue UI:**

9. **Verdict display.** Is `ERROR` shown as its own state, separate from `NOT_ENOUGH_EVIDENCE`? Is the absence of a "partially supported" verdict acceptable? Partially true sentences are split into atomic claims instead.
10. **Corrections.** Is one correction per claim enough? Should the UI show `model_rationale`, and if so, labelled as model-written?
11. **Scoring.** The score is not in v0.1.0; it comes in Phase 7. Does the UI need it in the report, or can it compute it from `verdict_counts`?

## Regenerating JSON Schema

```sh
cd services/verification
PYTHONPATH=src python -m inkloom_verify.json_schema
```

`tests/test_examples_and_json_schema.py` fails if the committed files in `schemas/` don't match
the models.
