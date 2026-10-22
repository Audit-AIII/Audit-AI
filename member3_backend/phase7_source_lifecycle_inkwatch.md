# Phase 7: Source lifecycle and InkWatch (named improvement)

Read `00_CONTEXT.md` first. Requires Phase 6.

## Goal
When an approved source is replaced or withdrawn, every approved item that relied on it is re-flagged and sent back to the reviewer. This is one of the three improvements we name for the rubric.

## Tasks
1. Source lifecycle: `draft → approved → superseded | archived`. Keep every source version and what each historical review used.
2. Dependency lookup: every finding stores its evidence excerpt and `source_version_id`. Add a query that finds all content versions whose evidence cites a given source or source version.
3. Manual first: a "withdraw source" action that sets the source status, finds dependents and sets them to `source_changed`, returns them to the reviewer queue with a drift reason, and writes audit events. Build this first.
4. Then automatic: on uploading a new source version, store section-level hashes, diff against the previous version, and mark only dependents whose cited section changed.
5. Notify: add a notification record or event for the reviewer queue.
6. Approval guard: block approval of any version whose cited source was superseded after its review (already in Phase 6; verify it covers `source_changed`).
7. Optional: source conflict detection when two approved sources disagree, surfaced as `conflicting_sources` for human resolution.

## Wiring with teammates
- Member 1: needs a `source_changed` state label, the drift reason, and which source changed, in the Review Queue and Audit History.
- Member 2: confirm how `conflicting_sources` is produced; do not edit their code without asking.

## Tests (write now)
- Withdrawing a source flips every dependent approved item to `source_changed`.
- Items that do not cite the source are unaffected.
- Approval is blocked for a `source_changed` item until re-reviewed.
- Tenant isolation holds: another organisation's items are never touched.
- Audit events exist for each flipped item.

## Done when
Demo scenario works live: upload a new brand guide version and watch three approved items flip to `source_changed`.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. Build the manual withdraw flow and its tests first. Only then start the automatic section diff. Show me after each.
