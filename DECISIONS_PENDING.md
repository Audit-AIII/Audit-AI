# Decisions pending

Things only Darsh (or the named owner) can decide. Each one says what is blocked and what was
built in the meantime. Governance decisions D1–D6 are already decided (docs/governance.md §3).

| # | Phase | Question | Options | Recommendation | Blocked / placeholder |
|---|---|---|---|---|---|
| P1 | 1 | Sign-up never verifies email addresses, so an invitation's "must be the invited email" check only proves the account was *registered* with that address. Add email verification? | (a) add verification + an email provider (a new service, may cost money); (b) accept the risk and treat the invite link as the secret | (b) for Round 3, (a) before real customers | Nothing blocked. Invite links are random, hashed, single use, 7-day expiry; documented in docs/governance.md §2 item 9 |
| P2 | 4 | contracts.md §15–23 (Krish) are still marked DRAFT/UNAPPROVED and the acknowledgement log (§22) is empty. Routing implements §19 as written. | (a) approve §19 as is; (b) change the mapping | (a) | Nothing blocked: the mapping lives in one file (`services/api/src/inkloom_api/risk_policy.py`), so a change is one edit plus its tests |
