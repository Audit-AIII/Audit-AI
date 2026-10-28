# 10 — Contribute to the other two outcomes (handoffs, not ownership)

Your plan: "contribute to all three outcomes" — governance (Darsh) and tone/brand voice (Chahit's area per the team split; **[CONFIRM]** who owns tone). Your engine knowledge is the contribution. Keep this small; do not start it before step 02 is acknowledged.

## A. For Darsh — governance and risk routing

Deliver as a short doc `docs/round3/handoff-governance.md` plus a conversation:
1. The **signal table** from `02` step 5 (verdict + `review_reasons` → risk tier). Today the backend routes on `verdict != SUPPORTED` only (**[VERIFY]** `approval_rules.py`, `review_runner.py`), so the engine's decision policy (weak evidence, compound under-cited, below policy strength) is not used. That is the gap risk-based routing should close.
2. **Unknown guard reasons must not crash anything** (`property_mismatch`, `unsupported_clause`). Offer a test: feed a report containing them through the review flow.
3. **ERROR is never SUPPORTED** and never auto-approved: point to `tests/test_provider_failure_never_approved.py` in `services/api` and ask that the author-cannot-approve and routing tests include it.
4. For the demo: a risk-tiered queue is only convincing with **real engine output** behind it — offer the three live-run cases files (`cases.jsonl`) as sample data.

## B. For the tone/brand-voice owner — reuse the grounding machinery

Deliver `docs/round3/handoff-tone.md`:
1. The same pattern applies: a judgement ("this sounds off-brand") must carry **evidence** (quote + span from the brand guide), be **validated deterministically** (the quote must exist in the guide; reuse `citation_guard.find_quote`/normalisation), and **downgrade to "unsupported judgement"** when it fails — exactly how `CitationGuard` downgrades a SUPPORTED claim.
2. The dataset has `brand-guide-v4` already; tone records need their own labelled set with the same lock/held-out rules (do not mix into the verification dataset: the validator's class shares would break).
3. Metrics for tone must follow the same rule: counts, denominators, held-out only, limitations.
4. Offer to review their reason codes before they become part of a contract.

## C. Things you should *not* take on unless asked
Frontend styling, invite/role UI, the tone prompts themselves.

## Done when
- [ ] Both handoff notes sent; each teammate replied or has a dated open question in the doc
