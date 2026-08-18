"""Distance-based, discrete-time vehicle simulation."""

from .engine import (
    DuplicateSimulation,
    Simulation,
    SimulationManager,
    SimulationNotFound,
    TransitionError,
)

__all__ = [
    "DuplicateSimulation",
    "Simulation",
    "SimulationManager",
    "SimulationNotFound",
    "TransitionError",
]

