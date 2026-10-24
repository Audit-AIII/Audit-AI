# Terminology and accessibility rules: integration contract for the backend

**From:** Krish (Member 2, verification engine) · **To:** Darsh (backend, `services/api`) · 2026-10-24

The rules module is built and tested in the engine. Wiring it into reviews is Darsh's part; nothing
in `services/api` was changed. Every Python example below is executed by
`tests/test_rules_handoff.py`, so this document cannot drift from the code.

## 1. What it does

`inkloom_verify.rules.evaluate_rules(text, rules, metadata)` runs deterministic checks on the
review's content. There's no model, no network and no state. It returns every **finding** plus one
**check record per rule**, so "nothing found" is never confused with "could not check".

| Category | Rule types (`rule_type`) | Configured by |
|---|---|---|
| `terminology` | `required_term`, `prohibited_term`, `product_naming`, `preferred_term`, `spelling`, `terminology_consistency` | the brand (`BrandRules`) |
| `brand_compliance` | `required_disclaimer`, `numeric_limit` | the brand (`BrandRules`) |
| `accessibility` | `all_caps_run`, `emoji_run`, `vague_link_text`, `missing_alt_text`, `heading_structure`, `missing_captions`, `low_contrast` | defaults, overridable in `BrandRules.style` |

## 2. Calling it

There's no setup and no engine object: import and call. Accessibility checks run with their defaults
even when a brand has no rules.

```python
from inkloom_verify.rules import evaluate_rules, RuleConfigurationError, RuleInputError

brand_rules = {                      # stored per brand by the backend (see section 6)
    "rule_set_id": "brand-123-rules",
    "version": "7",
    "prohibited_terms": [{"rule_id": "no-guarantee", "term": "guaranteed",
                          "approved_alternative": "designed", "severity": "high"}],
    "preferred_terms": [{"rule_id": "pref-email", "preferred": "email", "discouraged": ["e-mail"]}],
    "required_terms": [{"rule_id": "req-company", "term": "Lumen Goods"}],
}
content_text = "Guaranteed comfort. Send an e-mail."   # content_version.text, unchanged

evaluation = evaluate_rules(content_text, brand_rules)   # a RuleEvaluation

assert evaluation.complete                    # False if any rule failed to run
# Rule order: required terms, prohibited, product names, preferred, spelling, consistency,
# disclaimers, numeric limits, then accessibility. Select findings by rule_id, not by position.
assert [f.rule_id for f in evaluation.findings] == ["req-company", "no-guarantee", "pref-email"]
```

- **`text`:** the exact `content_version.text`. Spans index into it.
- **`rules`:** a dict or a `BrandRules`. `None` means accessibility checks only.
- **`metadata`** (optional): a dict or `ContentMetadata` describing images, media and colours the
  text can't carry, for example from an uploaded PDF (section 5).
- **`accessibility_defaults=False`:** skips accessibility checks unless `rules["style"]` is set.

## 3. Mapping a finding onto a `Finding` row

Use `inkloom_verify.integration.rule_finding_fields(finding)`. It returns exactly the shared-contract
fields. The backend adds `finding_id` and evidence ids, and maps evidence `doc_id` to
`source_id`/`source_version_id` the way claim evidence already is.

```python
from inkloom_verify.integration import rule_finding_fields, proposed_rule_finding_fields

finding = next(f for f in evaluation.findings if f.rule_id == "no-guarantee")
row = rule_finding_fields(finding)
assert row["check_type"] == "rule" and row["verification_status"] == "not_applicable"
assert row["requires_human_review"] is True
assert row["span"]["end"] > row["span"]["start"]     # fits ck_finding_span_order
assert content_text[row["span"]["start"]:row["span"]["end"]] == row["original_text"]
assert row["suggested_correction"] == "designed"     # replaces original_text, never auto-applied

extra = proposed_rule_finding_fields(finding)        # not in the shared contract yet (section 7)
assert extra["rule_id"] == "no-guarantee" and extra["scope"] == "text"
```

| `Finding` column | Value |
|---|---|
| `category` | `terminology`, `brand_compliance` or `accessibility` (**new values**, section 7) |
| `severity` | the rule's (`low`/`medium`/`high`/`critical`); accessibility defaults to `low` |
| `original_text`, `span_start`, `span_end` | the matched text and its half-open code-point span (never empty) |
| `check_type` | `rule` (already allowed) |
| `explanation` | fixed wording plus the matched text; never other content |
| `verification_status` | `not_applicable` (already allowed): a rule check is not an evidence verdict |
| `suggested_correction` | terminology only: the configured replacement for `original_text`, else null |
| `requires_human_review` | always true |
| `engine_claim_id` | leave null (or store `rule_id` if you add a column, section 7) |
| evidence | only when the rule has a `source` (a reference document quote): `relation` `contradicts`, `quote` = the rule's wording |

**Document-level findings.** A missing required term, a missing disclaimer, or an image or video
known only from metadata has no offending text. These findings have `scope: "document"`, and their
span anchors on the content's **first non-blank line**, so they fit the database's
`span_end > span_start` rule without a schema change. Show them as being about the whole draft.

## 4. Check records and error handling

```python
from inkloom_verify.schemas import RuleCheckStatus

statuses = {c.rule_id: c.status.value for c in evaluation.checks}
assert statuses["no-guarantee"] == "violated"
assert statuses["style.headings"] == "not_checkable"     # plain text: nothing to inspect
assert next(c for c in evaluation.checks if c.rule_id == "style.headings").reason

try:
    evaluate_rules(content_text, {"rule_set_id": "r", "required_terms": [{"rule_id": "a", "term": "x"}],
                                  "prohibited_terms": [{"rule_id": "b", "term": "X"}]})
except RuleConfigurationError as error:
    problems = error.problems
    assert problems == ["rules: Value error, conflicting rules: a requires a term that b prohibits"]
```

| Situation | What happens | Recommended backend handling |
|---|---|---|
| Malformed or contradictory rules or metadata | `RuleConfigurationError`, nothing is run; `.problems` lists field paths and rule ids, never values | Validate when the brand **saves** its rules (422 with `.problems`). If it still happens at review time, run the claim checks, record "brand rules could not be applied" in `error_summary`, and mark the review `needs_human_review` |
| Blank, non-text or oversized content | `RuleInputError` | Can't happen for a stored content version; treat like the above |
| One rule fails internally | That check has status `error` with a type-only reason; `evaluation.complete` is false; the other rules still run | Treat as incomplete: never show the draft as rule-clean, keep `needs_human_review` |
| Check lacks data | Status `not_checkable` with a reason (no links, no headings, no images, no media, no colour pairs) | Show "not checked", never "passed" |
| More than 200 findings | `truncated` is true; checks still count them all | Show the count from the checks |

Errors and logs contain rule ids and exception type names only, never submitted text or configured terms.

## 5. Optional metadata (`ContentMetadata`)

Plain text loses images, media and colours. If the upload pipeline ever extracts them, pass them:

```python
metadata = {
    "images": [{"ref": "page 2, photo", "alt_text": None}],          # None: missing; "": decorative
    "media":  [{"ref": "hero.mp4", "kind": "video", "captions": False}],
    "colors": [{"ref": "banner", "foreground": "#777777", "background": "#ffffff", "large_text": False}],
}
with_meta = evaluate_rules(content_text, brand_rules, metadata)
assert {c.rule_id: c.status.value for c in with_meta.checks}["style.alt_text"] == "violated"
```

Colours must be `#rgb`, `#rrggbb` or `rgb(r, g, b)`. Anything else is refused as malformed
metadata. An empty list means "nothing known", which gives `not_checkable`.

## 6. Storing brand rules (Darsh's decision; a proposal)

- **Storage:** a JSON column on `brand_profiles` (for example `rules JSONB`), validated with
  `BrandRules.model_validate` on save. JSON Schema:
  [`schemas/brand_rules.schema.json`](schemas/brand_rules.schema.json).
- **Cache:** include `rule_set_id` and `version` (or a hash of the stored JSON) in the result-cache
  key. Otherwise a cached review keeps old rule findings after the rules change.
- **Check records:** store `evaluation.checks` (for example as JSON on the review), so the UI can say
  which checks were not possible.

## 7. Contract changes that need Darsh and Chahit

1. **`category`:** new values `terminology`, `brand_compliance`, `accessibility` (contract/README.md
   lists claim categories only). The UI needs labels for them.
2. **Proposed finding fields:** `rule_id`, `rule_type`, `scope` (`text`/`document`),
   `suggestion_basis` (`approved_document`/`brand_rule`), `source_ids`. Add them to
   `contract/schemas/finding.schema.json` (it has `additionalProperties: false`) before storing
   them.
3. **Check records:** a field on `Review`, such as `rule_checks: [{rule_id, rule_type, category, status,
   findings, reason}]`.
4. **Brand rules storage and an API to edit them** (the backend), plus a UI (Chahit).

Until (1) and (2) land, only `rule_finding_fields(...)` output may be stored, and it already validates.

## 8. Tests

```sh
cd services/verification
python -m pytest -q tests/test_rules.py tests/test_rules_contract.py tests/test_rules_terminology.py \
    tests/test_rules_accessibility.py tests/test_rules_handoff.py
python -m pytest -q        # the whole engine suite
```

## 9. Known limitations

- **Matching is literal:** no stemming or synonyms ("guaranteed" doesn't match "guarantee"). Case,
  whole-word, whitespace, apostrophe, hyphen and Unicode NFC handling are as documented in
  `rules.py`.
- **Accessibility checks read only Markdown/HTML in the text, plus the metadata given.** They don't
  render pages, read uploaded files, judge reading level, or inspect embedded players
  (iframe/embed) or `<audio>` transcripts. Those report `not_checkable`.
- **Markdown links whose text contains `[`, or whose URL contains `(`,** aren't recognised as
  links. This is the price of matching in linear time on hostile input; such a link's text isn't
  checked.
- **Contrast uses inline `style` pairs and metadata only** (WCAG 4.5:1, or 3:1 for large text from
  metadata). Stylesheets, named colours and gradients aren't evaluated.
- **The engine's own `/v1/verify` pipeline doesn't run the rules.** The pipeline applies
  `VerificationRequest.rules` only when a request carries them, and accessibility only with an
  explicit `style` block (`check_rules`); this keeps the evaluation baselines unchanged.
