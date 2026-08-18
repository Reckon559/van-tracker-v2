"""
Unit tests for Phase 2 Model Upgrades: Safety Classifier and Enhanced ETA Regressor.
"""
from pathlib import Path
import time
import unittest
import joblib
import numpy as np
import pandas as pd

from ml.train_anomaly_classifier import train_classifier
from ml.train_enhanced_eta import train_enhanced_eta
from ml.feature_engineering import engineer_anomaly_features, engineer_eta_features

BASE_DIR = Path(__file__).resolve().parents[1]
ANOMALY_DATASET = BASE_DIR / "data" / "kathmandu_anomaly_labeled.csv"
ANOMALY_MODEL_PATH = BASE_DIR / "models" / "safety_anomaly_classifier.joblib"
ANOMALY_METRICS_PATH = BASE_DIR / "models" / "safety_anomaly_metrics.json"

ETA_DATASET = BASE_DIR / "data" / "kathmandu_eta_synthetic.csv"
ETA_MODEL_PATH = BASE_DIR / "models" / "enhanced_eta_model.joblib"
ETA_METRICS_PATH = BASE_DIR / "models" / "enhanced_eta_metrics.json"


class ModelUpgradesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Train both models if not already generated
        if not ANOMALY_MODEL_PATH.exists():
            train_classifier(dataset_path=ANOMALY_DATASET, model_path=ANOMALY_MODEL_PATH, metrics_path=ANOMALY_METRICS_PATH, trees=100)
        if not ETA_MODEL_PATH.exists():
            train_enhanced_eta(dataset_path=ETA_DATASET, model_path=ETA_MODEL_PATH, metrics_path=ETA_METRICS_PATH, max_iter=120)

    def test_anomaly_classifier_artifact_and_performance(self):
        self.assertTrue(ANOMALY_MODEL_PATH.exists())
        artifact = joblib.load(ANOMALY_MODEL_PATH)
        
        self.assertIn("preprocessor", artifact)
        self.assertIn("model", artifact)
        self.assertIn("classes", artifact)
        self.assertEqual(artifact["classes"], ["monitor", "normal", "suspicious"])
        
        # Test inference latency on a sample batch
        sample_payload = pd.DataFrame([{
            "distance_from_route_m": 350.0,
            "deviation_duration_sec": 140.0,
            "heading_difference_deg": 65.0,
            "off_route_distance_m": 950.0,
            "returned_to_route": 0,
            "stop_duration_sec": 0.0,
            "current_speed_kmh": 28.0,
            "speed_limit_kmh": 40.0,
            "overspeed_duration_sec": 0.0,
            "location_context": "unknown",
        }])
        
        engineered = engineer_anomaly_features(sample_payload)
        X = artifact["preprocessor"].transform(engineered[artifact["features"]])
        
        # Warmup
        _ = artifact["model"].predict(X)
        _ = artifact["model"].predict_proba(X)
        
        start_time = time.perf_counter()
        for _ in range(5):
            pred = artifact["model"].predict(X)[0]
            probs = artifact["model"].predict_proba(X)[0]
        avg_latency_ms = ((time.perf_counter() - start_time) / 5.0) * 1000.0
        
        self.assertEqual(pred, "suspicious")
        self.assertAlmostEqual(float(np.sum(probs)), 1.0, places=4)
        self.assertLess(avg_latency_ms, 150.0, f"Average inference latency {avg_latency_ms:.2f}ms should be < 150ms")

    def test_enhanced_eta_artifact_and_quantiles(self):
        self.assertTrue(ETA_MODEL_PATH.exists())
        artifact = joblib.load(ETA_MODEL_PATH)
        
        self.assertIn("preprocessor", artifact)
        self.assertIn("model", artifact)
        self.assertIn("quantile_lower", artifact)
        self.assertIn("quantile_upper", artifact)
        
        sample_payload = pd.DataFrame([{
            "latitude": 27.735,
            "longitude": 85.302,
            "distance_remaining_m": 5000.0,
            "baseline_remaining_sec": 700.0,
            "current_speed_kmh": 25.0,
            "speed_limit_kmh": 40.0,
            "route_progress": 0.35,
            "stops_remaining": 4,
            "incident": 0,
            "hour_of_day": 8,
            "day_of_week": 1,
            "road_type": "primary",
            "traffic_level": "medium",
            "weather": "clear",
            "school_period": "regular",
        }])
        
        engineered = engineer_eta_features(sample_payload)
        X = artifact["preprocessor"].transform(engineered[artifact["features"]])
        
        # Warmup
        _ = artifact["model"].predict(X)
        _ = artifact["quantile_lower"].predict(X)
        _ = artifact["quantile_upper"].predict(X)
        
        start_time = time.perf_counter()
        for _ in range(5):
            pred = float(artifact["model"].predict(X)[0])
            lower = float(artifact["quantile_lower"].predict(X)[0])
            upper = float(artifact["quantile_upper"].predict(X)[0])
        avg_latency_ms = ((time.perf_counter() - start_time) / 5.0) * 1000.0
        
        self.assertGreater(pred, 0.0)
        self.assertLessEqual(lower, pred + 50.0)
        self.assertGreaterEqual(upper, pred - 50.0)
        self.assertLess(avg_latency_ms, 50.0, f"Average ETA inference latency {avg_latency_ms:.2f}ms should be < 50ms")


if __name__ == "__main__":
    unittest.main()
