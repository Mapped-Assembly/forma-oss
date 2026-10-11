from __future__ import annotations

from pathlib import Path
import unittest

from pydantic import ValidationError

from forma_core.biology import BiologicalExperiment, validate_biological_experiment
from forma_core.biology.benchmark import evaluate_biological_scenario
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

ROOT = Path(__file__).resolve().parents[2]
ORGAN_CHIP = ROOT / "examples" / "organ-on-chip"


class BiologicalExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.experiment = BiologicalExperiment.model_validate_json(
            (ORGAN_CHIP / "liver-dili-biological.json").read_text()
        )
        self.project = HardwareIntermediateRepresentation.model_validate_json(
            (ORGAN_CHIP / "two-channel.json").read_text()
        )

    def test_liver_dili_fixture_round_trips(self) -> None:
        self.assertEqual(
            self.experiment,
            BiologicalExperiment.model_validate_json(self.experiment.model_dump_json()),
        )
        self.assertEqual("Liver-on-chip", self.experiment.organ_model)
        self.assertEqual("vMost-DILI-concern", self.experiment.reference_outcomes[0].value)

    def test_liver_dili_fixture_links_to_existing_fluidic_system(self) -> None:
        self.assertIsNotNone(self.project.fluidic_system)
        self.assertEqual(
            [],
            validate_biological_experiment(self.experiment, self.project.fluidic_system),
        )

    def test_integrated_scenario_reports_physical_and_biological_validity(self) -> None:
        result = evaluate_biological_scenario(self.experiment, self.project)
        self.assertTrue(result["passed"])
        self.assertEqual([], result["fluidic_issues"])
        self.assertEqual([], result["biological_issues"])
        self.assertEqual(2, result["counts"]["compartments"])
        self.assertEqual(1, result["counts"]["reference_outcomes"])
        self.assertEqual({
            "toxicity_prediction": False,
            "biological_simulation": False,
            "clinical_safety_assessment": False,
        }, result["claims"])

    def test_missing_fluidic_context_is_explicit(self) -> None:
        issues = validate_biological_experiment(self.experiment)
        self.assertEqual(["fluidic_context_missing"], [issue.code for issue in issues])

    def test_unknown_fluidic_host_is_rejected(self) -> None:
        experiment = self.experiment.model_copy(deep=True)
        experiment.compartments[0].fluidic_component_ids = ["missing_channel"]
        issues = validate_biological_experiment(experiment, self.project.fluidic_system)
        self.assertEqual(["unknown_fluidic_component"], [issue.code for issue in issues])
        self.assertEqual("vascular_compartment", issues[0].entity_id)
        self.assertIn("missing_channel", issues[0].message)

    def test_unknown_internal_references_fail_schema_validation(self) -> None:
        payload = self.experiment.model_dump()
        payload["exposures"][0]["compartment_id"] = "missing_compartment"
        with self.assertRaisesRegex(ValidationError, "unknown compartment 'missing_compartment'"):
            BiologicalExperiment.model_validate(payload)

        payload = self.experiment.model_dump()
        payload["reference_outcomes"][0]["dataset_ref_id"] = "missing_dataset"
        with self.assertRaisesRegex(ValidationError, "unknown dataset 'missing_dataset'"):
            BiologicalExperiment.model_validate(payload)

    def test_duplicate_ids_fail_schema_validation(self) -> None:
        payload = self.experiment.model_dump()
        payload["endpoints"][0]["id"] = payload["compartments"][0]["id"]
        with self.assertRaisesRegex(ValidationError, "Duplicate biological ID"):
            BiologicalExperiment.model_validate(payload)

    def test_observation_requires_one_value_and_provenance(self) -> None:
        payload = self.experiment.model_dump()
        payload["observations"] = [{
            "id": "obs_1",
            "endpoint_id": "cell_viability",
            "compartment_id": "hepatic_compartment",
            "time_h": 24.0,
            "numeric_value": 0.8,
            "categorical_value": "decreased",
            "unit": "relative",
            "dataset_ref_id": "fda_dilirank_2",
            "source_record_id": "demo",
            "notes": None,
        }]
        with self.assertRaisesRegex(ValidationError, "exactly one numeric_value or categorical_value"):
            BiologicalExperiment.model_validate(payload)

        payload["observations"][0]["categorical_value"] = None
        payload["observations"][0]["dataset_ref_id"] = "missing_dataset"
        with self.assertRaisesRegex(ValidationError, "unknown dataset 'missing_dataset'"):
            BiologicalExperiment.model_validate(payload)

    def test_nonfinite_or_negative_exposure_values_are_rejected(self) -> None:
        for field, values in (
            ("concentration_value", (0, -1, float("nan"), float("inf"))),
            ("duration_h", (0, -1, float("nan"), float("inf"))),
            ("start_time_h", (-1, float("nan"), float("inf"))),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = self.experiment.model_dump()
                    payload["exposures"][0][field] = value
                    with self.assertRaises(ValidationError):
                        BiologicalExperiment.model_validate(payload)

    def test_schema_keeps_external_outcomes_separate_from_observations(self) -> None:
        schema = BiologicalExperiment.model_json_schema()
        self.assertIn("BiologicalObservation", schema["$defs"])
        self.assertIn("ReferenceOutcome", schema["$defs"])
        self.assertEqual([], self.experiment.observations)
        self.assertEqual(1, len(self.experiment.reference_outcomes))


if __name__ == "__main__":
    unittest.main()
