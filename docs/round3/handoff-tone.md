# Handoff: tone and brand-voice checks (Round 3 step 10B)

From Krish, 2026-10-29. **Not sent yet. DRAFT PROPOSAL.** Nothing here is built or agreed.

## First: who owns tone? (unresolved)

The documents disagree, so this has to be settled before anyone builds:

- Krish's runbook (`docs/round3/krish/10-…md`) says tone is "Chahit's area per the team split;
  **[CONFIRM]** who owns tone", and lists the tone prompts as something Krish should *not* take
  on.
- Chahit's frontend plan (`docs/round3/chahit/ROUND3_FRONTEND_PROMPTS.md`, phase map row 4)
  says the tone UI "needs Krish's tone contract". Its message to Krish asks for the tone-finding
  fields.
- `DECISIONS_PENDING.md` P5, `docs/governance.md` §10 and `risk_policy.py` (`TONE_RULE_TYPES`):
  **there is no tone or brand-voice checker yet.** The "tone" count is two style rules,
  `all_caps_run` and `emoji_run`.
- `audit-ai-final/frontend/ROUND3_CONTRACTS.md`, where Chahit's plan expects the tone
  contract, does not exist.

**Decision needed (team):** who builds the tone checker (engine side), who stores and serves its
findings (backend, Darsh), and who answers Chahit's contract question. Until then, Chahit's
Phase 4 builds against optional fields and renders nothing that the API doesn't send. That is
his plan's own fallback.

## The pattern to reuse: a judgement must carry evidence and pass a deterministic check

Treat a tone judgement exactly like a verification claim:

1. **Evidence.** Every tone finding cites the brand-guide passage it relies on (`guideline_quote`,
   the guide's source id and version), plus the exact draft span it objects to.
2. **Deterministic validation.** The quote must exist in the approved guide, and the span must
   exist in the draft. Use the engine's existing helpers rather than new ones:
   - `inkloom_verify.citation_guard.find_quote(quote, text) -> (start, end) | None`. It matches
     after normalising whitespace and quote marks, and returns offsets in the original text.
   - `inkloom_verify.citation_guard.normalize(text)`, the same normalisation with an offset map.

   Run on 2026-10-29 against the `brand-guide-v4` text from the dataset: the exact quote "Never
   use exclamation marks in headlines." gives `(62, 103)`; the same quote reflowed over a line
   break gives `(62, 103)`; the invented "Always use exclamation marks in headlines." gives
   `None`.
3. **Downgrade, never pass, on failure.** When the quote or span check fails, the judgement
   becomes an *unsupported judgement* and is not shown as a tone finding. This is how
   `CitationGuard` turns a SUPPORTED answer with a bad quote into NOT_ENOUGH_EVIDENCE: the model's
   say-so alone never counts.

## Data and metrics rules (same as verification)

- **A separate labelled tone set**, with its own lock and held-out split. Do not add tone records
  to `services/verification/eval/dataset.jsonl`: the validator forces class shares for the
  verification labels, and mixing would break them and blur both metrics.
- `brand-guide-v4` already appears in 4 verification records, so it is a ready source document.
- **Tone metrics follow the verification rules:** numerator and denominator, sample size,
  held-out only for the headline, model and configuration, date, and limitations. A rate with an
  empty denominator is `null`, never 0%.

## Proposed tone-finding shape (answers Chahit's field list; PROPOSAL)

Chahit asked for these fields. I'd keep them, add the guide version, and make
`validation_status` a closed engine-side list that consumers still treat as open:

```json
{
  "finding_id": "…",
  "check_type": "tone",
  "original_text": "…",
  "span": {"start": 0, "end": 0},
  "guideline_source_id": "…",
  "guideline_source_title": "…",
  "guideline_source_version": "…",
  "guideline_quote": "…",
  "explanation": "…",
  "alternative_wording": null,
  "validation_status": "validated | span_not_found | unsupported | downgraded",
  "severity": "…"
}
```

This is a shape, not data. Spans are in code points, as for claim findings.

**Chahit's question, "show downgraded or unsupported as uncertain, or omit?" My recommendation:
omit them as findings**, and show only a count ("N brand-voice observations hidden because they
cite no valid guideline passage"). An "uncertain" card still puts an unproven judgement in front
of the writer. His plan already keeps this as one config constant, so it's a one-line change if
the team decides otherwise. **This is the tone owner's and Chahit's decision, not mine.**

## Offers

- I'll review the tone reason codes and `validation_status` values before they enter a contract.
- I'll help set up the tone dataset's lock and held-out split using the verification tooling.

## Open questions (dated 2026-10-29, no replies yet)

1. **Team:** who owns the tone checker, and who owns the tone contract?
2. **Tone owner and Chahit:** omit or "uncertain" for downgraded or unsupported judgements?
3. **Darsh:** where tone findings are stored and served (`FindingOut` with `check_type: "tone"`
   and additive optional fields?), and whether they route in `risk_policy.py` (today
   `TONE_RULE_TYPES` covers only the two style rules).
4. **Chahit:** does the tone count in the Scorecard stay out until a tone metric with
   numerators and denominators exists (his Phase 4 task 5 says yes)?
