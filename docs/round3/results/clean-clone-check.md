# Clean-clone check (runbook step 09, step 2)

Run on 2026-10-29 on Windows 11 with Python 3.14.6. The repo was freshly cloned from GitHub, from
branch `krish/round3-reconcile` at commit `e9055a2`, into an empty scratch folder with a new
virtual environment. `OPENROUTER_API_KEY`, `INKLOOM_LLM_MODELS` and `GEMINI_API_KEY` were unset,
and the clone had no `.env` file.

The clone was made before this phase's edits, so it checks only what is committed and pushed.

| Step (from `services/verification`) | Result |
|---|---|
| `python -m venv .venv` and `pip install -e ".[dev]" -c constraints.txt` | exit 0 |
| `python -m pytest -q` | **2054 passed, 3 xfailed, 1 warning** |
| `python eval/run_eval.py --check-baseline` | **exit 0** |
| `python eval/run_eval.py --verdicts oracle --check-baseline` | **exit 0** |
| `python eval/run_eval.py --replay eval/cassettes/final-run1.jsonl` | **exit 2, FAIL**: `cannot read cassette eval\cassettes\final-run1.jsonl: No such file or directory` |

The suite and both offline gates pass from a clean clone, without a `.env`, a key or this machine's
state. The replay fails because no recorded live run exists: step 07 has not run, so
`eval/cassettes/` doesn't exist. The script handles this correctly: it exits 2 and writes an
"incomplete" report rather than inventing numbers.

**Clean-clone check: FAIL until step 07 records `final-run1.jsonl`.**
