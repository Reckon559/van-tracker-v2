"""
Unit tests for feature engineering, group-splitting, and dataset validation.
"""
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

from ml.feature_engineering import (
    add_cyclic_time_features,
    engineer_eta_features,
    engineer_anomaly_features,
)
from ml.split_utils import (
    split_by_trip_group,
    stratified_group_kfold_split,
    summarize_split,
)
from ml.generate_labeled_anomaly_data import generate_labeled_trips


class DatasetValidationTests(unittest.TestCase):
    def setUp(self):
        self.sample_eta_df = pd.DataFrame([
            {
                "trip_id": 1,
                "latitude": 27.735,
                "longitude": 85.302,
                "distance_remaining_m": 4500.0,
                "baseline_remaining_sec": 600.0,
                "current_speed_kmh": 25.0,
                "speed_limit_kmh": 40.0,
                "route_progress": 0.45,
                "hour_of_day": 8,
                "day_of_week": 1,
                "stops_remaining": 3,
                "road_type": "primary",
                "traffic_level": "medium",
                "weather": "clear",
                "school_period": "regular",
                "incident": 0,
                "actual_remaining_sec": 720.0,
            },
            {
                "trip_id": 2,
                "latitude": 27.705,
                "longitude": 85.318,
                "distance_remaining_m": 1200.0,
                "baseline_remaining_sec": 180.0,
                "current_speed_kmh": 15.0,
                "speed_limit_kmh": 30.0,
                "route_progress": 0.85,
                "hour_of_day": 15,
                "day_of_week": 3,
                "stops_remaining": 1,
                "road_type": "secondary",
                "traffic_level": "high",
                "weather": "rain",
                "school_period": "regular",
                "incident": 0,
                "actual_remaining_sec": 240.0,
            }
        ])

    def test_cyclic_time_features_mathematical_identity(self):
        df = add_cyclic_time_features(self.sample_eta_df)
        self.assertIn("hour_sin", df.columns)
        self.assertIn("hour_cos", df.columns)
        self.assertIn("day_sin", df.columns)
        self.assertIn("day_cos", df.columns)
        
        # Verify sin^2 + cos^2 = 1
        hour_trig_sum = df["hour_sin"] ** 2 + df["hour_cos"] ** 2
        day_trig_sum = df["day_sin"] ** 2 + df["day_cos"] ** 2
        np.testing.assert_allclose(hour_trig_sum, 1.0, atol=1e-5)
        np.testing.assert_allclose(day_trig_sum, 1.0, atol=1e-5)

    def test_eta_feature_engineering_bounds(self):
        df = engineer_eta_features(self.sample_eta_df)
        self.assertIn("stop_density_per_km", df.columns)
        self.assertIn("speed_ratio", df.columns)
        self.assertIn("congestion_factor", df.columns)
        self.assertIn("dist_to_ktm_core_km", df.columns)
        self.assertIn("is_core_urban", df.columns)
        
        # Check finite and non-negative values
        self.assertTrue((df["stop_density_per_km"] >= 0).all())
        self.assertTrue((df["speed_ratio"] >= 0).all())
        self.assertTrue((df["congestion_factor"] >= 0.3).all())
        self.assertTrue((df["dist_to_ktm_core_km"] >= 0).all())
        self.assertIn(df.loc[1, "is_core_urban"], [0.0, 1.0])

    def test_anomaly_feature_engineering_bounds(self):
        sample_anom = pd.DataFrame([
            {
                "location_context": "traffic_light",
                "stop_duration_sec": 95.0,  # 20s over 75s limit
                "off_route_distance_m": 120.0,
                "deviation_duration_sec": 30.0,
                "heading_difference_deg": 45.0,
                "distance_from_route_m": 80.0,
                "current_speed_kmh": 48.0,
                "speed_limit_kmh": 40.0,
                "overspeed_duration_sec": 12.0,
            }
        ])
        df = engineer_anomaly_features(sample_anom)
        self.assertIn("stop_excess_ratio", df.columns)
        self.assertIn("deviation_spatial_rate", df.columns)
        self.assertIn("heading_deviation_intensity", df.columns)
        self.assertIn("overspeed_severity", df.columns)
        
        self.assertAlmostEqual(df.loc[0, "stop_excess_sec"], 20.0, places=2)
        self.assertAlmostEqual(df.loc[0, "deviation_spatial_rate"], 4.0, places=2)
        self.assertGreater(df.loc[0, "overspeed_severity"], 0.0)

    def test_zero_leakage_in_trip_group_split(self):
        # Generate dummy 20 trips with 10 rows each
        records = []
        for t in range(20):
            for r in range(10):
                records.append({"trip_id": f"T_{t}", "val": np.random.randn()})
        df = pd.DataFrame(records)
        
        train_df, test_df = split_by_trip_group(df, group_col="trip_id", test_size=0.25, random_state=42)
        summary = summarize_split(train_df, test_df, group_col="trip_id")
        
        self.assertEqual(summary["leakage_count"], 0)
        self.assertEqual(summary["train_trips"], 15)
        self.assertEqual(summary["test_trips"], 5)
        self.assertEqual(summary["train_rows"], 150)
        self.assertEqual(summary["test_rows"], 50)

    def test_labeled_anomaly_dataset_generation(self):
        trips = generate_labeled_trips(num_trips=25, min_steps=10, max_steps=15, seed=42)
        df = pd.DataFrame(trips)
        
        self.assertGreater(len(df), 250)
        self.assertIn("label", df.columns)
        self.assertIn("trip_id", df.columns)
        self.assertIn("location_context", df.columns)
        
        # Verify all 3 classes exist
        labels = set(df["label"].unique())
        self.assertTrue({"normal", "monitor", "suspicious"}.issubset(labels))
        
        # Verify speeds and durations are physical and finite
        self.assertTrue((df["current_speed_kmh"] >= 0).all())
        self.assertTrue((df["current_speed_kmh"] <= 120).all())
        self.assertTrue((df["stop_duration_sec"] >= 0).all())
        self.assertTrue((df["heading_difference_deg"] >= 0).all())
        self.assertTrue((df["heading_difference_deg"] <= 180).all())


if __name__ == "__main__":
    unittest.main()
