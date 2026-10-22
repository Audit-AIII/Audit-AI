# Phase 9: Stretch (only if Phases 1 to 8 pass)

Read `00_CONTEXT.md` first. Do not start until a known-good build is tagged.

## Order (cut from the bottom first)
1. Risk-based approval policy with clear, deterministic routing rules (for example high findings go to a legal reviewer, clean items to a brand manager for one-click sign-off). A human always decides.
2. Real analytics: `GET /api/analytics/brand-risk` with issue categories, turnaround time, re-review rate and queue age, computed from stored records only. Label any seeded data as seeded.
3. Hash-linked audit verification: chain each audit event to the previous one and add a verify command or endpoint. Describe it as tamper-evident, not tamper-proof.
4. Change-impact events when a new version introduces high-risk changes (strengthened guarantee, altered number, removed disclaimer). Coordinate with Member 2.
5. Audit pack export (PDF per item: findings, evidence, decisions, timestamps).

## Rules
- Each stretch feature must be testable and integrated, or it is described as future work.
- Re-run the full test suite and smoke test after each one.
- Tell me if a stretch item risks the demo; the tagged release is the fallback.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. Confirm the tagged release exists. Implement one stretch item at a time, with tests, and re-run the full suite after each.
