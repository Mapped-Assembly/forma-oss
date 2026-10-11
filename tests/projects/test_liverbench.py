from __future__ import annotations

from pathlib import Path
import unittest

from forma_core.biology.liverbench import (
    LiverBenchPredictions,
    build_reference_experiment,
    dataset_summary,
    evaluate_interface,
    load_liverbench,
    score_predictions,
)
from forma_core.biology.validation import validate_biological_experiment
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "examples" / "biology" / "liverbench-v0.json"
PROJECT = ROOT / "examples" / "organ-on-chip" / "two-channel.json"


class LiverBenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = load_liverbench(DATASET)
        self.project = HardwareIntermediateRepresentation.model_validate_json(PROJECT.read_text())

    def test_v0_manifest_is_balanced_and_split(self) -> None:
        summary = dataset_summary(self.dataset)
        self.assertEqual(24, summary["records"])
        self.assertEqual({"train": 12, "dev": 6, "heldout": 6}, summary["splits"])
        self.assertEqual({"dili_negative": 12, "dili_positive": 12}, summary["labels"])
        self.assertEqual(
            {
                "challenge_negative": 4,
                "challenge_positive": 4,
                "clear_negative": 8,
                "clear_positive": 8,
            },
            summary["cohorts"],
        )

    def test_heldout_is_balanced_and_contains_challenge_cases(self) -> None:
        heldout = [record for record in self.dataset.records if record.split == "heldout"]
        self.assertEqual(3, sum(record.dilist_classification == 1 for record in heldout))
        self.assertEqual(3, sum(record.dilist_classification == 0 for record in heldout))
        self.assertIn("challenge_positive", {record.cohort for record in heldout})
        self.assertIn("challenge_negative", {record.cohort for record in heldout})

    def test_every_record_builds_a_valid_biology_interface_case(self) -> None:
        self.assertIsNotNone(self.project.fluidic_system)
        for record in self.dataset.records:
            with self.subTest(record=record.id):
                experiment = build_reference_experiment(record, self.dataset)
                self.assertEqual([], experiment.exposures)
                self.assertEqual([], experiment.observations)
                self.assertEqual(2, len(experiment.reference_outcomes))
                self.assertEqual([], validate_biological_experiment(experiment, self.project.fluidic_system))

    def test_interface_evaluation_covers_all_24_records(self) -> None:
        result = evaluate_interface(self.dataset, self.project)
        self.assertTrue(result["passed"])
        self.assertEqual(24, result["cases"])
        self.assertEqual(24, result["cases_passed"])
        self.assertEqual([], result["fluidic_issues"])
        self.assertEqual([], result["case_failures"])

    def test_perfect_heldout_predictions_score_one(self) -> None:
        heldout = [record for record in self.dataset.records if record.split == "heldout"]
        bundle = LiverBenchPredictions.model_validate({
            "model_name": "unit-test-perfect",
            "predictions": [
                {
                    "record_id": record.id,
                    "predicted_label": record.dilist_classification,
                    "score": 0.9 if record.dilist_classification else 0.1,
                }
                for record in heldout
            ],
        })
        result = score_predictions(self.dataset, bundle, "heldout")
        self.assertTrue(result["complete"])
        self.assertEqual(1.0, result["metrics"]["sensitivity"])
        self.assertEqual(1.0, result["metrics"]["specificity"])
        self.assertEqual(0.0, result["metrics"]["false_negative_rate"])
        self.assertEqual(1.0, result["metrics"]["accuracy"])
        self.assertEqual(1.0, result["metrics"]["auroc"])

    def test_all_negative_predictions_surface_false_negative_rate(self) -> None:
        heldout = [record for record in self.dataset.records if record.split == "heldout"]
        bundle = LiverBenchPredictions.model_validate({
            "model_name": "unit-test-all-negative",
            "predictions": [
                {"record_id": record.id, "predicted_label": 0}
                for record in heldout
            ],
        })
        result = score_predictions(self.dataset, bundle, "heldout")
        self.assertTrue(result["complete"])
        self.assertEqual(0.0, result["metrics"]["sensitivity"])
        self.assertEqual(1.0, result["metrics"]["specificity"])
        self.assertEqual(1.0, result["metrics"]["false_negative_rate"])
        self.assertEqual(0.5, result["metrics"]["accuracy"])
        self.assertIsNone(result["metrics"]["auroc"])

    def test_missing_prediction_is_not_scored_as_complete(self) -> None:
        heldout = [record for record in self.dataset.records if record.split == "heldout"]
        bundle = LiverBenchPredictions.model_validate({
            "model_name": "unit-test-incomplete",
            "predictions": [
                {"record_id": record.id, "predicted_label": record.dilist_classification}
                for record in heldout[:-1]
            ],
        })
        result = score_predictions(self.dataset, bundle, "heldout")
        self.assertFalse(result["complete"])
        self.assertEqual([heldout[-1].id], result["missing_record_ids"])
        self.assertIsNone(result["metrics"])

    def test_unknown_prediction_record_is_rejected_from_complete_scoring(self) -> None:
        heldout = [record for record in self.dataset.records if record.split == "heldout"]
        predictions = [
            {"record_id": record.id, "predicted_label": record.dilist_classification}
            for record in heldout
        ]
        predictions.append({"record_id": "not-in-liverbench", "predicted_label": 1})
        bundle = LiverBenchPredictions.model_validate({
            "model_name": "unit-test-unknown",
            "predictions": predictions,
        })
        result = score_predictions(self.dataset, bundle, "heldout")
        self.assertFalse(result["complete"])
        self.assertEqual(["not-in-liverbench"], result["unknown_record_ids"])


if __name__ == "__main__":
    unittest.main()
