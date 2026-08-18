"""
Feature engineering pipelines for ETA Regression and Safety Anomaly Detection.
Provides consistent, reusable mathematical and categorical transformations.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

# Kathmandu Central Urban Core Reference (Ratna Park / New Road / Thamel)
KTM_CORE_LAT = 27.704
KTM_CORE_LNG = 85.318

# Location Context Normal Stop Limits (seconds)
CONTEXT_STOP_LIMITS: dict[str, float] = {
    "bus_stop": 300.0,
    "traffic_light": 75.0,
    "school": 900.0,
    "depot": 900.0,
    "unknown": 120.0,
}


def add_cyclic_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds sin and cos encodings for hour_of_day and day_of_week."""
    df = df.copy()
    if "hour_of_day" in df.columns:
        hour = df["hour_of_day"].astype(float)
        df["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
        df["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)
    if "day_of_week" in df.columns:
        day = df["day_of_week"].astype(float)
        df["day_sin"] = np.sin(2.0 * np.pi * day / 7.0)
        df["day_cos"] = np.cos(2.0 * np.pi * day / 7.0)
    return df


def engineer_eta_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extracts spatial, dynamic, and temporal interaction features for ETA prediction.
    """
    df = add_cyclic_time_features(df)
    
    # 1. Stop Density per kilometer remaining
    dist_km = np.maximum(df["distance_remaining_m"].astype(float) / 1000.0, 0.05)
    stops = df["stops_remaining"].astype(float)
    df["stop_density_per_km"] = stops / dist_km
    
    # 2. Dynamic Speed Ratio & Congestion Indices
    speed = df["current_speed_kmh"].astype(float)
    limit = np.maximum(df["speed_limit_kmh"].astype(float), 10.0)
    df["speed_ratio"] = speed / limit
    
    baseline_sec = np.maximum(df["baseline_remaining_sec"].astype(float), 1.0)
    implied_speed_kmh = (df["distance_remaining_m"].astype(float) / baseline_sec) * 3.6
    df["implied_osm_speed_kmh"] = implied_speed_kmh
    df["congestion_factor"] = np.clip(
        implied_speed_kmh / np.maximum(speed, 3.0),
        0.3,
        5.0
    )
    
    # 3. Kathmandu Central Core Proximity
    if "latitude" in df.columns and "longitude" in df.columns:
        lat = df["latitude"].astype(float)
        lng = df["longitude"].astype(float)
        core_dist_km = np.hypot((lat - KTM_CORE_LAT) * 111.0, (lng - KTM_CORE_LNG) * 98.0)
        df["dist_to_ktm_core_km"] = core_dist_km
        df["is_core_urban"] = (core_dist_km < 3.2).astype(float)
    
    # 4. Non-linear Progress Curve
    progress = np.clip(df["route_progress"].astype(float), 0.0, 1.0)
    df["progress_squared"] = progress ** 2
    
    return df


def engineer_anomaly_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extracts compound deviation and context-normalized metrics for safety classification.
    """
    df = df.copy()
    
    # 1. Context-Normalized Stop Duration Excess
    stop_dur = df["stop_duration_sec"].astype(float)
    context_limits = df["location_context"].astype(str).map(CONTEXT_STOP_LIMITS).fillna(120.0)
    df["stop_excess_ratio"] = np.maximum(0.0, stop_dur - context_limits) / context_limits
    df["stop_excess_sec"] = np.maximum(0.0, stop_dur - context_limits)
    
    # 2. Spatial Deviation Velocity (rate of moving off-route)
    off_route_dist = df["off_route_distance_m"].astype(float)
    dev_dur = np.maximum(df["deviation_duration_sec"].astype(float), 1.0)
    df["deviation_spatial_rate"] = off_route_dist / dev_dur
    
    # 3. Compound Heading Severity
    heading_diff = np.abs(df["heading_difference_deg"].astype(float))
    dist_from_route = df["distance_from_route_m"].astype(float)
    df["heading_deviation_intensity"] = (heading_diff / 180.0) * (dist_from_route / 100.0)
    
    # 4. Overspeed Severity Factor
    speed = df["current_speed_kmh"].astype(float)
    limit = df["speed_limit_kmh"].astype(float)
    speed_delta = np.maximum(0.0, speed - limit)
    overspeed_dur = df["overspeed_duration_sec"].astype(float)
    df["overspeed_severity"] = (speed_delta ** 1.3) * np.log1p(overspeed_dur)
    
    return df
