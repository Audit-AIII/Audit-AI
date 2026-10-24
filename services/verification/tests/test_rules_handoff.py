"""RULES_HANDOFF.md stays true: every ```python block in it runs, in order, in one namespace."""

from __future__ import annotations

import re
from pathlib import Path

HANDOFF = Path(__file__).resolve().parents[1] / "RULES_HANDOFF.md"


def test_every_python_example_in_the_handoff_runs():
    blocks = re.findall(r"```python\n(.*?)```", HANDOFF.read_text(encoding="utf-8"), re.DOTALL)
    assert len(blocks) >= 4
    namespace: dict = {}
    for number, block in enumerate(blocks, start=1):
        exec(compile(block, f"RULES_HANDOFF.md python block {number}", "exec"), namespace)  # noqa: S102


def test_the_handoff_names_every_rule_type_and_category():
    from inkloom_verify.schemas import RuleCategory, RuleType

    text = HANDOFF.read_text(encoding="utf-8")
    for rule_type in RuleType:
        assert f"`{rule_type.value}`" in text, rule_type
    for category in RuleCategory:
        assert f"`{category.value}`" in text, category
