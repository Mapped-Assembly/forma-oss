"""Run the offline liver-chip engineering-to-evidence demonstration in one command.

Design generation uses the declared fixture builder, not an LLM. Repairs undo
known injected defects and are not an autonomous general-purpose repair model.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from forma_core.fluidics.benchmark import FluidicBenchmarkSpec, score_fluidic_system
from forma_core.fluidics.calculations import (
    average_velocity_mm_s, mean_wall_shear_stress_pa, pressure_drop_kpa,
    residence_time_s, reynolds_number,
)
from forma_core.fluidics.examples import organ_on_chip_system
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

from .ewart_liverchip import load_dataset
from .liverchip_evidence import build_evidence_experiment, build_evidence_report
from .models import BiologicalExperiment
from .liverbench import load_liverbench, score_predictions
from .liverbench_independent import build_pubchem_knn_baseline, load_pubchem_descriptors


def write_json(path: Path, payload: Any) -> None:
    """Write deterministic, finite JSON artifacts."""
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def run_demo(root: Path, output: Path, compound: str = "Troglitazone") -> dict[str, Any]:
    """Join fixture generation, fault checks, repair, flow perturbation and evidence."""
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new or empty output directory to preserve earlier run artifacts.")
    chip = root / "examples/organ-on-chip"
    dataset_path = root / "examples/biology/ewart-liverchip-v0.json"
    dataset = load_dataset(dataset_path)
    template = BiologicalExperiment.model_validate_json((chip / "liver-dili-biological.json").read_text())
    project = HardwareIntermediateRepresentation.model_validate_json((chip / "two-channel.json").read_text())
    project.fluidic_system = organ_on_chip_system()
    spec = FluidicBenchmarkSpec.model_validate_json((chip / "two-channel-spec.json").read_text())
    experiment = build_evidence_experiment(dataset, compound, template)
    evidence = build_evidence_report(dataset, experiment, project)
    reference = load_liverbench(root / "examples/biology/liverbench-v0.json")
    descriptors = load_pubchem_descriptors(root / "examples/biology/liverbench-v0-pubchem-descriptors.json")
    predictions, neighbors = build_pubchem_knn_baseline(reference, descriptors)
    molecular = {"scope": "Separate six-compound molecular baseline; not a prediction for the selected evidence compound or a chip model.",
        "predictions": predictions.model_dump(mode="json"), "evaluation": score_predictions(reference, predictions, "heldout"),
        "neighbors": neighbors}
    baseline = score_fluidic_system(project.fluidic_system, spec)
    original = project.fluidic_system.model_dump(mode="json")
    cases = []
    for fault in ("missing_outlet", "reversed_connection", "excessive_flow"):
        broken = deepcopy(original)
        target = next(c for c in broken["channels"] if c["id"] == "vascular_channel")
        if fault == "missing_outlet":
            broken["outlets"] = [o for o in broken["outlets"] if o["id"] != "vascular_waste"]
            correction = "Restore the required vascular waste outlet from the declared fixture."
        elif fault == "reversed_connection":
            target["source_id"], target["target_id"] = target["target_id"], target["source_id"]
            correction = "Restore the vascular channel direction: chamber to waste."
        else:
            target["target_flow_rate_ul_min"] = 90
            correction = "Restore the externally required vascular channel flow of 30 uL/min."
        detected = score_fluidic_system(broken, spec)
        repaired = deepcopy(broken)
        if fault == "missing_outlet":
            repaired["outlets"].append(deepcopy(next(o for o in original["outlets"] if o["id"] == "vascular_waste")))
        else:
            restored = next(c for c in repaired["channels"] if c["id"] == "vascular_channel")
            saved = next(c for c in original["channels"] if c["id"] == "vascular_channel")
            for key in (("source_id", "target_id") if fault == "reversed_connection" else ("target_flow_rate_ul_min",)):
                restored[key] = saved[key]
        verified = score_fluidic_system(repaired, spec)
        cases.append({"fault": fault, "detected": not detected.passed, "before": detected.model_dump(mode="json"),
            "correction": correction, "repair_method": "known-fault deterministic correction",
            "after": verified.model_dump(mode="json"), "broken_system": broken, "repaired_system": repaired})
    physics = []
    fluid = project.fluidic_system.fluids[0]
    for channel in project.fluidic_system.channels:
        if channel.id not in {"vascular_channel", "epithelial_channel"}:
            continue
        doubled = channel.model_copy(deep=True)
        doubled.target_flow_rate_ul_min *= 2
        base = {"velocity_mm_s": average_velocity_mm_s(channel), "residence_time_s": residence_time_s(channel),
            "pressure_drop_kpa": pressure_drop_kpa(channel, fluid), "reynolds_number": reynolds_number(channel, fluid),
            "mean_wall_shear_pa": mean_wall_shear_stress_pa(channel, fluid)}
        ratios = {"velocity": average_velocity_mm_s(doubled) / base["velocity_mm_s"],
            "residence_time": residence_time_s(doubled) / base["residence_time_s"],
            "pressure_drop": pressure_drop_kpa(doubled, fluid) / base["pressure_drop_kpa"]}
        expected = {"velocity": 2.0, "residence_time": 0.5, "pressure_drop": 2.0}
        physics.append({"channel_id": channel.id, "base": base, "doubled_flow_ratios": ratios,
            "expected_ratios": expected, "passed": all(math.isclose(ratios[k], v, rel_tol=1e-10) for k, v in expected.items())})
    passed = molecular["evaluation"]["complete"] and baseline.passed and evidence["validation"]["passed"] and all(
        c["detected"] and c["after"]["passed"] for c in cases) and all(p["passed"] for p in physics)
    result = {"demo": "Liver-chip engineering and published evidence", "version": "0.1", "passed": passed,
        "generation_mode": "deterministic_fixture_builder", "compound": evidence["compound"],
        "baseline": baseline.model_dump(mode="json"), "fault_cases": cases, "flow_perturbations": physics,
        "evidence_summary": {k: evidence["evidence"][k] for k in ("status", "source_rows", "measured_values", "missing_values")},
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "claims": {"live_llm_generation": False, "general_autonomous_repair": False,
            "biological_digital_twin": False, "new_toxicity_predictor": False, "physical_chip_tested": False},
        "limitations": ["Fixture geometry, fluid properties and operating limits are illustrative inputs.",
            "Doubling-flow check is a channel calculation, not a new validated whole-system operating point.",
            "Fault cases are three deliberate software defects, not a held-out real-world benchmark.",
            "External published observations are not measurements generated by this design."]}
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "design.json", project.model_dump(mode="json"))
    write_json(output / "requirements.json", spec.model_dump(mode="json"))
    write_json(output / "experiment.json", experiment.model_dump(mode="json"))
    write_json(output / "evidence.json", evidence)
    write_json(output / "run.json", result)
    write_json(output / "molecular-baseline.json", molecular)
    report = ["# Liver-chip end-to-end demo", "", f"Run result: {'PASS' if passed else 'FAIL'}", "",
        "Scope: deterministic engineering fixture → validation → known-fault repair → analytical flow perturbation → published drug evidence.",
        "", f"Compound: **{evidence['compound']['name']}**", "", "## Engineering checks", "",
        f"Initial design passes: {baseline.passed}", "", "| Injected fault | Detected | Repair passes |", "|---|---|---|"]
    report.extend(f"| {c['fault']} | {c['detected']} | {c['after']['passed']} |" for c in cases)
    report += ["", "## Flow perturbation", "", "| Channel | Velocity ratio | Pressure-drop ratio | Residence-time ratio |", "|---|---:|---:|---:|"]
    report.extend(f"| {p['channel_id']} | {p['doubled_flow_ratios']['velocity']:.2f} | {p['doubled_flow_ratios']['pressure_drop']:.2f} | {p['doubled_flow_ratios']['residence_time']:.2f} |" for p in physics)
    summary = result["evidence_summary"]
    report += ["", "## Published evidence", "", f"{summary['source_rows']} source rows: {summary['measured_values']} measured values and {summary['missing_values']} missing results. Status: {summary['status']}.",
        "", "See evidence.json for doses, units, source hashes, row references, descriptive means and SEM.",
        "", "## Separate molecular baseline", "", "The run also executes the existing PubChem 3-NN comparator on its six-compound heldout slice. See molecular-baseline.json. This is not a prediction for the selected evidence compound, and its performance must not be attributed to the chip.", "", "## Limits", "", "This run does not call an LLM, simulate injury, train a toxicity model, or test a physical chip. Repairs target known injected faults. The separate molecular baseline is not a chip predictor.",
        "", "## Artifacts", "", "design.json, requirements.json, experiment.json, evidence.json, molecular-baseline.json, run.json.", ""]
    (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    """Run from a repository checkout without API keys or paid services."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compound", default="Troglitazone")
    args = parser.parse_args(argv)
    try:
        result = run_demo(args.repo_root, args.output, args.compound)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"passed": result["passed"], "output": str(args.output),
        "faults_detected": sum(c["detected"] for c in result["fault_cases"]),
        "repairs_passed": sum(c["after"]["passed"] for c in result["fault_cases"]),
        "evidence": result["evidence_summary"]}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
