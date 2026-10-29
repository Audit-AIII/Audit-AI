"""Round 3 probe cases for the binding and compound rules, written after the rules were designed.

None of these steered the rules: they check them on cases the rules were not tuned on. The text is
exactly as given in the reconcile review. Each rejected probe names the rule that must catch it;
each accepted probe must pass the whole support check, not just the two new rules.
"""

import pytest

from inkloom_verify.citation_guard import support_problems
from inkloom_verify.schemas import GuardRejectionReason

R = GuardRejectionReason

REJECTED = {
    "R1": (
        "Lumen Pods have a 3 year battery life.",
        ["Battery life: up to 12 hours of playback per charge.", "Warranty: 3 years."],
        R.PROPERTY_MISMATCH,
    ),
    "R2": (
        "The charging case weighs 5.2 g.",
        ["Weight: 5.2 g per earbud; charging case 48 g."],
        R.PROPERTY_MISMATCH,
    ),
    "R3": (
        "The Lumen Bottle is dishwasher safe and keeps drinks cold for 24 hours.",
        ["Insulation: keeps drinks cold for 24 hours."],
        R.UNSUPPORTED_CLAUSE,
    ),
    "R4": (
        "The Lumen Bottle keeps drinks hot for 5 years.",
        ["Warranty: 5 years.", "Insulation: keeps drinks hot for up to 12 hours."],
        R.PROPERTY_MISMATCH,
    ),
}

ACCEPTED = {
    "A1": ("Lumen Pods can be charged via USB-C.", ["Charging: USB-C."]),
    "A2": (
        "The Lumen Bottle holds up to 750 ml and weighs 340 g.",
        ["Capacity: up to 750 ml; weight: 340 g."],
    ),
    "A3": (
        "Lumen Pods launched in Portugal, Spain and France on 2 April 2026.",
        ["Launch date: 2 April 2026 in Portugal, Spain and France."],
    ),
    "A4": (
        "Lumen Pods have a 2-year warranty and cost €129.",
        ["Warranty: 2 years.", "Price: €129 (EU launch price)."],
    ),
    "A5": (
        "With the case, the pods provide up to 36 hours of playback in total.",
        [
            "Battery life: up to 12 hours of playback per charge; "
            "up to 36 hours with the charging case."
        ],
    ),
    "A6": (
        "Lumen Pods come with a 2 year warranty.",
        ["Warranty: 2 years.", "Battery life: up to 12 hours of playback per charge."],
    ),
    "A7": (
        "The Lumen Bottle is covered for 3 years.",
        ["Coverage: the Lumen Bottle is covered for 3 years.", "Insulation: keeps drinks cold for 24 hours."],
    ),
    "A8": (
        "Lumen Pods are guaranteed for 2 years.",
        ["Warranty: 2 years.", "Battery life: up to 12 hours per charge."],
    ),
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_probe_is_rejected(case):
    claim, quotes, reason = REJECTED[case]
    assert reason in support_problems(claim, quotes)


@pytest.mark.parametrize("case", sorted(ACCEPTED))
def test_probe_is_accepted(case):
    claim, quotes = ACCEPTED[case]
    assert support_problems(claim, quotes) == []
