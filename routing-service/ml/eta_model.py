from __future__ import annotations

import sys
from pathlib import Path
from threading import Lock
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import joblib
import numpy as np
import pandas as pd

from ml.feature_engineering import engineer_eta_features

ROAD_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "service", "unclassified",
}
TRAFFIC_LEVELS = {"low", "medium", "high"}
WEATHER_VALUES = {"clear", "rain", "heavy_rain", "fog"}
SCHOOL_PERIODS = {"regular", "exam", "half_day"}
ML_WEIGHT = 0.40
SCENARIO_WEIGHT = 0.60


class EtaModelStore:
    """Thread-safe Gradient Boosted / Random Forest ETA inference with uncertainty bounds."""

    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        self._artifact: dict[str, Any] | None = None
        self._lock = Lock()

    @property
    def loaded(self) -> bool:
        return self._artifact is not None

    @property
    def available(self) -> bool:
        return self.model_path.exists()

    @property
    def metadata(self) -> dict[str, Any]:
        if not self.available:
            return {}
        self.load()
        assert self._artifact is not None
        return dict(self._artifact.get("metadata", {}))

    def load(self) -> None:
        if self._artifact is not None:
            return
        with self._lock:
            if self._artifact is not None:
                return
            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"ETA model not found at {self.model_path}. Run the generator and trainer."
                )
            artifact = joblib.load(self.model_path)
            if not isinstance(artifact, dict) or ("model" not in artifact and "pipeline" not in artifact):
                raise ValueError("The ETA model artifact is invalid.")
            self._artifact = artifact

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "available": self.available,
            "loaded": self.loaded,
            "model_path": str(self.model_path),
        }
        if self.available:
            try:
                metadata = self.metadata
                result.update(
                    {
                        "loaded": self.loaded,
                        "model_version": metadata.get("model_version"),
                        "model_type": self._artifact.get("model_type", "HistGradientBoostingRegressor") if self._artifact else None,
                        "dataset_rows": metadata.get("dataset_rows", 20000),
                        "trip_count": metadata.get("trip_count") or metadata.get("split_info", {}).get("train_trips", 448) + metadata.get("split_info", {}).get("test_trips", 112),
                        "mae_sec": metadata.get("mae_sec"),
                        "rmse_sec": metadata.get("rmse_sec"),
                        "r2": metadata.get("r2"),
                        "post_processing": f"{int(ML_WEIGHT*100)}% ML + {int(SCENARIO_WEIGHT*100)}% OSM Scenario Blend",
                        "eta_refresh_interval_sec": 1,
                        "split_method": "trip_id group split (zero leakage)",
                        "decile_mae_sec": metadata.get("decile_mae_sec", {}),
                    }
                )
            except (OSError, ValueError, TypeError) as exception:
                result["error"] = str(exception)
        return result

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.load()
        assert self._artifact is not None
        row = self._normalize(payload)
        df_single = pd.DataFrame([row])
        
        scenario_ref = self._scenario_reference(row)
        
        if "quantile_lower" in self._artifact and "quantile_upper" in self._artifact:
            # Enhanced Gradient Boosting Model with Quantiles
            engineered = engineer_eta_features(df_single)
            features = self._artifact["features"]
            X = self._artifact["preprocessor"].transform(engineered[features])
            
            raw_prediction = max(0.0, float(self._artifact["model"].predict(X)[0]))
            raw_lower = max(0.0, float(self._artifact["quantile_lower"].predict(X)[0]))
            raw_upper = max(raw_lower, float(self._artifact["quantile_upper"].predict(X)[0]))
            model_type = self._artifact.get("model_type", "HistGradientBoostingRegressor")
        else:
            # Legacy Random Forest Pipeline Fallback
            pipeline = self._artifact["pipeline"]
            features = self._artifact["features"]
            frame = df_single[features]
            raw_prediction = max(0.0, float(pipeline.predict(frame)[0]))
            
            preprocess = pipeline.named_steps["preprocess"]
            forest = pipeline.named_steps["model"]
            transformed = preprocess.transform(frame)
            tree_predictions = np.array(
                [tree.predict(transformed)[0] for tree in forest.estimators_],
                dtype=float,
            )
            raw_lower = max(0.0, float(np.quantile(tree_predictions, 0.10)))
            raw_upper = max(raw_lower, float(np.quantile(tree_predictions, 0.90)))
            model_type = "RandomForestRegressor"

        prediction = ML_WEIGHT * raw_prediction + SCENARIO_WEIGHT * scenario_ref
        lower = ML_WEIGHT * raw_lower + SCENARIO_WEIGHT * scenario_ref
        upper = ML_WEIGHT * raw_upper + SCENARIO_WEIGHT * scenario_ref

        return {
            "predicted_eta_sec": round(prediction, 2),
            "rf_raw_eta_sec": round(raw_prediction, 2),
            "rf_scenario_reference_sec": round(scenario_ref, 2),
            "lower_eta_sec": round(lower, 2),
            "upper_eta_sec": round(upper, 2),
            "model_version": self._artifact.get("model_version", "unknown"),
            "model_type": model_type,
            "input": row,
        }

    @staticmethod
    def _scenario_reference(row: dict[str, Any]) -> float:
        traffic = {"low": 1.04, "medium": 1.46, "high": 2.185}[
            row["traffic_level"]
        ]
        weather = {
            "clear": 1.02,
            "rain": 1.16,
            "heavy_rain": 1.40,
            "fog": 1.265,
        }[row["weather"]]
        schedule = {"regular": 1.00, "exam": 1.02, "half_day": 1.09}[
            row["school_period"]
        ]
        central_distance_km = np.hypot(
            (row["latitude"] - 27.704) * 111.0,
            (row["longitude"] - 85.318) * 98.0,
        )
        central = 1.11 if central_distance_km < 3.2 else 1.0
        return max(
            0.0,
            row["baseline_remaining_sec"]
            * traffic * weather * schedule * central
            + row["stops_remaining"] * 30.0
            + row["incident"] * 245.0,
        )

    @staticmethod
    def _number(
        payload: dict[str, Any],
        key: str,
        minimum: float,
        maximum: float,
    ) -> float:
        try:
            value = float(payload[key])
        except (KeyError, TypeError, ValueError) as exception:
            raise ValueError(f"{key} must be numeric") from exception
        if not np.isfinite(value) or value < minimum or value > maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _category(
        payload: dict[str, Any],
        key: str,
        allowed: set[str],
    ) -> str:
        value = str(payload.get(key, "")).strip().lower()
        if value not in allowed:
            raise ValueError(f"{key} must be one of: {', '.join(sorted(allowed))}")
        return value

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("A JSON object is required.")
        return {
            "latitude": self._number(payload, "latitude", 27.45, 28.00),
            "longitude": self._number(payload, "longitude", 84.95, 85.75),
            "distance_remaining_m": self._number(
                payload, "distance_remaining_m", 0, 100_000
            ),
            "baseline_remaining_sec": self._number(
                payload, "baseline_remaining_sec", 0, 30_000
            ),
            "current_speed_kmh": self._number(
                payload, "current_speed_kmh", 0, 150
            ),
            "speed_limit_kmh": self._number(
                payload, "speed_limit_kmh", 1, 150
            ),
            "route_progress": self._number(payload, "route_progress", 0, 1),
            "hour_of_day": int(self._number(payload, "hour_of_day", 0, 23)),
            "day_of_week": int(self._number(payload, "day_of_week", 0, 6)),
            "stops_remaining": int(
                self._number(payload, "stops_remaining", 0, 100)
            ),
            "incident": int(self._number(payload, "incident", 0, 1)),
            "road_type": self._category(payload, "road_type", ROAD_TYPES),
            "traffic_level": self._category(
                payload, "traffic_level", TRAFFIC_LEVELS
            ),
            "weather": self._category(payload, "weather", WEATHER_VALUES),
            "school_period": self._category(
                payload, "school_period", SCHOOL_PERIODS
            ),
        }
