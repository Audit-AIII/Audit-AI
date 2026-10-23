# Evaluation reports

`eval/run_eval.py` writes one report per run here, named by its UTC start time:

| File | Contents |
|---|---|
| `<timestamp>.md` | The readable report: outcome, dataset, model, prompts, retrieval, policy, the eight metrics, confusion matrix, failures, baseline comparison, limitations, skipped checks |
| `<timestamp>.json` | Everything the report was rendered from (`report_schema: evaluation-report-v1`) |
| `<timestamp>.cases.jsonl` | Every record's outcome (full-pipeline runs only) |
| `<timestamp>.summary.json` | What the Trust Scorecard shows (contract `evaluation-summary-v1`) |

- **Never overwritten:** a second run in the same second gets a `-2` suffix.
- **Incomplete runs are recorded too.** A run that stops (invalid dataset, missing provider)
  still writes a report marked INCOMPLETE, with its error.
- **Not committed.** These files are generated, and git ignores them. CI uploads them as
  artifacts instead.

To create one, from `services/verification`, run `python eval/run_eval.py --verdicts oracle --check-baseline`.
