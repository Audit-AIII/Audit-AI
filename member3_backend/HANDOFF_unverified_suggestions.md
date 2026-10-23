# Suggested safer wording for unverified claims — handoff to Member 2

**From:** Member 3 (backend) · **To:** Member 2 (engine, `services/verification`) · **Date:** 2026-10-24

## What we need, in one paragraph

When a claim has no evidence in the brand's approved documents, the engine correctly answers
`NOT_ENOUGH_EVIDENCE` and the backend shows it as **unverified** (never "false"). The product now
also wants a **suggested safer wording** for those claims. Example: *"The Kora X2 is India's number
one smartphone."* with no ranking in any approved document is flagged unverified, and the user is
offered *"The Kora X2 is a smartphone sold in India."*. The user decides whether to use it; nothing is
applied automatically, and the finding stays unverified.

Today `ClaimCorrector` (`correction.py`) only handles `CONTRADICTED` results, and the `ClaimResult`
contract forbids a `correction` on any other verdict (`schemas.py`: "a correction is only allowed
on a CONTRADICTED claim"). So this needs a new engine step. The backend side is **already built and
tested**; it lights up as soon as the engine step exists (see "Backend side" below).

## Rules for the suggested wording (product requirements — please keep them exactly)

1. **Never invent facts.** The suggestion may only remove or soften what the claim already says.
   No new numbers, names, places, features or comparisons.
2. **Remove or soften the unsupported part.** E.g. drop the ranking; turn a guarantee into a
   description; keep everything else.
3. **Never replace one unproven ranking or superlative with another.** "number one", "#1", "best",
   "leading", "fastest", "only" are all unproven rankings. "India's number one" → "India's leading"
   is **not** a fix.
4. **Keep product names, prices and dates unchanged.**
5. **The finding stays `unverified`.** The suggestion is only a suggestion; it is never a verdict
   and never makes the claim supported.

## Proposed engine interface (please tell Member 3 if you change any name)

Mirrors `ClaimCorrector` so it is familiar and easy to review:

```python
# services/verification/src/inkloom_verify/softening.py
class ClaimSoftener:
    def __init__(self, provider: LLMProvider, config: SofteningConfig | None = None) -> None: ...

    def soften(self, result: ClaimResult, content: InputContent) -> SoftenedWording | None:
        """For a NOT_ENOUGH_EVIDENCE result only (anything else -> None, no model call).
        Returns None when the model declines or any check fails."""


class SoftenedWording(BaseModel):          # frozen, extra="forbid", like the other contracts
    target_span: SourceSpan                # inside the claim's source_span, offsets into content.text
    original_text: str                     # == content.text[target_span.start:target_span.end]
    replacement_text: str                  # single line, no hidden/control characters
```

- **Prompt:** a new versioned prompt `soften-claim-v1` (`prompts/soften-claim-v1.txt`), registered
  in `prompts.lock.json` like the other released prompts, with `PROMPT_VERSION`, `OUTPUT_SCHEMA`,
  `user_message` and `repair_message` in a `prompts/softening.py` module (same shape as
  `prompts/correction.py`, and the same `{status, original_text, replacement_text, citations,
  reason}` reply works fine — `citations` would simply be empty).
- **Return a separate object**, not `ClaimResult.correction`: that field means "evidence-backed fix
  of a contradiction" and requires citations; an unverified claim has none. (If you'd rather relax
  the contract and reuse `correction`, the backend accepts that too — see below — but a separate
  type keeps the two meanings apart.)
- **Deterministic checks inside the engine** (like `correction_issues`): no added numbers; no
  ranking/superlative term in the replacement (rule 3); every number, currency symbol, month and
  capitalised name of the original claim kept (rule 4); minimal edit; not identical; no hidden
  characters. A proposal that fails becomes `None`.
- **Budget:** one call (+ at most one repair) per unverified claim. `budget.py`'s docstring counts
  calls per claim; please add this step there.
- **Tests:** a scripted-provider test per rule above, including the "number one" → "leading" swap
  being refused, and a recorded `eval/data/softening_v1.jsonl` set if you want it measured.
- **Engine pipeline (`pipeline.py` `_run`)**: optional; the backend calls the step itself (below),
  but adding it to your own pipeline/report keeps your API consistent.

## Backend side (already done, Member 3)

`services/api/src/inkloom_api/engine/pipeline.py`:

- `load_softener_class()` imports `inkloom_verify.softening.ClaimSoftener` if it exists. Today it
  doesn't, so nothing changes. Once it exists, the backend constructs `ClaimSoftener(provider)`
  with the review's own provider (so every softening call is logged in `external_call_log` and
  goes through the same fallback chain, confidential routing included) and calls
  `soften(result, content)` for every `NOT_ENOUGH_EVIDENCE` result.
- It also accepts a `correction` attached to an unverified result, in case you relax the contract
  instead.
- Whatever comes back is spliced into the claim span (the UI replaces the finding's whole
  `original_text` with `suggested_correction`) and must pass the backend's **own** deterministic
  check, `services/api/src/inkloom_api/softening_guard.py` (the backend never trusts the engine).
  It enforces the checkable parts of rules 1, 3 and 4. A failing suggestion is dropped.
- The finding's `verification_status` stays `unverified`, `category` stays `unsupported_claim`,
  and `evidence` stays empty. A softener exception is caught and logged by type name only; the
  review is unaffected.
- Tests: `services/api/tests/test_unverified_suggestions.py` (uses a stand-in softener with exactly
  the interface above).

## Contact points

- The one backend touchpoint is `load_softener_class()` / `_propose_softening()` in
  `engine/pipeline.py`. If you pick different names, tell Member 3 and it is a two-line change.
- Questions about the product rules → the team lead; about the backend guard → Member 3.
