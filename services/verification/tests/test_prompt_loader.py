"""Versioned prompt files and their loader (PROMPTS.md Phase 1). Mocked models only.

Tests that need a missing, tampered or extra prompt never touch the real files: they point the
loader at a temporary copy of the prompts directory."""

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from e2e_support import CONTRADICTED_CLAIM, DOCS, SUPPORTED_CLAIM, RoutedProvider, careful_model, data_block, request
from inkloom_verify.api_contract import to_public_report
from inkloom_verify.correction import ClaimCorrector, CorrectionConfig
from inkloom_verify.extraction import ClaimExtractor, ExtractionConfig
from inkloom_verify.pipeline import PipelineConfig, verify_request
from inkloom_verify.prompts import correction, extraction, loader, verification
from inkloom_verify.prompts.loader import PromptIntegrityError, PromptNotFoundError, load_prompt
from inkloom_verify.verification import ClaimVerifier, VerificationConfig

ROOT = Path(__file__).resolve().parents[1]
MODULES = {"extraction": extraction, "verification": verification, "correction": correction}


@pytest.fixture
def prompt_dir(tmp_path, monkeypatch):
    """A writable copy of the prompts directory, used by the loader for this test only."""
    copy = tmp_path / "prompts"
    shutil.copytree(loader.PROMPT_DIR, copy, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    monkeypatch.setattr(loader, "PROMPT_DIR", copy)
    monkeypatch.setattr(loader, "LOCK_FILE", copy / "prompts.lock.json")
    loader.released_versions.cache_clear()
    yield copy
    loader.released_versions.cache_clear()


# --- Every required prompt loads, from its own versioned file ------------------------------------


@pytest.mark.parametrize("component", sorted(MODULES))
def test_every_required_prompt_loads(component):
    module = MODULES[component]
    loaded = load_prompt(component, module.PROMPT_VERSION)
    assert loaded.released and loaded.version == module.PROMPT_VERSION
    assert (loader.PROMPT_DIR / f"{module.PROMPT_VERSION}.txt").is_file()
    assert loaded.text == module.SYSTEM_PROMPT  # the module's prompt is the file's text


V1_HASHES = {  # taken from the inline text before Phase 1 moved it into files; never changes
    "extract-claims-v1": "d7f14fc360aaecfbe5fe6f1560341d079781ba945ba519f207ed6797466a7bec",
    "verify-claim-v1": "5d8506866d6f947f359127a202c719c619cd085aea785141552b3582f3edf1c4",
    "correct-claim-v1": "82602e695c086cb48e975651b67108a996bb7434ea587e2b83bf92fe3f8bc011",
}


# The softening prompt (Member 3's handoff, unverified-claim suggestions), released 2026-10-24.
SOFTENING_HASHES = {"soften-claim-v1": "89437617260bf8c51242a81d4848c1e1b3e3c232bc171c8272428dce488f61ab"}


def test_the_wording_is_exactly_the_released_text():
    """Phase 1 moved the prompts into files without changing a character; Phase 6 added v2 files
    beside them without touching v1; the softening step added soften-claim-v1."""
    lock = json.loads((loader.LOCK_FILE).read_text(encoding="utf-8"))["released"]
    assert set(lock) == set(V1_HASHES) | {"extract-claims-v2", "verify-claim-v2", "correct-claim-v2"} | set(SOFTENING_HASHES)
    for version, digest in (V1_HASHES | SOFTENING_HASHES).items():
        assert lock[version]["sha256"] == digest
    for version, entry in lock.items():
        assert load_prompt(entry["component"], version).sha256 == entry["sha256"]


def test_every_shipped_prompt_file_is_a_released_version():
    lock = json.loads((loader.LOCK_FILE).read_text(encoding="utf-8"))["released"]
    assert sorted(p.stem for p in loader.PROMPT_DIR.glob("*.txt")) == sorted(lock)


def test_prompt_files_are_package_data():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(config["tool"]["setuptools"]["package-data"]["inkloom_verify"]) == {"prompts/*.txt", "prompts/prompts.lock.json"}


# --- Missing, wrong or unexpected versions fail clearly; nothing falls back ----------------------


@pytest.mark.parametrize("version", ["verify-claim-v3", "verify-claim-v99"])
def test_a_missing_version_is_a_clear_error_not_a_fallback(version):
    with pytest.raises(PromptNotFoundError, match=rf"{version}.*not found.*available verification versions: verify-claim-v1, verify-claim-v2"):
        load_prompt("verification", version)


@pytest.mark.parametrize("version", ["verify-claim-latest", "verify-claim", "verify-claim-v1.txt", "../verify-claim-v1", ""])
def test_malformed_versions_are_refused(version):
    with pytest.raises(PromptNotFoundError, match="is not a verification prompt version"):
        load_prompt("verification", version)


def test_another_components_version_is_refused():
    with pytest.raises(PromptNotFoundError, match="is not a verification prompt version"):
        load_prompt("verification", "extract-claims-v1")


def test_an_unknown_component_is_refused():
    with pytest.raises(PromptNotFoundError, match="unknown prompt component"):
        load_prompt("summarisation", "summarise-v1")


def test_a_deleted_prompt_file_is_a_clear_error(prompt_dir):
    (prompt_dir / "correct-claim-v1.txt").unlink()
    with pytest.raises(PromptNotFoundError, match="correct-claim-v1.*not found.*versions: correct-claim-v2$"):
        load_prompt("correction", "correct-claim-v1")


def test_an_empty_prompt_file_is_refused(prompt_dir):
    (prompt_dir / "verify-claim-v3.txt").write_text("\n", encoding="utf-8")
    with pytest.raises(PromptNotFoundError, match="empty"):
        load_prompt("verification", "verify-claim-v3")


# --- Released prompts are never overwritten -------------------------------------------------------


def test_an_edited_released_prompt_is_refused(prompt_dir):
    path = prompt_dir / "verify-claim-v1.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("Decide using only the passages.", "Decide."), encoding="utf-8")
    with pytest.raises(PromptIntegrityError, match="edited in place"):
        load_prompt("verification", "verify-claim-v1")


def test_a_lock_entry_for_the_wrong_component_is_refused(prompt_dir):
    lock = json.loads((prompt_dir / "prompts.lock.json").read_text(encoding="utf-8"))
    lock["released"]["verify-claim-v1"]["component"] = "extraction"
    (prompt_dir / "prompts.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    loader.released_versions.cache_clear()
    with pytest.raises(PromptIntegrityError, match="lists 'verify-claim-v1' under 'extraction'"):
        load_prompt("verification", "verify-claim-v1")


def test_a_windows_checkout_sends_the_same_text(prompt_dir):
    path = prompt_dir / "verify-claim-v1.txt"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))  # what git autocrlf produces
    assert load_prompt("verification", "verify-claim-v1").sha256 == V1_HASHES["verify-claim-v1"]


def test_an_unreleased_version_loads_only_when_asked_for_by_name(prompt_dir):
    (prompt_dir / "verify-claim-v3.txt").write_text("Draft wording.\n", encoding="utf-8")
    draft = load_prompt("verification", "verify-claim-v3")
    assert draft.text == "Draft wording." and draft.released is False
    assert verification.PROMPT_VERSION == "verify-claim-v1"  # the default is untouched
    assert load_prompt("verification", verification.PROMPT_VERSION).released


# --- Each component sends its own configured prompt -----------------------------------------------


def test_each_component_sends_its_own_prompt():
    provider = RoutedProvider(careful_model)
    report = verify_request(request(), provider)
    systems = {call.schema_name: call.system for call in provider.calls}
    assert systems == {"claim_extraction": extraction.SYSTEM_PROMPT, "claim_verification": verification.SYSTEM_PROMPT,
                       "claim_correction": correction.SYSTEM_PROMPT}
    assert report.provenance.prompt_versions == {"extract_claims": "extract-claims-v1", "verify_claim": "verify-claim-v1",
                                                 "correct_claim": "correct-claim-v1"}


@pytest.mark.parametrize(
    ("build", "component"),
    [(lambda v: ClaimExtractor(RoutedProvider(careful_model), ExtractionConfig(prompt_version=v)), "extraction"),
     (lambda v: ClaimVerifier(RoutedProvider(careful_model), [DOCS["pods-fact-sheet"]], VerificationConfig(prompt_version=v)), "verification"),
     (lambda v: ClaimCorrector(RoutedProvider(careful_model), None, CorrectionConfig(prompt_version=v, recheck=False)), "correction")],
    ids=["extractor", "verifier", "corrector"],
)
def test_a_component_configured_with_a_missing_or_foreign_version_fails_at_construction(build, component):
    with pytest.raises(PromptNotFoundError):
        build(f"{loader.COMPONENTS[component]}-v404")
    foreign = "verify-claim-v1" if component != "verification" else "extract-claims-v1"
    with pytest.raises(PromptNotFoundError):
        build(foreign)


def test_a_configured_version_is_the_one_sent_and_recorded(prompt_dir):
    (prompt_dir / "verify-claim-v3.txt").write_text(verification.SYSTEM_PROMPT + "\n\nA draft sentence.\n", encoding="utf-8")
    provider = RoutedProvider(careful_model)
    config = PipelineConfig(verification=VerificationConfig(prompt_version="verify-claim-v3"))
    report = verify_request(request(SUPPORTED_CLAIM), provider, config)
    sent = [c.system for c in provider.calls if c.schema_name == "claim_verification"]
    assert sent and all(s.endswith("A draft sentence.") for s in sent)
    assert report.provenance.prompt_versions["verify_claim"] == "verify-claim-v3"


# --- The versions actually used are tracked, in the internal and the public report ---------------


def test_only_stages_that_sent_their_prompt_are_recorded():
    no_corrections = verify_request(request(CONTRADICTED_CLAIM), RoutedProvider(careful_model),
                                    PipelineConfig(correct_contradicted=False))
    assert no_corrections.provenance.prompt_versions == {"extract_claims": "extract-claims-v1", "verify_claim": "verify-claim-v1"}

    def opinions_only(call):
        return {"statements": [{"sentence_id": s["id"], "kind": "opinion", "claims": []}
                               for s in data_block(call, "content_json")["sentences"]]}

    nothing_to_check = verify_request(request("We think they sound amazing."), RoutedProvider(opinions_only))
    assert nothing_to_check.provenance.prompt_versions == {"extract_claims": "extract-claims-v1"}


def test_the_public_report_records_the_versions_actually_used():
    public = to_public_report(verify_request(request(), RoutedProvider(careful_model)))
    assert public.metadata.prompt_versions == {"extract_claims": "extract-claims-v1", "verify_claim": "verify-claim-v1",
                                               "correct_claim": "correct-claim-v1"}
    without = to_public_report(verify_request(request(CONTRADICTED_CLAIM), RoutedProvider(careful_model),
                                              PipelineConfig(correct_contradicted=False)), suggest_corrections=False)
    assert "correct_claim" not in without.metadata.prompt_versions


def test_the_public_report_refuses_an_unknown_stage():
    from pydantic import ValidationError

    from inkloom_verify.api_contract import ReportMetadata

    with pytest.raises(ValidationError):
        ReportMetadata(content_hash="a" * 64, prompt_versions={"summarise": "summarise-v1"})
