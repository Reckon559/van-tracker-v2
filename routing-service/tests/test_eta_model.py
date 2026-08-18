from pathlib import Path
import unittest

from ml.eta_model import EtaModelStore

BASE_DIR = Path(__file__).resolve().parents[1]
ENHANCED_MODEL_PATH = BASE_DIR / "models" / "enhanced_eta_model.joblib"
LEGACY_MODEL_PATH = BASE_DIR / "models" / "random_forest_eta.joblib"
ACTIVE_MODEL_PATH = ENHANCED_MODEL_PATH if ENHANCED_MODEL_PATH.exists() else LEGACY_MODEL_PATH


class EtaModelTests(unittest.TestCase):
    def setUp(self):
        self.store = EtaModelStore(ACTIVE_MODEL_PATH)
        self.payload = {
            "latitude": 27.7354,
            "longitude": 85.3021,
            "distance_remaining_m": 6500,
            "baseline_remaining_sec": 900,
            "current_speed_kmh": 22,
            "speed_limit_kmh": 40,
            "route_progress": 0,
            "hour_of_day": 8,
            "day_of_week": 1,
            "stops_remaining": 4,
            "incident": 0,
            "road_type": "primary",
            "traffic_level": "high",
            "weather": "rain",
            "school_period": "regular",
        }

    def test_model_is_available_with_trip_group_metrics(self):
        health = self.store.health()
        self.assertTrue(health["available"])
        self.assertGreaterEqual(health["dataset_rows"], 20_000)
        self.assertIn("trip_id", health["split_method"])
        self.assertEqual(health["eta_refresh_interval_sec"], 1)
        self.assertTrue("40%" in health["post_processing"] and "60%" in health["post_processing"])

    def test_prediction_is_positive_and_has_interval(self):
        result = self.store.predict(self.payload)
        self.assertGreater(result["predicted_eta_sec"], 0)
        self.assertLessEqual(result["lower_eta_sec"], result["predicted_eta_sec"] + 50.0)
        self.assertGreaterEqual(result["upper_eta_sec"], result["predicted_eta_sec"] - 50.0)
        self.assertIn("rf_raw_eta_sec", result)
        self.assertIn("rf_scenario_reference_sec", result)

    def test_invalid_category_is_rejected(self):
        self.payload["traffic_level"] = "live"
        with self.assertRaises(ValueError):
            self.store.predict(self.payload)

    def test_rf_predicts_throughout_the_middle_of_a_trip(self):
        predictions = []
        for progress in [index / 20 for index in range(1, 20)]:
            self.payload["route_progress"] = progress
            self.payload["distance_remaining_m"] = 6500 * (1 - progress)
            self.payload["baseline_remaining_sec"] = 900 * (1 - progress)
            self.payload["stops_remaining"] = max(0, int(5 * (1 - progress)))
            result = self.store.predict(self.payload)
            predictions.append(result["predicted_eta_sec"])
        self.assertEqual(len(predictions), 19)
        self.assertTrue(all(value >= 0 for value in predictions))
        self.assertGreater(len(set(predictions)), 15)
        self.assertLess(predictions[-1], predictions[0])


if __name__ == "__main__":
    unittest.main()
