from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BASE_DIR / "data" / "kathmandu_eta_synthetic.csv"
DEFAULT_MODEL = BASE_DIR / "models" / "random_forest_eta.joblib"
DEFAULT_METADATA = BASE_DIR / "models" / "random_forest_eta_metrics.json"

NUMERIC_FEATURES = [
    "latitude",
    "longitude",
    "distance_remaining_m",
    "baseline_remaining_sec",
    "current_speed_kmh",
    "speed_limit_kmh",
    "route_progress",
    "hour_of_day",
    "day_of_week",
    "stops_remaining",
    "incident",
]
CATEGORICAL_FEATURES = [
    "road_type",
    "traffic_level",
    "weather",
    "school_period",
]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "actual_remaining_sec"
RF_WEIGHT = 0.40
SCENARIO_WEIGHT = 0.60


def scenario_reference(frame: pd.DataFrame) -> np.ndarray:
    """Deterministic OSM/scenario reference used to stabilize live RF ETA."""

    traffic = frame["traffic_level"].map(
        {"low": 1.04, "medium": 1.46, "high": 2.185}
    ).to_numpy(dtype=float)
    weather = frame["weather"].map(
        {"clear": 1.02, "rain": 1.16, "heavy_rain": 1.40, "fog": 1.265}
    ).to_numpy(dtype=float)
    schedule = frame["school_period"].map(
        {"regular": 1.00, "exam": 1.02, "half_day": 1.09}
    ).to_numpy(dtype=float)
    central_distance_km = np.hypot(
        (frame["latitude"].to_numpy(dtype=float) - 27.704) * 111.0,
        (frame["longitude"].to_numpy(dtype=float) - 85.318) * 98.0,
    )
    central = np.where(central_distance_km < 3.2, 1.11, 1.0)
    return (
        frame["baseline_remaining_sec"].to_numpy(dtype=float)
        * traffic * weather * schedule * central
        + frame["stops_remaining"].to_numpy(dtype=float) * 30.0
        + frame["incident"].to_numpy(dtype=float) * 245.0
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Kathmandu ETA Random Forest.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--trees", type=int, default=240)
    args = parser.parse_args()

    data = pd.read_csv(args.dataset)
    missing = [column for column in ["trip_id", *FEATURES, TARGET] if column not in data]
    if missing:
        raise ValueError(f"Dataset is missing columns: {', '.join(missing)}")
    if data["trip_id"].nunique() < 20:
        raise ValueError("At least 20 independent trips are required for a group split.")

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=42)
    train_index, test_index = next(
        splitter.split(data[FEATURES], data[TARGET], groups=data["trip_id"])
    )
    train = data.iloc[train_index]
    test = data.iloc[test_index]

    preprocessing = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", NUMERIC_FEATURES),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
        ]
    )
    regressor = RandomForestRegressor(
        n_estimators=args.trees,
        max_depth=20,
        min_samples_leaf=2,
        max_features=0.78,
        n_jobs=-1,
        random_state=42,
    )
    pipeline = Pipeline(
        [("preprocess", preprocessing), ("model", regressor)]
    )
    pipeline.fit(train[FEATURES], train[TARGET])
    raw_predictions = pipeline.predict(test[FEATURES])
    reference_predictions = scenario_reference(test)
    predictions = (
        RF_WEIGHT * raw_predictions
        + SCENARIO_WEIGHT * reference_predictions
    )

    mae = mean_absolute_error(test[TARGET], predictions)
    rmse = mean_squared_error(test[TARGET], predictions) ** 0.5
    r2 = r2_score(test[TARGET], predictions)
    raw_mae = mean_absolute_error(test[TARGET], raw_predictions)
    raw_rmse = mean_squared_error(test[TARGET], raw_predictions) ** 0.5
    raw_r2 = r2_score(test[TARGET], raw_predictions)
    version = datetime.now(timezone.utc).strftime(
        "rf-eta-%Y%m%d-%H%M%S-calibrated-v2"
    )

    transformed_names = pipeline.named_steps["preprocess"].get_feature_names_out()
    importances = pipeline.named_steps["model"].feature_importances_
    top_features = sorted(
        [
            {"feature": str(name), "importance": round(float(value), 6)}
            for name, value in zip(transformed_names, importances)
        ],
        key=lambda item: item["importance"],
        reverse=True,
    )[:15]
    metadata = {
        "model_version": version,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": args.dataset.name,
        "dataset_rows": int(len(data)),
        "trip_count": int(data["trip_id"].nunique()),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_trip_count": int(train["trip_id"].nunique()),
        "test_trip_count": int(test["trip_id"].nunique()),
        "split_method": "GroupShuffleSplit by trip_id (80/20)",
        "mae_sec": round(float(mae), 3),
        "rmse_sec": round(float(rmse), 3),
        "r2": round(float(r2), 5),
        "raw_rf_mae_sec": round(float(raw_mae), 3),
        "raw_rf_rmse_sec": round(float(raw_rmse), 3),
        "raw_rf_r2": round(float(raw_r2), 5),
        "post_processing": "40% Random Forest + 60% OSM scenario reference",
        "eta_refresh_interval_sec": 1,
        "features": FEATURES,
        "target": TARGET,
        "top_feature_importances": top_features,
        "data_scope": "Synthetic traffic scenarios grounded in Kathmandu OSM road attributes",
    }
    artifact = {
        "pipeline": pipeline,
        "model_version": version,
        "features": FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "metadata": metadata,
    }
    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.model, compress=3)
    args.metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
