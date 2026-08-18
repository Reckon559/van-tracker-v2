from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BASE_DIR / "data" / "kathmandu_anomaly_normal.csv"
DEFAULT_MODEL = BASE_DIR / "models" / "isolation_forest_anomaly.joblib"
DEFAULT_METADATA = BASE_DIR / "models" / "isolation_forest_anomaly_metrics.json"
NUMERIC = [
    "distance_from_route_m", "deviation_duration_sec",
    "heading_difference_deg", "off_route_distance_m", "returned_to_route",
    "stop_duration_sec", "current_speed_kmh", "speed_limit_kmh",
    "overspeed_duration_sec",
]
CATEGORICAL = ["location_context"]
FEATURES = NUMERIC + CATEGORICAL


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Isolation Forest on normal behavior.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    args = parser.parse_args()

    data = pd.read_csv(args.dataset)
    preprocess = ColumnTransformer([
        ("numeric", RobustScaler(), NUMERIC),
        ("context", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
    ])
    forest = IsolationForest(
        n_estimators=220,
        max_samples=1024,
        contamination="auto",
        random_state=42,
        n_jobs=-1,
    )
    pipeline = Pipeline([("preprocess", preprocess), ("model", forest)])
    pipeline.fit(data[FEATURES])
    transformed = preprocess.transform(data[FEATURES])
    scores = forest.score_samples(transformed)
    suspicious_threshold = float(np.quantile(scores, 0.015))
    monitor_threshold = float(np.quantile(scores, 0.08))
    version = datetime.now(timezone.utc).strftime("if-behavior-%Y%m%d-%H%M%S")
    metadata = {
        "model_version": version,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_rows": int(len(data)),
        "training_data": "synthetic normal behavior by location context",
        "monitor_threshold": round(monitor_threshold, 6),
        "suspicious_threshold": round(suspicious_threshold, 6),
        "features": FEATURES,
        "output_classes": ["normal", "monitor", "suspicious"],
    }
    artifact = {
        "pipeline": pipeline,
        "features": FEATURES,
        "monitor_threshold": monitor_threshold,
        "suspicious_threshold": suspicious_threshold,
        "model_version": version,
        "metadata": metadata,
    }
    args.model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.model, compress=3)
    args.metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
