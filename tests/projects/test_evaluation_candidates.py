"""Checks that candidate screening cannot silently certify an independent cohort."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def auditor() -> ModuleType:
    """Load the standard-library audit script without installing script packages."""
    spec = importlib.util.spec_from_file_location("candidate_auditor", ROOT / "scripts/biology/audit_evaluation_candidates.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_changed_source_rejected(auditor: ModuleType, tmp_path: Path) -> None:
    """A changed upstream publication must not inherit the frozen audit version."""
    source = tmp_path / "source.xml"
    source.write_text("changed")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        auditor.audit_candidates(source, tmp_path / "unused1", tmp_path / "unused2")


def test_name_matching_does_not_guess_identity(auditor: ModuleType) -> None:
    """Case and whitespace match, while aliases and chemical forms remain unresolved."""
    assert auditor.normalize_name("  Valproic Acid ") == auditor.normalize_name("valproic acid")
    assert auditor.normalize_name("Sitax(s)entan") != auditor.normalize_name("Sitaxsentan")
    assert auditor.normalize_name("Diclofenac sodium") != auditor.normalize_name("Diclofenac")


def test_frozen_audit_tracks_current_prior_exposure() -> None:
    """Every previously used compound name is excluded, regardless of original split."""
    import hashlib

    audit = json.loads((ROOT / "examples/biology/liverchip-evaluation-candidates-v0.json").read_text())
    ewart_path = ROOT / "examples/biology/ewart-liverchip-v0.json"
    liverbench_path = ROOT / "examples/biology/liverbench-v0.json"
    known = {r["name"].strip().casefold() for r in json.loads(ewart_path.read_text())["compounds"]}
    known |= {r["compound_name"].strip().casefold() for r in json.loads(liverbench_path.read_text())["records"]}
    for record in audit["records"]:
        matched = record["source_name"].strip().casefold() in known
        assert (record["disposition"] == "exclude_prior_exposure") == matched
        assert not record["chemical_identity_verified"]
    assert audit["counts"] == {"source_compounds": 110, "name_matched_exclusions": 26,
                               "unresolved_candidates": 84, "admitted_external_test_compounds": 0}
    assert not any(audit["readiness"].values())
    for reference, path in zip(audit["prior_manifests"], (ewart_path, liverbench_path)):
        assert reference["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_refuses_input_overwrite(auditor: ModuleType, tmp_path: Path) -> None:
    """Reject input/output aliasing before reading or altering source data."""
    source = tmp_path / "source.xml"
    source.write_text("preserve")
    with pytest.raises(SystemExit) as error:
        auditor.main([str(source), "ewart.json", "liverbench.json", str(source)])
    assert error.value.code == 2
    assert source.read_text() == "preserve"
