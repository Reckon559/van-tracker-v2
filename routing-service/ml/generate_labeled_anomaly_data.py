"""
Generates a realistic, trip-grouped, ground-truth labeled anomaly dataset for Kathmandu school vans.
Simulates normal trips, minor traffic detours, severe unauthorized diversions, context stalls, and speeding events.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import random
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BASE_DIR / "data" / "kathmandu_anomaly_labeled.csv"

CONTEXT_LIMITS: dict[str, tuple[float, float, float]] = {
    "bus_stop": (20.0, 300.0, 70.0),       # min, max normal, mode
    "traffic_light": (3.0, 75.0, 18.0),
    "school": (20.0, 900.0, 140.0),
    "depot": (20.0, 900.0, 180.0),
    "unknown": (2.0, 90.0, 12.0),
}


def generate_labeled_trips(
    num_trips: int = 600,
    min_steps: int = 20,
    max_steps: int = 45,
    seed: int = 2026,
) -> list[dict[str, object]]:
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    contexts = list(CONTEXT_LIMITS.keys())
    context_weights = [0.25, 0.30, 0.15, 0.10, 0.20]
    
    scenario_types = [
        "normal_smooth",
        "normal_with_stops",
        "mild_alley_detour",
        "severe_unauthorized_deviation",
        "stalling_traffic_light",
        "stalling_bus_stop",
        "stalling_roadside",
        "overspeed_minor",
        "overspeed_severe",
    ]
    scenario_weights = [0.35, 0.25, 0.12, 0.08, 0.05, 0.04, 0.05, 0.04, 0.02]

    for trip_idx in range(1, num_trips + 1):
        trip_id = f"TRIP_ANOM_{trip_idx:04d}"
        scenario = rng.choices(scenario_types, weights=scenario_weights, k=1)[0]
        context = rng.choices(contexts, weights=context_weights, k=1)[0]
        speed_limit = rng.choice([20.0, 30.0, 35.0, 40.0, 45.0, 50.0])
        steps = rng.randint(min_steps, max_steps)
        if scenario in {"severe_unauthorized_deviation", "stalling_bus_stop", "stalling_roadside"}:
            steps = max(steps, 36)
        
        cumulative_off_route = 0.0
        active_deviation_sec = 0.0
        active_overspeed_sec = 0.0
        active_stop_sec = 0.0

        for step in range(steps):
            elapsed_sec = step * 5.0
            
            if scenario == "normal_smooth":
                speed = rng.uniform(speed_limit * 0.45, speed_limit)
                route_dist = min(25.0, rng.expovariate(1.0 / 5.0))
                heading_diff = rng.uniform(0.0, 10.0)
                active_deviation_sec = 0.0
                active_overspeed_sec = 0.0
                active_stop_sec = 0.0
                label = "normal"
                
            elif scenario == "normal_with_stops":
                if step in range(5, 10):  # Stop within normal bounds
                    speed = 0.0
                    active_stop_sec += 5.0
                    route_dist = rng.uniform(0.0, 8.0)
                    heading_diff = 0.0
                else:
                    speed = rng.uniform(speed_limit * 0.4, speed_limit)
                    active_stop_sec = 0.0
                    route_dist = min(25.0, rng.expovariate(1.0 / 5.0))
                    heading_diff = rng.uniform(0.0, 12.0)
                active_deviation_sec = 0.0
                active_overspeed_sec = 0.0
                label = "normal"
                
            elif scenario == "mild_alley_detour":
                # Van takes a small 20-40s bypass around a narrow alley
                if 8 <= step <= 14:
                    speed = rng.uniform(12.0, speed_limit * 0.8)
                    active_deviation_sec += 5.0
                    route_dist = rng.uniform(35.0, 85.0)
                    heading_diff = rng.uniform(20.0, 55.0)
                    cumulative_off_route += (speed / 3.6) * 5.0
                    label = "monitor"
                else:
                    speed = rng.uniform(15.0, speed_limit)
                    route_dist = min(20.0, rng.expovariate(1.0 / 4.0))
                    heading_diff = rng.uniform(0.0, 10.0)
                    active_deviation_sec = 0.0
                    label = "normal"
                    
            elif scenario == "severe_unauthorized_deviation":
                # Van leaves planned route for >2 mins and >250m
                if step >= 6:
                    speed = rng.uniform(22.0, speed_limit + 4.0)
                    active_deviation_sec += 5.0
                    route_dist = min(600.0, 260.0 + (step - 6) * 25.0)
                    heading_diff = rng.uniform(45.0, 120.0)
                    cumulative_off_route += (speed / 3.6) * 5.0
                    label = "suspicious" if active_deviation_sec >= 120.0 and cumulative_off_route >= 800.0 else "monitor"
                else:
                    speed = rng.uniform(15.0, speed_limit)
                    route_dist = min(20.0, rng.expovariate(1.0 / 5.0))
                    heading_diff = rng.uniform(0.0, 10.0)
                    label = "normal"
                    
            elif scenario == "stalling_traffic_light":
                # Exceeds traffic light 75s limit
                context = "traffic_light"
                if step >= 5:
                    speed = 0.0
                    active_stop_sec += 5.0
                    route_dist = rng.uniform(0.0, 5.0)
                    heading_diff = 0.0
                    label = "suspicious" if active_stop_sec > 120.0 else ("monitor" if active_stop_sec > 75.0 else "normal")
                else:
                    speed = rng.uniform(15.0, speed_limit)
                    route_dist = min(15.0, rng.expovariate(1.0 / 4.0))
                    heading_diff = rng.uniform(0.0, 10.0)
                    label = "normal"

            elif scenario == "stalling_bus_stop":
                # Exceeds bus stop 300s limit
                context = "bus_stop"
                if step >= 4:
                    speed = 0.0
                    active_stop_sec += 5.0
                    route_dist = rng.uniform(0.0, 5.0)
                    heading_diff = 0.0
                    label = "suspicious" if active_stop_sec > 400.0 else ("monitor" if active_stop_sec > 300.0 else "normal")
                else:
                    speed = rng.uniform(15.0, speed_limit)
                    route_dist = min(15.0, rng.expovariate(1.0 / 4.0))
                    heading_diff = rng.uniform(0.0, 10.0)
                    label = "normal"

            elif scenario == "stalling_roadside":
                # Exceeds roadside 120s limit
                context = "unknown"
                if step >= 5:
                    speed = 0.0
                    active_stop_sec += 5.0
                    route_dist = rng.uniform(0.0, 10.0)
                    heading_diff = 0.0
                    label = "suspicious" if active_stop_sec > 180.0 else ("monitor" if active_stop_sec > 120.0 else "normal")
                else:
                    speed = rng.uniform(15.0, speed_limit)
                    route_dist = min(15.0, rng.expovariate(1.0 / 4.0))
                    heading_diff = rng.uniform(0.0, 10.0)
                    label = "normal"

            elif scenario == "overspeed_minor":
                # 3 to 8 km/h over limit briefly
                speed = speed_limit + rng.uniform(3.0, 8.0)
                active_overspeed_sec += 5.0
                route_dist = min(20.0, rng.expovariate(1.0 / 5.0))
                heading_diff = rng.uniform(0.0, 8.0)
                label = "monitor" if active_overspeed_sec >= 10.0 else "normal"

            elif scenario == "overspeed_severe":
                # >= 10 km/h over limit
                speed = speed_limit + rng.uniform(11.0, 24.0)
                active_overspeed_sec += 5.0
                route_dist = min(20.0, rng.expovariate(1.0 / 5.0))
                heading_diff = rng.uniform(0.0, 10.0)
                label = "suspicious"

            rows.append({
                "trip_id": trip_id,
                "sample_step": step,
                "simulated_time_sec": round(elapsed_sec, 2),
                "distance_from_route_m": round(route_dist, 2),
                "deviation_duration_sec": round(active_deviation_sec, 2),
                "heading_difference_deg": round(heading_diff, 2),
                "off_route_distance_m": round(cumulative_off_route, 2),
                "returned_to_route": 1 if (active_deviation_sec == 0.0 and cumulative_off_route > 0) else 0,
                "stop_duration_sec": round(active_stop_sec, 2),
                "current_speed_kmh": round(speed, 2),
                "speed_limit_kmh": round(speed_limit, 2),
                "overspeed_duration_sec": round(active_overspeed_sec, 2),
                "location_context": context,
                "scenario_type": scenario,
                "label": label,  # normal, monitor, suspicious
            })
            
    return rows


def main():
    parser = argparse.ArgumentParser(description="Generate labeled Kathmandu school van anomaly datasets.")
    parser.add_argument("--trips", type=int, default=600, help="Number of trips to generate")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument("--seed", type=int, default=2026, help="Random seed")
    args = parser.parse_args()

    print(f"Generating {args.trips} labeled trip scenarios...")
    rows = generate_labeled_trips(num_trips=args.trips, seed=args.seed)
    
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(args.output, index=False)
    
    print(f"Saved {len(df):,} rows from {args.trips:,} trips to {args.output}")
    print("\nClass Distribution:")
    for label, count in df["label"].value_counts().items():
        print(f"  - {label:12s}: {count:6d} ({count/len(df)*100:.1f}%)")


if __name__ == "__main__":
    main()
