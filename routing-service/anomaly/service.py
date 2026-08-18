from __future__ import annotations

from pathlib import Path
from typing import Any

from .decision import decide
from .model import AnomalyModelStore


class HybridAnomalyService:
    def __init__(self, model_path: str | Path):
        self.model = AnomalyModelStore(model_path)

    def health(self) -> dict[str, Any]:
        return self.model.health()

    def evaluate(self, features: dict[str, Any]) -> dict[str, Any]:
        try:
            isolation = self.model.evaluate(features)
        except (FileNotFoundError, OSError, TypeError, ValueError) as exception:
            isolation = {
                "status": "unavailable",
                "score": None,
                "model_version": None,
                "error": str(exception),
            }
        decision_input = dict(features)
        decision = decide(decision_input, str(isolation["status"]))
        return {
            "isolation_forest": isolation,
            "decision_layer": decision,
        }
