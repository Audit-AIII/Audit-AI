# Test fixture: required metrics (not a measurement)

Hand-constructed inputs that exercise every formula and edge case of
`inkloom_verify.evaluation.required_metrics` (EVAL.md Phase 4). **No model was run.** These files
say nothing about Inkloom AI's accuracy.

- `dataset.jsonl`: 8 records copied unchanged from `eval/dataset.jsonl`.
- `predictions.jsonl`: hand-written predictions. They cover:
  - 2 TP, 1 FP, 2 FN (one of them a missing prediction for `v3-006`), 3 TN (one an ERROR);
  - one citation off by one character;
  - one citation on a record with no supporting evidence.
- `cases.jsonl`: hand-written per-case outcomes. They cover:
  - one traceable correction (€99 → €129);
  - one untraceable correction ("microwave safe" adds a word not in the evidence);
  - one correction attempt that declined;
  - two auto-cleared records, one of them labelled NOT_ENOUGH_EVIDENCE.
- `SAMPLE_REPORT.md` / `.json`: generated from those files.

The expected values are worked out by hand in `tests/test_required_metrics.py`, which also
checks that the committed sample report is what the files produce. To regenerate it (from
`services/verification`):

```sh
F=eval/fixtures/required_metrics
PYTHONPATH=src python -m inkloom_verify.evaluation.required_metrics --dataset $F/dataset.jsonl \
  --predictions $F/predictions.jsonl --cases $F/cases.jsonl \
  --title "SAMPLE REPORT: TEST FIXTURE, NOT A MEASUREMENT" \
  --note "Hand-constructed predictions and outcomes for 8 records of eval/dataset.jsonl (eval/fixtures/required_metrics/), built to exercise every formula and edge case. No model was run; these numbers say nothing about Inkloom AI's accuracy." \
  --out $F/SAMPLE_REPORT.md
```
