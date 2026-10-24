"""Terminology rules (rules.py): preferred terms, spelling conventions, consistency, and the
matching behaviour shared by every terminology rule. All terms are configuration, never
hard-coded brand vocabulary; the ones below are test data only."""

from __future__ import annotations

import pytest

from inkloom_verify.rules import RuleConfigurationError, evaluate_rules, term_pattern
from inkloom_verify.schemas import RuleCheckStatus


def run(text: str, **kinds):
    return evaluate_rules(text, {"rule_set_id": "t", **kinds}, accessibility_defaults=False)


def texts(evaluation) -> list[str]:
    return [f.original_text for f in evaluation.findings]


# --- Preferred terms ------------------------------------------------------------------------------


def test_every_discouraged_term_is_flagged_with_the_preferred_term_as_suggestion():
    evaluation = run(
        "Send an e-mail or an electronic mail. Email is fine.",
        preferred_terms=[
            {"rule_id": "pref", "preferred": "email", "discouraged": ["e-mail", "electronic mail"]}
        ],
    )
    assert texts(evaluation) == ["e-mail", "electronic mail"]
    assert all(
        f.suggested_correction == "email" and f.suggestion_basis == "brand_rule"
        for f in evaluation.findings
    )
    assert all(
        f.category.value == "terminology" and f.rule_type.value == "preferred_term"
        for f in evaluation.findings
    )
    assert [f.finding_id for f in evaluation.findings] == ["rul_pref_1", "rul_pref_2"]


def test_preferred_term_used_correctly_passes():
    evaluation = run(
        "Email us.",
        preferred_terms=[{"rule_id": "pref", "preferred": "email", "discouraged": ["e-mail"]}],
    )
    assert evaluation.findings == [] and evaluation.checks[0].status is RuleCheckStatus.PASSED


# --- Spelling conventions ------------------------------------------------------------------------


def test_spelling_convention_flags_each_incorrect_form():
    evaluation = run(
        "The colour and the COLOUR of the colours.",
        spelling=[{"rule_id": "spell", "correct": "color", "incorrect": ["colour"]}],
    )
    assert texts(evaluation) == ["colour", "COLOUR"]  # whole words: "colours" is not "colour"
    assert all(
        f.suggested_correction == "color" and f.rule_type.value == "spelling"
        for f in evaluation.findings
    )


def test_case_sensitive_spelling_only_flags_the_exact_case():
    evaluation = run(
        "iPhone, IPhone and iphone.",
        spelling=[
            {
                "rule_id": "case",
                "correct": "iPhone",
                "incorrect": ["IPhone", "iphone"],
                "case_sensitive": True,
            }
        ],
    )
    assert texts(evaluation) == ["IPhone", "iphone"]


# --- Consistency ------------------------------------------------------------------------------------


def test_mixed_forms_flag_the_less_frequent_ones_without_a_suggestion():
    evaluation = run(
        "Wi-Fi here, Wi-Fi there, WiFi once.",
        consistency=[{"rule_id": "wifi", "variants": ["Wi-Fi", "WiFi"]}],
    )
    assert texts(evaluation) == ["WiFi"]
    finding = evaluation.findings[0]
    assert (
        finding.suggested_correction is None
        and '"Wi-Fi" (2)' in finding.explanation
        and '"WiFi" (1)' in finding.explanation
    )


def test_a_tie_keeps_the_form_used_first_and_one_form_alone_passes():
    tie = run("WiFi then Wi-Fi.", consistency=[{"rule_id": "wifi", "variants": ["Wi-Fi", "WiFi"]}])
    assert texts(tie) == ["Wi-Fi"]  # "WiFi" came first
    alone = run(
        "Wi-Fi and Wi-Fi.", consistency=[{"rule_id": "wifi", "variants": ["Wi-Fi", "WiFi"]}]
    )
    assert alone.findings == [] and alone.checks[0].status is RuleCheckStatus.PASSED


def test_consistency_never_counts_a_short_form_inside_a_longer_one():
    evaluation = run(
        "Use e-mail, e-mail and email.",
        consistency=[{"rule_id": "m", "variants": ["email", "e-mail", "mail"]}],
    )
    assert texts(evaluation) == [
        "email"
    ]  # "mail" inside "e-mail"/"email" is never counted separately


# --- Matching behaviour ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("guaranteed.", ["guaranteed"]),
        ("(guaranteed)", ["guaranteed"]),
        ('"Guaranteed!"', ["Guaranteed"]),
        ("guaranteed,guaranteed", ["guaranteed", "guaranteed"]),
        ("unguaranteed", []),
        ("guaranteedly", []),
        ("guaranteed_value", []),
    ],
)
def test_whole_word_matching_respects_punctuation_and_word_characters(text, expected):
    assert texts(run(text, prohibited_terms=[{"rule_id": "p", "term": "guaranteed"}])) == expected


def test_whole_word_can_be_switched_off_for_substrings():
    evaluation = run(
        "Unguaranteedly.",
        prohibited_terms=[{"rule_id": "p", "term": "guaranteed", "whole_word": False}],
    )
    assert texts(evaluation) == ["guaranteed"]


def test_whitespace_apostrophe_and_hyphen_variants_match_each_other():
    text = "Don’t send an e‑mail with best in class claims."
    evaluation = run(
        text,
        prohibited_terms=[
            {"rule_id": "dont", "term": "don't"},
            {"rule_id": "bic", "term": "best in class"},
        ],
        preferred_terms=[{"rule_id": "mail", "preferred": "email", "discouraged": ["e-mail"]}],
    )
    assert sorted(texts(evaluation)) == ["Don’t", "best in class", "e‑mail"]
    for f in evaluation.findings:
        assert text[f.span.start : f.span.end] == f.original_text  # offsets into the original text


def test_unicode_nfc_matching_maps_offsets_back_to_the_original_text():
    decomposed = "A café au lait and the CAFÉ menu."  # e + combining accent
    evaluation = run(
        decomposed, prohibited_terms=[{"rule_id": "cafe", "term": "café"}]
    )  # precomposed term
    assert texts(evaluation) == ["café", "CAFÉ"]
    for f in evaluation.findings:
        assert (
            decomposed[f.span.start : f.span.end] == f.original_text and len(f.original_text) == 5
        )


def test_terms_are_literal_never_regular_expressions():
    assert texts(run("a.b and axb", prohibited_terms=[{"rule_id": "p", "term": "a.b"}])) == ["a.b"]
    assert texts(
        run("x+ and xx", prohibited_terms=[{"rule_id": "p", "term": "x+", "whole_word": False}])
    ) == ["x+"]
    assert term_pattern("(.*)").pattern.startswith(r"\(")


def test_different_rules_may_flag_the_same_text_and_each_finding_names_its_rule():
    evaluation = run(
        "The best earbuds.",
        prohibited_terms=[{"rule_id": "no-best", "term": "best"}],
        preferred_terms=[
            {"rule_id": "pref-top", "preferred": "favourite", "discouraged": ["best"]}
        ],
    )
    assert sorted((f.rule_id, f.original_text) for f in evaluation.findings) == [
        ("no-best", "best"),
        ("pref-top", "best"),
    ]


def test_one_rule_never_reports_overlapping_text_twice():
    evaluation = run(
        "electronic mail",
        preferred_terms=[
            {"rule_id": "p", "preferred": "email", "discouraged": ["electronic mail", "mail"]}
        ],
    )
    assert texts(evaluation) == ["electronic mail"]


# --- Malformed configuration -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule, field",
    [
        ({"rule_id": "p", "preferred": "email", "discouraged": ["  "]}, "discouraged"),
        ({"rule_id": "p", "preferred": "", "discouraged": ["e-mail"]}, "preferred"),
        ({"rule_id": "p", "preferred": "email", "discouraged": "e-mail"}, "discouraged"),
        ({"rule_id": "p", "preferred": "email"}, "discouraged"),
    ],
)
def test_malformed_preferred_terms_are_refused(rule, field):
    with pytest.raises(RuleConfigurationError) as info:
        run("x", preferred_terms=[rule])
    assert any(field in p for p in info.value.problems)


def test_consistency_needs_two_distinct_forms_under_its_own_case_rule():
    with pytest.raises(RuleConfigurationError):
        run("x", consistency=[{"rule_id": "c", "variants": ["WiFi"]}])
    with pytest.raises(RuleConfigurationError, match="invalid brand rules"):
        run(
            "x", consistency=[{"rule_id": "c", "variants": ["WiFi", "wifi"]}]
        )  # same form when case-insensitive
    ok = run(
        "WiFi and wifi.",
        consistency=[{"rule_id": "c", "variants": ["WiFi", "wifi"], "case_sensitive": True}],
    )
    assert len(ok.findings) == 1
