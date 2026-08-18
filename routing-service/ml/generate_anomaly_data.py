from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BASE_DIR / "data" / "kathmandu_anomaly_normal.csv"
CONTEXT_LIMITS = {
    "bus_stop": (20, 300, 70),
    "traffic_light": (3, 75, 18),
    "school": (20, 900, 140),
    "depot": (20, 900, 180),
    "unknown": (2, 90, 12),
}


def generate(row_count: int, seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    contexts = list(CONTEXT_LIMITS)
    weights = [0.20, 0.30, 0.16, 0.10, 0.24]
    for _ in range(row_count):
        context = rng.choices(contexts, weights=weights, k=1)[0]
        stopped = rng.random() < 0.34
        temporary_detour = rng.random() < 0.07
        speed_limit = rng.choice([20, 30, 35, 40, 45, 50])
        if stopped:
            low, high, mode = CONTEXT_LIMITS[context]
            stop_duration = rng.triangular(low, high, mode)
            speed = rng.uniform(0, 1.2)
        else:
            stop_duration = 0.0
            speed = rng.uniform(7, speed_limit + 3)

        if temporary_detour:
            route_distance = rng.uniform(25, 95)
            deviation_duration = rng.uniform(8, 100)
            heading_difference = rng.uniform(15, 75)
            off_route_distance = max(0, speed / 3.6 * deviation_duration)
            returned = int(rng.random() < 0.72)
        else:
            route_distance = min(35, rng.expovariate(1 / 7))
            deviation_duration = rng.uniform(0, 18)
            heading_difference = rng.uniform(0, 18)
            off_route_distance = rng.uniform(0, 30)
            returned = 0

        rows.append({
            "distance_from_route_m": round(route_distance, 2),
            "deviation_duration_sec": round(deviation_duration, 2),
            "heading_difference_deg": round(heading_difference, 2),
            "off_route_distance_m": round(off_route_distance, 2),
            "returned_to_route": returned,
            "stop_duration_sec": round(stop_duration, 2),
            "current_speed_kmh": round(speed, 2),
            "speed_limit_kmh": speed_limit,
            "overspeed_duration_sec": round(rng.uniform(0, 4) if speed > speed_limit else 0, 2),
            "location_context": context,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate normal Kathmandu van behavior samples.")
    parser.add_argument("--rows", type=int, default=15_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rows = generate(args.rows, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows):,} normal-behavior rows to {args.output}")


if __name__ == "__main__":
    main()
