# Round 3 frontend contract map

Captured 2026-10-30 from `main` at `ec484f1`. "Sent" was checked against `services/api/src/inkloom_api/schemas.py` and live responses for a seeded personal workspace. Team-only values come from `contract/examples/governance_*.json` and `docs/governance.md`, because the seed has no team workspace.

"Typed" means present in `lib/api/types.ts` or `lib/additions/evaluationRun.ts`. "Shown" means the UI reads the field.

## Review governance fields

Sent by `GET /api/reviews` and `GET /api/reviews/{id}`.

| Field | Sent | Typed | Shown | Seen live |
|---|---|---|---|---|
| `workspace` | Yes | No | No | `{id, name, is_personal: true}` |
| `author` | Yes | No | No | `{id, display_name}` |
| `owner` | Yes | No | No | `{id, display_name}` |
| `assigned_reviewer` | Yes | No | No | `null` |
| `workflow_status` | Yes | No | No | `draft`, `approved`, `blocked` |
| `risk_level` | Yes | No | No, Queue works out its own risk | `clean`, `low`, `medium`, `high` |
| `routing_reason` | Yes | No | No | `{code, text, triggered_by[]}` |
| `required_reviewer_role` | Yes | Yes, old values only | No | `reviewer` |
| `approval_mode` | Yes | No | No | `self` |
| `allowed_actions` | Yes | No | No | `create_version, rerun, submit, approve, request_changes, reject, publish, comment, dismiss_finding` (varies by review) |
| `summary_counts` | Yes | No | No, `Tally` counts in the browser | `{supported, contradicted, unverified, conflicting, tone, needs_human_review}` |
| `is_current_version` | Yes | No | No | `true` |

## Finding fields

| Field | Sent | Typed | Shown |
|---|---|---|---|
| `original_text`, `span`, `severity`, `verification_status`, `check_type`, `explanation`, `evidence`, `requires_human_review`, `suggested_correction` | Yes | Yes | Yes |
| `safer_wording`, `suggestion_basis`, `rule_type`, `scope`, `withheld_by_intent_lock`, `dismissal`, `comment_count` | Yes | Yes | Yes |
| `source_ids` | Yes | Yes | No |
| `review_reasons` | Yes | No | Not on the review page; to confirm in Phase 2 |
| `report_status` (on the review) | Yes | Yes | No |

## Tone fields

**NOT SENT:** `guideline_quote`, `guideline_source_id`, `guideline_source_title`, `guideline_source_version`, `alternative_wording`, `validation_status`, and `check_type: "tone"`. `summary_counts.tone` only counts the `all_caps_run` and `emoji_run` style rules. The shape in `docs/round3/handoff-tone.md` is a draft proposal.

## Evaluation fields

All are sent by `GET /api/evaluations/latest`, typed in `lib/additions/evaluationRun.ts` and shown. With no run, the API returns 404 `NOT_FOUND`.

`catch_rate`, `false_positive_rate`, `per_check`, `sample_size`, `run_at`, `id`, `status`, `engine_prompt_version`, `dataset_version`, `limits_note`, `latency_ms_p50`, `provider_failure_rate`, `coverage`, `by_split`, `provider_mode`.

Also sent since 2026-10-30, and shown: `catch_rate_ratio`, `false_positive_rate_ratio`, `headline` (the stored held-out split), and the ratio fields on `per_check[]`.

**NOT SENT:** `run`, `limitations` and `guard_regressions`. These are proposals in `docs/round3/contracts.md` section 17, and need Krish's published run.

## Routes with no frontend caller

The GET routes were called live as the signed-in owner and returned 200. The POST, PATCH and DELETE routes have only been read in the routers so far, not called.

| Route | Used in |
|---|---|
| `POST /api/content/{id}/submit`, `/assign`, `/mark-reviewed` | Phase 3 |
| `POST /api/content-versions/{id}/publish` | Phase 3 |
| `GET /api/content/{id}/audit`, `GET /api/workspace/audit` | Phase 4 |
| `GET /api/workspace/members`, `PATCH` and `DELETE /api/workspace/members/{user_id}` | Phase 5 |
| `GET` and `POST /api/workspace/invitations`, `POST /api/workspace/invitations/{id}/revoke` | Phase 5 |
| `POST /api/invitations/accept` | Phase 6 |
| `GET /api/workspaces`, `POST /api/auth/switch-workspace` | Phase 6 |

## Where the API differs from `docs/governance.md`, or needs care

1. **`/api/auth/me` sends `memberships_count`.** Added on 2026-10-30, after this map was first written.
2. **Solo wording in routing text.** In a personal workspace `routing_reason.text` says "a reviewer must check this draft" and `required_reviewer_role` is `reviewer`, while `approval_mode` is `self` and `approve` is allowed. The UI drops that clause for someone alone in a workspace; the stored text is unchanged.
3. **`Session` has no workspace.** `lib/session.ts` stores `organisation` and `role`, though login sends `workspace`. Phases 3 and 6 need it stored as an optional field.
4. **`workspace.is_personal` doesn't mean "one person".** It stays `true` after someone joins, so it only says how the workspace started. The API now sends `workspace.member_count`, and the UI goes by that (`isSolo` in `lib/additions/governance.ts`).
5. **Routing decisions have an actor:** the person who submitted. The contract example now shows this, and the timeline still handles a null actor.
6. **`report_status` values.** The engine sends `COMPLETED`, `PARTIAL` or `FAILED`, in capitals, and seeded reviews send `null`. The UI matches `PARTIAL` in any case.
7. **Team examples, now verified live.** `assigned_reviewer` objects and the `in_review`, `reviewed` and `published` statuses were seen on a real team in `e2e/04-team-workflow.mjs`.

## Confirmed example JSON

Use `contract/examples/governance_*.json`. Their values are illustrative placeholders, as `docs/governance.md` section 9 says.
