from __future__ import annotations

from pathlib import Path
import unittest

from forma_core.biology.liverbench import load_liverbench, score_predictions
from forma_core.biology.liverbench_independent import (
    FEATURE_FIELDS,
    K_NEIGHBORS,
    build_pubchem_knn_baseline,
    load_pubchem_descriptors,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "examples" / "biology" / "liverbench-v0.json"
DESCRIPTORS = ROOT / "examples" / "biology" / "liverbench-v0-pubchem-descriptors.json"


class LiverBenchIndependentBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = load_liverbench(DATASET)
        self.descriptors = load_pubchem_descriptors(DESCRIPTORS)

    def test_descriptor_manifest_has_full_liverbench_coverage(self) -> None:
        self.assertEqual(24, len(self.descriptors.records))
        self.assertEqual(
            {record.id for record in self.dataset.records},
            {record.record_id for record in self.descriptors.records},
        )
        self.assertEqual(
            ("molecular_weight", "xlogp", "hbond_donor_count", "hbond_acceptor_count", "tpsa"),
            FEATURE_FIELDS,
        )

    def test_descriptor_manifest_contains_no_dili_labels_or_dilirank_fields(self) -> None:
        payload = DESCRIPTORS.read_text().lower()
        self.assertNotIn("dilist_classification", payload)
        self.assertNotIn("severity_class", payload)
        self.assertNotIn("dilirank_concern", payload)

    def test_fixed_knn_generates_all_six_heldout_predictions(self) -> None:
        self.assertEqual(3, K_NEIGHBORS)
        bundle, details = build_pubchem_knn_baseline(self.dataset, self.descriptors)
        self.assertEqual(
            {
                "ketoconazole",
                "valproic-acid",
                "simvastatin",
                "indocyanine-green",
                "streptomycin",
                "zolpidem",
            },
            {prediction.record_id for prediction in bundle.predictions},
        )
        self.assertEqual(6, len(details))
        self.assertTrue(all(len(detail["neighbors"]) == 3 for detail in details))

    def test_heldout_metrics_are_reproducible(self) -> None:
        bundle, _ = build_pubchem_knn_baseline(self.dataset, self.descriptors)
        result = score_predictions(self.dataset, bundle, "heldout")
        self.assertTrue(result["complete"])
        metrics = result["metrics"]
        self.assertEqual({"tp": 3, "tn": 1, "fp": 2, "fn": 0}, metrics["confusion_matrix"])
        self.assertEqual(1.0, metrics["sensitivity"])
        self.assertAlmostEqual(1 / 3, metrics["specificity"])
        self.assertEqual(0.0, metrics["false_negative_rate"])
        self.assertAlmostEqual(2 / 3, metrics["accuracy"])
        self.assertAlmostEqual(2 / 3, metrics["balanced_accuracy"])
        self.assertEqual(0.5, metrics["auroc"])

    def test_heldout_predictions_are_fixed(self) -> None:
        bundle, _ = build_pubchem_knn_baseline(self.dataset, self.descriptors)
        prediction_lookup = {
            prediction.record_id: (prediction.predicted_label, prediction.score)
            for prediction in bundle.predictions
        }
        self.assertEqual((1, 2 / 3), prediction_lookup["ketoconazole"])
        self.assertEqual((1, 2 / 3), prediction_lookup["valproic-acid"])
        self.assertEqual((1, 2 / 3), prediction_lookup["simvastatin"])
        self.assertEqual((1, 1.0), prediction_lookup["indocyanine-green"])
        self.assertEqual((0, 0.0), prediction_lookup["streptomycin"])
        self.assertEqual((1, 2 / 3), prediction_lookup["zolpidem"])


if __name__ == "__main__":
    unittest.main()
