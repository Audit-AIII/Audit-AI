# INKLOOM verification engine

This is Member 2's claim-verification engine. It extracts claims from content, retrieves
evidence for each claim from the reference documents, verifies the claim against that evidence,
validates the citations, and proposes minimal evidence-backed corrections.

The engine receives plain text. Uploads, document parsing, authentication and tenancy are
handled by other members.

**Status:** Phase 1 (contracts), Phase 2 (evidence retrieval) and Phase 3 (evaluation dataset
and harness) are done. See [CONTRACTS.md](CONTRACTS.md) and [EVAL.md](EVAL.md).

## Setup

```sh
cd services/verification
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest
```

Requires Python 3.11+, Pydantic 2.10+ and rank_bm25 0.2.x.

## Layout

| Path | Contents |
|---|---|
| `src/inkloom_verify/schemas.py` | All data contracts and their validation rules |
| `src/inkloom_verify/json_schema.py` | Exports the contracts to `schemas/` as JSON Schema |
| `src/inkloom_verify/chunking.py` | Splits reference documents into traceable passages |
| `src/inkloom_verify/retrieval.py` | `EvidenceRetriever` interface and the BM25 implementation |
| `src/inkloom_verify/evaluation/` | Evaluation metrics, runner and command line (`python -m inkloom_verify.evaluation`) |
| `eval/data/` | Labelled evaluation datasets (JSONL) |
| `schemas/` | Generated JSON Schema files for integrators |
| `examples/` | Validated sample payloads |
| `tests/` | Contract tests |
