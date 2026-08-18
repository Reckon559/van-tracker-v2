from pathlib import Path
import unittest

from anomaly.decision import decide
from anomaly.model import AnomalyModelStore

BASE_DIR = Path(__file__).resolve().parents[1]
ENHANCED_ANOMALY_PATH = BASE_DIR / "models" / "safety_anomaly_classifier.joblib"
LEGACY_ANOMALY_PATH = BASE_DIR / "models" / "isolation_forest_anomaly.joblib"
ACTIVE_ANOMALY_PATH = ENHANCED_ANOMALY_PATH if ENHANCED_ANOMALY_PATH.exists() else LEGACY_ANOMALY_PATH


def normal_features():
    return {
        "distance_from_route_m": 4,
        "deviation_duration_sec": 0,
        "heading_difference_deg": 3,
        "off_route_distance_m": 0,
        "returned_to_route": 0,
        "stop_duration_sec": 20,
        "current_speed_kmh": 24,
        "speed_limit_kmh": 40,
        "overspeed_duration_sec": 0,
        "location_context": "traffic_light",
        "deviation_active": False,
        "is_emergency": False,
    }


class AnomalyTests(unittest.TestCase):
    def test_model_returns_three_level_classification(self):
        result = AnomalyModelStore(ACTIVE_ANOMALY_PATH).evaluate(normal_features())
        self.assertIn(result["status"], {"normal", "monitor", "suspicious"})

    def test_temporary_deviation_does_not_alert_parent(self):
        features = normal_features()
        features.update({
            "deviation_active": True,
            "distance_from_route_m": 100,
            "deviation_duration_sec": 20,
            "off_route_distance_m": 80,
        })
        result = decide(features, "monitor")
        route = next(item for item in result["decisions"] if item["type"] == "route_deviation")
        self.assertFalse(route["notify_parent"])
        self.assertEqual(route["status"], "monitor")

    def test_severe_deviation_requires_isolation_forest_evidence(self):
        features = normal_features()
        features.update({
            "deviation_active": True,
            "distance_from_route_m": 40,
            "max_distance_from_route_m": 300,
            "deviation_duration_sec": 130,
            "off_route_distance_m": 1500,
        })
        without_evidence = decide(features, "monitor")
        with_evidence = decide(features, "suspicious")
        self.assertFalse(any(item["notify_parent"] for item in without_evidence["decisions"]))
        self.assertTrue(any(item["notify_parent"] for item in with_evidence["decisions"]))

    def test_stop_threshold_depends_on_location(self):
        bus_stop = normal_features()
        bus_stop.update({"location_context": "bus_stop", "stop_duration_sec": 180})
        traffic_light = dict(bus_stop, location_context="traffic_light")
        self.assertFalse(any(item["alert"] for item in decide(bus_stop, "normal")["decisions"]))
        self.assertTrue(any(item["notify_staff"] for item in decide(traffic_light, "suspicious")["decisions"]))

    def test_emergency_and_overspeed_are_parent_rules(self):
        emergency = normal_features()
        emergency["is_emergency"] = True
        speed = normal_features()
        speed.update({"current_speed_kmh": 55, "overspeed_duration_sec": 1})
        self.assertTrue(any(item["notify_parent"] for item in decide(emergency, "normal")["decisions"]))
        self.assertTrue(any(item["notify_parent"] for item in decide(speed, "normal")["decisions"]))


if __name__ == "__main__":
    unittest.main()
