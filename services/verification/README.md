# INKLOOM verification engine

This is Member 2's claim-verification engine. It extracts claims from content, retrieves
evidence for each claim from the reference documents, verifies the claim against that evidence,
validates the citations, and proposes minimal evidence-backed corrections.

The engine receives plain text. Uploads, document parsing, authentication and tenancy are
handled by other members.

**Status:** Phases 1–8 are built:

- contracts, evidence retrieval, and the evaluation dataset and harness;
- claim extraction with the OpenRouter provider;
- claim verification with the citation guard;
- evidence-backed corrections and the report score;
- engine-side security ([SECURITY.md](SECURITY.md));
- the end-to-end pipeline.

**The engine has not yet been evaluated against a live model**, so Phase 8 remains incomplete
(see [INTEGRATION.md](INTEGRATION.md), "What has been measured").

To integrate the engine, start with [INTEGRATION.md](INTEGRATION.md). Also see
[CONTRACTS.md](CONTRACTS.md), [EVAL.md](EVAL.md) and [PROMPTS.md](PROMPTS.md).

## Setup

```sh
cd services/verification
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest
```

Requires Python 3.11+, Pydantic 2.10+, rank_bm25 0.2.x and httpx.

LLM stages need `OPENROUTER_API_KEY` and `INKLOOM_LLM_MODELS` in the environment (see
[.env.example](.env.example) and [PROMPTS.md](PROMPTS.md)). Tests need neither; they never call
a real provider.

## Layout

| Path | Contents |
|---|---|
| `src/inkloom_verify/schemas.py` | All data contracts and their validation rules |
| `src/inkloom_verify/json_schema.py` | Exports the contracts to `schemas/` as JSON Schema |
| `src/inkloom_verify/chunking.py` | Splits reference documents into traceable passages |
| `src/inkloom_verify/retrieval.py` | `EvidenceRetriever` interface and the BM25 implementation |
| `src/inkloom_verify/extraction.py` | Claim extraction and its meaning-preservation checks |
| `src/inkloom_verify/verification.py` | Claim verification: one claim and its passages per model call |
| `src/inkloom_verify/citation_guard.py` | Deterministic checks on every quotation offered as evidence |
| `src/inkloom_verify/correction.py` | Minimal, evidence-backed corrections for contradicted claims |
| `src/inkloom_verify/prompts/` | Versioned prompts and output schemas |
| `src/inkloom_verify/providers/` | `LLMProvider` interface, OpenRouter adapter, scripted fake |
| `src/inkloom_verify/security.py` | Credential redaction, and cleaning of model-written display text |
| `src/inkloom_verify/api.py` | `POST /v1/verify` router, plus a development app (no auth) |
| `src/inkloom_verify/fake_engine.py` | Walking-skeleton engine: real BM25 retrieval, canned and clearly labelled verdicts (development only) |
| `src/inkloom_verify/pipeline.py` | `verify_request`: the single entry point, plus a command line |
| `src/inkloom_verify/integration.py` | Reference mapping to Member 3's Finding contract |
| `examples/end_to_end/` | Request, report and mapped findings from one pipeline run (scripted model) |
| `src/inkloom_verify/scope.py` | Checks that a report's evidence comes only from its own request |
| `src/inkloom_verify/evaluation/` | Evaluation metrics, runner and command line (`python -m inkloom_verify.evaluation`) |
| `eval/data/` | Labelled evaluation datasets (JSONL) |
| `schemas/` | Generated JSON Schema files for integrators |
| `examples/` | Validated sample payloads |
| `tests/` | Contract tests |
