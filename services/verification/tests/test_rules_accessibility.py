"""Accessibility rules (rules.py, StyleRules + ContentMetadata).

For each check: a valid input passes, a violation is found with its exact text, missing data is
NOT_CHECKABLE (never "passed"), and formats the check cannot inspect (embedded players, named
colours, plain text from an uploaded file) are reported as such."""

from __future__ import annotations

import pytest

from inkloom_verify.rules import RuleConfigurationError, contrast_ratio, evaluate_rules
from inkloom_verify.schemas import RuleCheckStatus


def check(evaluation, rule_id: str):
    return next(c for c in evaluation.checks if c.rule_id == rule_id)


def found(evaluation, rule_id: str) -> list[str]:
    return [f.original_text for f in evaluation.findings if f.rule_id == rule_id]


# --- Headings ---------------------------------------------------------------------------------------


def test_well_ordered_headings_pass():
    evaluation = evaluate_rules("# Title\n## Part\n### Detail\n## Next part\n")
    assert check(evaluation, "style.headings").status is RuleCheckStatus.PASSED


def test_skipped_levels_empty_headings_and_a_second_h1_are_flagged():
    text = "# Title\n### Skipped\n##\n# Another title\n<h2>Html</h2><h5> </h5>"
    evaluation = evaluate_rules(text)
    assert found(evaluation, "style.headings") == [
        "### Skipped",
        "##",
        "# Another title",
        "<h5> </h5>",
        "<h5> </h5>",
    ]
    explanations = [f.explanation for f in evaluation.findings if f.rule_id == "style.headings"]
    assert (
        "jumps from 1 to 3" in explanations[0]
        and "empty" in explanations[1]
        and "second level-1" in explanations[2]
    )
    assert "empty" in explanations[3] and "jumps from 2 to 5" in explanations[4]


def test_plain_text_has_no_headings_to_check():
    c = check(evaluate_rules("Just a paragraph of copy."), "style.headings")
    assert c.status is RuleCheckStatus.NOT_CHECKABLE and "no headings" in c.reason


# --- Captions and transcripts ------------------------------------------------------------------


def test_video_with_a_captions_track_passes_and_without_one_is_flagged():
    good = '<video src="a.mp4"><track kind="captions" src="a.vtt"></video>'
    bad = '<video src="b.mp4" controls></video>'
    assert check(evaluate_rules(good), "style.media_captions").status is RuleCheckStatus.PASSED
    evaluation = evaluate_rules(good + bad)
    assert found(evaluation, "style.media_captions") == [bad]


def test_embedded_players_and_audio_cannot_be_inspected():
    for markup in (
        '<iframe src="https://video.example/embed/1"></iframe>',
        '<audio src="pod.mp3"></audio>',
    ):
        c = check(evaluate_rules(markup), "style.media_captions")
        assert c.status is RuleCheckStatus.NOT_CHECKABLE and "cannot be inspected" in c.reason


def test_media_metadata_decides_captions_and_transcripts():
    meta = {
        "media": [
            {"ref": "hero.mp4", "kind": "video", "captions": False},
            {"ref": "intro.mp3", "kind": "audio", "transcript": False},
            {"ref": "teaser.mp4", "kind": "video", "captions": True},
        ]
    }
    evaluation = evaluate_rules("Launch copy.", metadata=meta)
    explanations = [
        f.explanation for f in evaluation.findings if f.rule_id == "style.media_captions"
    ]
    assert explanations == [
        'Video "hero.mp4" has no captions (from metadata).',
        'Audio "intro.mp3" has no transcript (from metadata).',
    ]
    assert all(
        f.scope == "document" for f in evaluation.findings if f.rule_id == "style.media_captions"
    )


def test_unknown_media_metadata_is_not_checkable_not_passed():
    c = check(
        evaluate_rules("Copy.", metadata={"media": [{"ref": "x.mp4", "kind": "video"}]}),
        "style.media_captions",
    )
    assert c.status is RuleCheckStatus.NOT_CHECKABLE


def test_no_media_anywhere_is_not_checkable():
    assert (
        check(evaluate_rules("Copy."), "style.media_captions").status
        is RuleCheckStatus.NOT_CHECKABLE
    )


# --- Colour contrast --------------------------------------------------------------------------------


def test_contrast_ratio_matches_the_wcag_reference_values():
    assert contrast_ratio((0, 0, 0), (1, 1, 1)) == pytest.approx(21.0)
    assert contrast_ratio((1, 1, 1), (1, 1, 1)) == pytest.approx(1.0)
    grey = 0x76 / 255  # #767676 on white is the classic 4.54:1
    assert contrast_ratio((grey, grey, grey), (1, 1, 1)) == pytest.approx(4.54, abs=0.01)


def test_inline_colour_pairs_below_the_ratio_are_flagged_and_good_ones_pass():
    good = '<p style="color:#000000; background-color:#FFFFFF">ok</p>'
    bad = "<span style='color: #777; background: #888'>grey</span>"
    assert check(evaluate_rules(good), "style.contrast").status is RuleCheckStatus.PASSED
    evaluation = evaluate_rules(good + bad)
    assert found(evaluation, "style.contrast") == ["<span style='color: #777; background: #888'>"]
    # #777 on #888: luminances 0.184 and 0.246 -> (0.246 + 0.05) / (0.184 + 0.05) = 1.26
    assert "is 1.26:1; at least 4.5:1 is needed" in evaluation.findings[-1].explanation


def test_background_color_is_not_mistaken_for_the_text_colour():
    evaluation = evaluate_rules('<p style="background-color:#ffffff; color:#fefefe">x</p>')
    assert len(found(evaluation, "style.contrast")) == 1  # fg #fefefe vs bg #ffffff, not bg vs bg


def test_named_colours_or_a_missing_background_are_not_checkable():
    for markup in (
        '<p style="color:red;background:white">x</p>',
        '<p style="color:#000">x</p>',
        "Plain text.",
    ):
        assert (
            check(evaluate_rules(markup), "style.contrast").status is RuleCheckStatus.NOT_CHECKABLE
        ), markup


def test_metadata_colours_use_the_large_text_threshold_when_marked():
    pair = {"ref": "banner", "foreground": "#777777", "background": "#ffffff"}  # about 4.48:1
    normal = evaluate_rules("Copy.", metadata={"colors": [pair]})
    large = evaluate_rules("Copy.", metadata={"colors": [pair | {"large_text": True}]})
    assert len(found(normal, "style.contrast")) == 1 and found(large, "style.contrast") == []


def test_malformed_metadata_colour_is_refused():
    with pytest.raises(RuleConfigurationError):
        evaluate_rules(
            "Copy.", metadata={"colors": [{"ref": "x", "foreground": "#12", "background": "#fff"}]}
        )


# --- Alt text (metadata) and link text ----------------------------------------------------------


def test_metadata_images_without_alt_text_are_flagged_and_decorative_ones_pass():
    meta = {
        "images": [
            {"ref": "page 2 photo"},
            {"ref": "divider.png", "alt_text": ""},
            {"ref": "logo", "alt_text": "Lumen logo"},
        ]
    }
    evaluation = evaluate_rules("Copy.", metadata=meta)
    assert [f.explanation for f in evaluation.findings if f.rule_id == "style.alt_text"] == [
        'Image "page 2 photo" has no alt text (from metadata).'
    ]


def test_no_images_anywhere_is_not_checkable_with_a_reason_about_uploaded_files():
    c = check(evaluate_rules("Copy."), "style.alt_text")
    assert c.status is RuleCheckStatus.NOT_CHECKABLE and "uploaded files" in c.reason


def test_text_without_links_cannot_have_its_link_text_checked():
    assert check(evaluate_rules("Copy."), "style.link_text").status is RuleCheckStatus.NOT_CHECKABLE
    assert (
        check(
            evaluate_rules("See [the battery guide](https://example.com)."), "style.link_text"
        ).status
        is RuleCheckStatus.PASSED
    )


# --- Configuration ------------------------------------------------------------------------------------


def test_each_accessibility_check_can_be_switched_off_and_then_is_not_reported():
    off = {
        "rule_set_id": "r",
        "style": {"heading_structure": False, "media_captions": False, "color_contrast": False},
    }
    ids = {c.rule_id for c in evaluate_rules("# A\n### B", off).checks}
    assert (
        "style.headings" not in ids
        and "style.media_captions" not in ids
        and "style.contrast" not in ids
    )
    assert "style.all_caps" in ids


def test_accessibility_findings_never_suggest_a_correction():
    text = "# A\n### B BUY NOW TODAY 🔥🔥🔥 [click here](x) ![](y.png) <video></video>"
    evaluation = evaluate_rules(text)
    assert evaluation.findings and all(
        f.category.value == "accessibility" and f.suggested_correction is None
        for f in evaluation.findings
    )
