# SAMPLE REPORT: TEST FIXTURE, NOT A MEASUREMENT

Hand-constructed predictions and outcomes for 8 records of eval/dataset.jsonl (eval/fixtures/required_metrics/), built to exercise every formula and edge case. No model was run; these numbers say nothing about Inkloom AI's accuracy.

## Required metrics (positive class: CONTRADICTED)

Evaluated 8 records · TP 2 · FP 1 · FN 2 · TN 3 · missing predictions 1 · ERROR predictions 2 · invalid labels 0 · unexpected predictions 0

| Metric | Formula | Value |
|---|---|---|
| 1. Precision (CONTRADICTED) | TP / (TP + FP) | 66.7% (2/3) |
| 2. Recall (CONTRADICTED) | TP / (TP + FN) | 50.0% (2/4) |
| 3. False-positive rate | FP / (FP + TN) | 25.0% (1/4) |
| 4. False-negative rate | FN / (TP + FN) | 50.0% (2/4) |
| 5. Citation validity | resolving and supporting citations / all citations | 60.0% (3/5) |
|    Citation resolution | resolving citations / all citations | 80.0% (4/5) |
| 6. Retrieval recall@5 | records with gold evidence in the top 5 / records with gold evidence | 100.0% (6/6) |
| 7. Human-review share | records routed to review / records with a pipeline outcome | 71.4% (5/7) |
| 8. Correction traceability | traceable proposals / proposed corrections | 50.0% (1/2) |

Citation failures: {'does_not_resolve:quote_mismatch': 1, 'no_supporting_evidence_exists': 1}
Retrieval: 6 records with gold evidence, 2 excluded (no gold evidence), 0 empty retrievals, misses none
Review: 7 records with an outcome, 1 excluded (no outcome); auto-cleared 2; auto-cleared although not SUPPORTED: ['v1-037']
Corrections: {'proposed': 2, 'needs_human_review': 1}; 4 claims not applicable; untraceable: v1-025 ['unsupported:microwave']
