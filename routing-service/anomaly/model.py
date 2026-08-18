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

from ml.feature_engineering import engineer_anomaly_features

LOCATION_CONTEXTS = {"bus_stop", "traffic_light", "school", "depot", "unknown"}


class AnomalyModelStore:
    """Multi-Class Safety Classifier & Isolation Forest model store; it never chooses alert recipients."""

    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        self._artifact: dict[str, Any] | None = None
        self._lock = Lock()

    @property
    def available(self) -> bool:
        return self.model_path.exists()

    @property
    def loaded(self) -> bool:
        return self._artifact is not None

    def load(self) -> None:
        if self._artifact is not None:
            return
        with self._lock:
            if self._artifact is not None:
                return
            if not self.model_path.exists():
                raise FileNotFoundError(f"Anomaly model not found at {self.model_path}")
            artifact = joblib.load(self.model_path)
            if not isinstance(artifact, dict) or ("model" not in artifact and "pipeline" not in artifact):
                raise ValueError("Invalid Anomaly model artifact")
            self._artifact = artifact

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "available": self.available,
            "loaded": self.loaded,
            "model_path": str(self.model_path),
        }
        if self.available:
            try:
                self.load()
                assert self._artifact is not None
                metadata = self._artifact.get("metadata", {})
                result.update(metadata)
                result["model_type"] = "CostSensitiveSafetyClassifier" if "classes" in self._artifact else "IsolationForest"
                result["loaded"] = True
            except (OSError, TypeError, ValueError) as exception:
                result["error"] = str(exception)
        return result

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.load()
        assert self._artifact is not None
        row = self._normalize(payload)
        df_single = pd.DataFrame([row])
        
        if "classes" in self._artifact:
            # Multi-Class Cost-Sensitive Safety Classifier
            engineered = engineer_anomaly_features(df_single)
            features = self._artifact["features"]
            X = self._artifact["preprocessor"].transform(engineered[features])
            status = str(self._artifact["model"].predict(X)[0])
            probs = self._artifact["model"].predict_proba(X)[0]
            classes = self._artifact["classes"]
            
            # Anomaly confidence score: 1.0 - P(normal)
            normal_idx = classes.index("normal") if "normal" in classes else -1
            score = 1.0 - float(probs[normal_idx]) if normal_idx >= 0 else 0.0
            
            return {
                "status": status,
                "score": round(score, 6),
                "monitor_threshold": 0.20,
                "suspicious_threshold": 0.70,
                "model_version": self._artifact.get("model_version", "unknown"),
                "model_type": "CostSensitiveSafetyClassifier",
                "probabilities": {cls: round(float(p), 4) for cls, p in zip(classes, probs)},
            }
        else:
            # Legacy Isolation Forest Fallback
            frame = df_single[self._artifact["features"]]
            pipeline = self._artifact["pipeline"]
            transformed = pipeline.named_steps["preprocess"].transform(frame)
            score = float(pipeline.named_steps["model"].score_samples(transformed)[0])
            monitor_threshold = float(self._artifact["monitor_threshold"])
            suspicious_threshold = float(self._artifact["suspicious_threshold"])
            if score < suspicious_threshold:
                status = "suspicious"
            elif score < monitor_threshold:
                status = "monitor"
            else:
                status = "normal"
            return {
                "status": status,
                "score": round(score, 6),
                "monitor_threshold": round(monitor_threshold, 6),
                "suspicious_threshold": round(suspicious_threshold, 6),
                "model_version": self._artifact.get("model_version", "unknown"),
                "model_type": "IsolationForest",
            }

    @staticmethod
    def _number(payload: dict[str, Any], key: str, low: float, high: float) -> float:
        try:
            value = float(payload.get(key, 0))
        except (TypeError, ValueError) as exception:
            raise ValueError(f"{key} must be numeric") from exception
        if not np.isfinite(value) or value < low or value > high:
            raise ValueError(f"{key} must be between {low} and {high}")
        return value

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = str(payload.get("location_context", "unknown")).lower()
        if context not in LOCATION_CONTEXTS:
            raise ValueError("location_context is invalid")
        return {
            "distance_from_route_m": self._number(payload, "distance_from_route_m", 0, 10_000),
            "deviation_duration_sec": self._number(payload, "deviation_duration_sec", 0, 86_400),
            "heading_difference_deg": self._number(payload, "heading_difference_deg", 0, 180),
            "off_route_distance_m": self._number(payload, "off_route_distance_m", 0, 100_000),
            "returned_to_route": int(self._number(payload, "returned_to_route", 0, 1)),
            "stop_duration_sec": self._number(payload, "stop_duration_sec", 0, 86_400),
            "current_speed_kmh": self._number(payload, "current_speed_kmh", 0, 150),
            "speed_limit_kmh": self._number(payload, "speed_limit_kmh", 1, 150),
            "overspeed_duration_sec": self._number(payload, "overspeed_duration_sec", 0, 86_400),
            "location_context": context,
        }
