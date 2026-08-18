"""
Trains a Cost-Sensitive Multi-Class Safety Classifier for Kathmandu School Vans.
Uses leak-free trip-level group splits and balanced class weighting.
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
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.preprocessing import OneHotEncoder, RobustScaler

from ml.feature_engineering import engineer_anomaly_features
from ml.split_utils import split_by_trip_group, summarize_split
DEFAULT_DATASET = BASE_DIR / "data" / "kathmandu_anomaly_labeled.csv"
DEFAULT_MODEL = BASE_DIR / "models" / "safety_anomaly_classifier.joblib"
DEFAULT_METRICS = BASE_DIR / "models" / "safety_anomaly_metrics.json"

RAW_NUMERIC_FEATURES = [
    "distance_from_route_m", "deviation_duration_sec", "heading_difference_deg",
    "off_route_distance_m", "returned_to_route", "stop_duration_sec",
    "current_speed_kmh", "speed_limit_kmh", "overspeed_duration_sec"
]
CATEGORICAL_FEATURES = ["location_context"]
TARGET = "label"


def train_classifier(
    dataset_path: Path = DEFAULT_DATASET,
    model_path: Path = DEFAULT_MODEL,
    metrics_path: Path = DEFAULT_METRICS,
    trees: int = 200,
    random_state: int = 42,
) -> dict:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found at {dataset_path}. Run generate_labeled_anomaly_data.py first.")
    
    raw_df = pd.read_csv(dataset_path)
    print(f"Loaded {len(raw_df):,} rows from {raw_df['trip_id'].nunique()} trips.")
    
    # 1. Feature Engineering
    df = engineer_anomaly_features(raw_df)
    engineered_numeric = RAW_NUMERIC_FEATURES + [
        "stop_excess_ratio", "stop_excess_sec",
        "deviation_spatial_rate", "heading_deviation_intensity",
        "overspeed_severity"
    ]
    features = engineered_numeric + CATEGORICAL_FEATURES
    
    # 2. Leak-Proof Split by trip_id
    train_df, test_df = split_by_trip_group(df, group_col="trip_id", test_size=0.20, random_state=random_state)
    split_info = summarize_split(train_df, test_df, group_col="trip_id")
    print(f"Group Split: {split_info['train_trips']} train trips ({split_info['train_rows']} rows) | "
          f"{split_info['test_trips']} test trips ({split_info['test_rows']} rows). Leakage: {split_info['leakage_count']}")
    
    # 3. Preprocessor Pipeline
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", RobustScaler(), engineered_numeric),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ]
    )
    
    X_train = preprocessor.fit_transform(train_df[features])
    y_train = train_df[TARGET]
    X_test = preprocessor.transform(test_df[features])
    y_test = test_df[TARGET]
    
    # 4. Train with Balanced Class Weights (penalizes misclassifying rare 'suspicious' and 'monitor' cases)
    class_weights = {"normal": 1.0, "monitor": 2.5, "suspicious": 6.0}
    
    clf = RandomForestClassifier(
        n_estimators=trees,
        max_depth=16,
        min_samples_leaf=2,
        class_weight=class_weights,
        n_jobs=1,
        random_state=random_state,
    )
    clf.fit(X_train, y_train)
    
    # 5. Evaluate on Held-out Independent Trips
    preds = clf.predict(X_test)
    probs = clf.predict_proba(X_test)
    classes = list(clf.classes_)
    
    cm = confusion_matrix(y_test, preds, labels=classes)
    report = classification_report(y_test, preds, labels=classes, output_dict=True)
    f1_macro = f1_score(y_test, preds, average="macro")
    
    print("\n=======================================================")
    print("CLASSIFICATION REPORT ON HELD-OUT INDEPENDENT TRIPS")
    print("=======================================================")
    print(classification_report(y_test, preds, labels=classes))
    print(f"Macro F1-Score: {f1_macro:.4f}")
    print("\nConfusion Matrix (Rows: Actual, Cols: Predicted):")
    for row_idx, cls_name in enumerate(classes):
        print(f"  {cls_name:12s}: {cm[row_idx]}")
    
    # Feature Importances
    transformed_feature_names = preprocessor.get_feature_names_out()
    importances = sorted(
        [{"feature": str(f), "importance": round(float(imp), 5)}
         for f, imp in zip(transformed_feature_names, clf.feature_importances_)],
        key=lambda x: x["importance"],
        reverse=True
    )[:12]
    
    # 6. Save Model Artifact and Metadata
    version = datetime.now(timezone.utc).strftime("anom-clf-%Y%m%d-%H%M%S")
    artifact = {
        "preprocessor": preprocessor,
        "model": clf,
        "features": features,
        "classes": classes,
        "model_version": version,
        "metadata": {
            "model_version": version,
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "f1_macro": round(f1_macro, 4),
            "classes": classes,
            "top_features": importances,
            "split_info": split_info,
        }
    }
    
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path, compress=3)
    
    metrics = {
        "model_version": version,
        "f1_macro": round(f1_macro, 4),
        "classes": classes,
        "confusion_matrix": cm.tolist(),
        "classification_report": report,
        "top_features": importances,
        "split_info": split_info,
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\nSaved model artifact to {model_path}")
    print(f"Saved metrics to {metrics_path}")
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Train the Kathmandu Safety Anomaly Classifier.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--trees", type=int, default=200)
    args = parser.parse_args()
    train_classifier(dataset_path=args.dataset, model_path=args.model, metrics_path=args.metrics, trees=args.trees)


if __name__ == "__main__":
    main()
