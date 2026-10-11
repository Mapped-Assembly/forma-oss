from __future__ import annotations

from pathlib import Path
import unittest

from forma_core.biology.liverbench import LiverBenchPredictions, load_liverbench, score_predictions
from forma_core.biology.liverbench_baselines import (
    DILIRANK_SEVERITY_POSITIVE_THRESHOLD,
    build_constant_negative_baseline,
    build_dilirank_severity_baseline,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "examples" / "biology" / "liverbench-v0.json"
REFERENCE_PREDICTIONS = ROOT / "examples" / "biology" / "liverbench-v0-dilirank-severity-baseline.json"


class LiverBenchBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = load_liverbench(DATASET)

    def test_dilirank_severity_mapping_is_fixed_and_label_independent(self) -> None:
        self.assertEqual(5, DILIRANK_SEVERITY_POSITIVE_THRESHOLD)
        bundle = build_dilirank_severity_baseline(self.dataset)
        prediction_lookup = {prediction.record_id: prediction for prediction in bundle.predictions}
        for record in self.dataset.records:
            with self.subTest(record=record.id):
                prediction = prediction_lookup[record.id]
                self.assertEqual(int(record.severity_class >= 5), prediction.predicted_label)
                self.assertAlmostEqual(record.severity_class / 8, prediction.score)

    def test_checked_in_prediction_bundle_matches_generator(self) -> None:
        checked_in = LiverBenchPredictions.model_validate_json(REFERENCE_PREDICTIONS.read_text())
        generated = build_dilirank_severity_baseline(self.dataset)
        self.assertEqual(generated, checked_in)

    def test_dilirank_severity_heldout_metrics_are_reproducible(self) -> None:
        result = score_predictions(
            self.dataset,
            build_dilirank_severity_baseline(self.dataset),
            "heldout",
        )
        self.assertTrue(result["complete"])
        metrics = result["metrics"]
        self.assertEqual({"tp": 2, "tn": 2, "fp": 1, "fn": 1}, metrics["confusion_matrix"])
        self.assertAlmostEqual(2 / 3, metrics["sensitivity"])
        self.assertAlmostEqual(2 / 3, metrics["specificity"])
        self.assertAlmostEqual(1 / 3, metrics["false_negative_rate"])
        self.assertAlmostEqual(2 / 3, metrics["accuracy"])
        self.assertAlmostEqual(2 / 3, metrics["balanced_accuracy"])
        self.assertAlmostEqual(8 / 9, metrics["auroc"])

        self.assertEqual(
            {"n": 2, "correct": 2, "accuracy": 1.0},
            result["cohort_accuracy"]["clear_positive"],
        )
        self.assertEqual(
            {"n": 2, "correct": 2, "accuracy": 1.0},
            result["cohort_accuracy"]["clear_negative"],
        )
        self.assertEqual(
            {"n": 1, "correct": 0, "accuracy": 0.0},
            result["cohort_accuracy"]["challenge_positive"],
        )
        self.assertEqual(
            {"n": 1, "correct": 0, "accuracy": 0.0},
            result["cohort_accuracy"]["challenge_negative"],
        )

    def test_dilirank_severity_errors_are_the_two_heldout_challenge_cases(self) -> None:
        bundle = build_dilirank_severity_baseline(self.dataset)
        prediction_lookup = {prediction.record_id: prediction for prediction in bundle.predictions}
        errors = {
            record.id
            for record in self.dataset.records
            if record.split == "heldout"
            and prediction_lookup[record.id].predicted_label != record.dilist_classification
        }
        self.assertEqual({"simvastatin", "zolpidem"}, errors)

    def test_constant_negative_is_a_half_balanced_accuracy_floor(self) -> None:
        result = score_predictions(
            self.dataset,
            build_constant_negative_baseline(self.dataset),
            "heldout",
        )
        metrics = result["metrics"]
        self.assertEqual(0.0, metrics["sensitivity"])
        self.assertEqual(1.0, metrics["specificity"])
        self.assertEqual(1.0, metrics["false_negative_rate"])
        self.assertEqual(0.5, metrics["accuracy"])
        self.assertEqual(0.5, metrics["balanced_accuracy"])
        self.assertEqual(0.5, metrics["auroc"])


if __name__ == "__main__":
    unittest.main()
