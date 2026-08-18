"""
Trains an Enhanced Gradient Boosted ETA Regressor for Kathmandu School Vans.
Includes cyclic time features, stop density, dynamic speed ratio, and uncertainty quantiles.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import OneHotEncoder

from ml.feature_engineering import engineer_eta_features
from ml.split_utils import split_by_trip_group, summarize_split
DEFAULT_DATASET = BASE_DIR / "data" / "kathmandu_eta_synthetic.csv"
DEFAULT_MODEL = BASE_DIR / "models" / "enhanced_eta_model.joblib"
DEFAULT_METRICS = BASE_DIR / "models" / "enhanced_eta_metrics.json"

RAW_NUMERIC = [
    "latitude", "longitude", "distance_remaining_m", "baseline_remaining_sec",
    "current_speed_kmh", "speed_limit_kmh", "route_progress",
    "stops_remaining", "incident"
]
CATEGORICAL = ["road_type", "traffic_level", "weather", "school_period"]
TARGET = "actual_remaining_sec"


def train_enhanced_eta(
    dataset_path: Path = DEFAULT_DATASET,
    model_path: Path = DEFAULT_MODEL,
    metrics_path: Path = DEFAULT_METRICS,
    learning_rate: float = 0.05,
    max_iter: int = 300,
    random_state: int = 42,
) -> dict:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found at {dataset_path}. Run generate_synthetic_eta_data.py first.")

    raw_df = pd.read_csv(dataset_path)
    print(f"Loaded {len(raw_df):,} rows from {raw_df['trip_id'].nunique()} trips.")

    # 1. Feature Engineering
    df = engineer_eta_features(raw_df)
    engineered_numeric = RAW_NUMERIC + [
        "hour_sin", "hour_cos", "day_sin", "day_cos",
        "stop_density_per_km", "speed_ratio", "congestion_factor",
        "dist_to_ktm_core_km", "is_core_urban", "progress_squared"
    ]
    features = engineered_numeric + CATEGORICAL

    # 2. Leak-Proof Split by trip_id
    train_df, test_df = split_by_trip_group(df, group_col="trip_id", test_size=0.20, random_state=random_state)
    split_info = summarize_split(train_df, test_df, group_col="trip_id")
    print(f"Group Split: {split_info['train_trips']} train trips ({split_info['train_rows']} rows) | "
          f"{split_info['test_trips']} test trips ({split_info['test_rows']} rows). Leakage: {split_info['leakage_count']}")

    # 3. Preprocessor Pipeline
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", engineered_numeric),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ]
    )

    X_train = preprocessor.fit_transform(train_df[features])
    y_train = train_df[TARGET]
    X_test = preprocessor.transform(test_df[features])
    y_test = test_df[TARGET]

    # 4. Train Central Estimator (HistGradientBoostingRegressor - fast and accurate)
    print("Training Central Estimator...")
    regressor = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=learning_rate,
        max_iter=max_iter,
        max_depth=12,
        min_samples_leaf=15,
        l2_regularization=0.8,
        random_state=random_state,
    )
    regressor.fit(X_train, y_train)

    # 5. Train Lower (10th percentile) and Upper (90th percentile) Quantile Regressors for Uncertainty Intervals
    print("Training 10th and 90th percentile Uncertainty Quantile Estimators...")
    q_lower = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.10,
        learning_rate=learning_rate,
        max_iter=160,
        max_depth=8,
        min_samples_leaf=15,
        random_state=random_state,
    )
    q_upper = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.90,
        learning_rate=learning_rate,
        max_iter=160,
        max_depth=8,
        min_samples_leaf=15,
        random_state=random_state,
    )
    q_lower.fit(X_train, y_train)
    q_upper.fit(X_train, y_train)

    # 6. Evaluation on Held-out Independent Trips
    preds = np.maximum(0.0, regressor.predict(X_test))
    lower_preds = np.maximum(0.0, q_lower.predict(X_test))
    upper_preds = np.maximum(lower_preds, q_upper.predict(X_test))

    mae = mean_absolute_error(y_test, preds)
    rmse = mean_squared_error(y_test, preds) ** 0.5
    r2 = r2_score(y_test, preds)

    # Decile Error Analysis (Performance by trip stage)
    progress_deciles = pd.cut(test_df["route_progress"], bins=np.linspace(0, 1, 6), labels=["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"])
    errors = np.abs(y_test - preds)
    decile_mae = errors.groupby(progress_deciles, observed=True).mean().to_dict()

    print("\n=======================================================")
    print("ENHANCED ETA REGRESSION ON HELD-OUT INDEPENDENT TRIPS")
    print("=======================================================")
    print(f"Mean Absolute Error (MAE): {mae:.2f} seconds ({mae/60:.2f} minutes)")
    print(f"Root Mean Squared Error (RMSE): {rmse:.2f} seconds ({rmse/60:.2f} minutes)")
    print(f"R² Score: {r2:.4f}")
    print("\nMAE by Trip Progress Stage:")
    for stage, err in decile_mae.items():
        print(f"  Stage {stage:8s}: {err:.2f}s ({err/60:.2f} min)")

    # 7. Save Model Artifact and Metadata
    version = datetime.now(timezone.utc).strftime("hgb-eta-%Y%m%d-%H%M%S")
    artifact = {
        "preprocessor": preprocessor,
        "model": regressor,
        "quantile_lower": q_lower,
        "quantile_upper": q_upper,
        "features": features,
        "raw_numeric_features": RAW_NUMERIC,
        "categorical_features": CATEGORICAL,
        "model_version": version,
        "model_type": "HistGradientBoostingRegressor",
        "metadata": {
            "model_version": version,
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "mae_sec": round(mae, 2),
            "rmse_sec": round(rmse, 2),
            "r2": round(r2, 4),
            "decile_mae_sec": {k: round(v, 2) for k, v in decile_mae.items()},
            "split_info": split_info,
        }
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path, compress=3)

    metrics = {
        "model_version": version,
        "mae_sec": round(mae, 2),
        "rmse_sec": round(rmse, 2),
        "r2": round(r2, 4),
        "decile_mae_sec": {k: round(v, 2) for k, v in decile_mae.items()},
        "split_info": split_info,
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\nSaved model artifact to {model_path}")
    print(f"Saved metrics to {metrics_path}")
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Train Enhanced Kathmandu ETA Regressor.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--max_iter", type=int, default=300)
    args = parser.parse_args()
    train_enhanced_eta(
        dataset_path=args.dataset,
        model_path=args.model,
        metrics_path=args.metrics,
        learning_rate=args.lr,
        max_iter=args.max_iter,
    )


if __name__ == "__main__":
    main()
