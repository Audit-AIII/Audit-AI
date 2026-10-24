"""Demo: the engine's deterministic terminology and accessibility rules on a sample draft.

The backend runs these rules on every review; this script shows the engine's view directly, for
a terminal demo or when the app is unavailable. The draft and the brand rules below are demo
fixtures (the fictional Lumen Goods brand); no model is called. Run from services/verification:

    .venv/Scripts/python demo/rules_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inkloom_verify.rules import evaluate_rules  # noqa: E402

DRAFT = """# Lumen pods launch
### Specs
Our guaranteed comfort lasts all day. Send an e-mail to preorder.
Wi-Fi setup, Wi-Fi pairing and WiFi updates. [click here](https://example.com/preorder)
![](pods-hero.png) BUY NOW TODAY!
"""

BRAND_RULES = {
    "rule_set_id": "lumen-demo-rules",
    "version": "1",
    "required_terms": [{"rule_id": "req-company", "term": "Lumen Goods"}],
    "prohibited_terms": [
        {
            "rule_id": "no-guarantee",
            "term": "guaranteed",
            "approved_alternative": "designed for",
            "severity": "high",
        }
    ],
    "product_names": [{"rule_id": "name-pods", "approved_name": "Lumen Pods"}],
    "preferred_terms": [{"rule_id": "pref-email", "preferred": "email", "discouraged": ["e-mail"]}],
    "consistency": [{"rule_id": "cons-wifi", "variants": ["Wi-Fi", "WiFi"]}],
}


def main() -> None:
    evaluation = evaluate_rules(DRAFT, BRAND_RULES)
    print("DEMO FIXTURE: deterministic rules, no model call\n")
    for f in evaluation.findings:
        fix = f' -> suggest "{f.suggested_correction}"' if f.suggested_correction else ""
        print(f"[{f.category.value:13}] {f.rule_id:18} {f.original_text!r}{fix}")
        print(f"{'':16}{f.explanation}")
    print("\nChecks:")
    for c in evaluation.checks:
        print(f"  {c.status.value:13} {c.rule_id}{'  (' + c.reason + ')' if c.reason else ''}")
    print(
        f"\ncomplete={evaluation.complete}  findings={len(evaluation.findings)}  every finding needs a person's decision"
    )


if __name__ == "__main__":
    main()
