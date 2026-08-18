from __future__ import annotations

import argparse
import ast
import csv
import math
import random
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = BASE_DIR / "data" / "kathmandu_drive.graphml"
DEFAULT_OUTPUT = BASE_DIR / "data" / "kathmandu_eta_synthetic.csv"

ROAD_DEFAULT_SPEEDS = {
    "motorway": 60.0,
    "trunk": 45.0,
    "primary": 40.0,
    "secondary": 35.0,
    "tertiary": 30.0,
    "residential": 20.0,
    "service": 15.0,
    "unclassified": 20.0,
}


@dataclass(frozen=True)
class RoadEdge:
    latitude: float
    longitude: float
    length_m: float
    travel_time_sec: float
    speed_kph: float
    road_type: str


def clean_road_type(value: str | None) -> str:
    if not value:
        return "unclassified"
    value = value.strip()
    if value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list) and parsed:
                value = str(parsed[0])
        except (SyntaxError, ValueError):
            pass
    value = value.lower().replace(" ", "_")
    return value if value in ROAD_DEFAULT_SPEEDS else "unclassified"


def load_graph_edges(graph_path: Path) -> list[RoadEdge]:
    tree = ET.parse(graph_path)
    root = tree.getroot()
    namespace = {"g": "http://graphml.graphdrawing.org/xmlns"}
    key_names = {
        element.attrib["id"]: element.attrib.get("attr.name", element.attrib["id"])
        for element in root.findall("g:key", namespace)
    }

    node_coordinates: dict[str, tuple[float, float]] = {}
    for node in root.findall(".//g:node", namespace):
        values = {
            key_names.get(data.attrib.get("key", ""), ""): data.text
            for data in node.findall("g:data", namespace)
        }
        try:
            node_coordinates[node.attrib["id"]] = (
                float(values["y"]),
                float(values["x"]),
            )
        except (KeyError, TypeError, ValueError):
            continue

    edges: list[RoadEdge] = []
    for edge in root.findall(".//g:edge", namespace):
        values = {
            key_names.get(data.attrib.get("key", ""), ""): data.text
            for data in edge.findall("g:data", namespace)
        }
        coordinate = node_coordinates.get(edge.attrib.get("source", ""))
        if coordinate is None:
            continue
        road_type = clean_road_type(values.get("highway"))
        try:
            length_m = max(1.0, float(values.get("length") or 0))
        except ValueError:
            continue
        try:
            speed_kph = float(values.get("speed_kph") or 0)
        except ValueError:
            speed_kph = 0.0
        if speed_kph <= 0:
            speed_kph = ROAD_DEFAULT_SPEEDS[road_type]
        try:
            travel_time_sec = float(values.get("travel_time") or 0)
        except ValueError:
            travel_time_sec = 0.0
        if travel_time_sec <= 0:
            travel_time_sec = length_m / (speed_kph / 3.6)
        edges.append(
            RoadEdge(
                latitude=coordinate[0],
                longitude=coordinate[1],
                length_m=length_m,
                travel_time_sec=travel_time_sec,
                speed_kph=speed_kph,
                road_type=road_type,
            )
        )
    if not edges:
        raise RuntimeError(f"No usable road edges were found in {graph_path}")
    return edges


def choose_hour(rng: random.Random, school_period: str) -> int:
    roll = rng.random()
    if school_period == "half_day" and roll < 0.58:
        return rng.randint(10, 13)
    if school_period == "exam" and roll < 0.58:
        return rng.randint(11, 15)
    if roll < 0.42:
        return rng.randint(6, 9)
    if roll < 0.84:
        return rng.randint(13, 17)
    return rng.choice([5, 10, 11, 12, 18, 19, 20])


def choose_traffic(
    rng: random.Random,
    hour: int,
    day_of_week: int,
    school_period: str,
) -> str:
    peak = hour in {7, 8, 9, 14, 15, 16, 17}
    school_exit = (
        school_period == "half_day" and hour in {11, 12, 13}
    ) or (school_period == "exam" and hour in {12, 13, 14, 15})
    score = rng.random() + (0.42 if peak else 0) + (0.28 if school_exit else 0)
    if day_of_week == 5:
        score -= 0.18
    if score >= 1.04:
        return "high"
    if score >= 0.48:
        return "medium"
    return "low"


def generate_rows(
    edges: list[RoadEdge],
    row_count: int,
    seed: int,
) -> list[dict[str, object]]:
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    trip_id = 1
    while len(rows) < row_count:
        route_edges = rng.choices(edges, k=rng.randint(18, 75))
        total_distance = sum(edge.length_m for edge in route_edges)
        total_baseline = sum(edge.travel_time_sec for edge in route_edges)
        if total_distance < 700 or total_baseline < 60:
            continue

        road_counts = Counter(edge.road_type for edge in route_edges)
        dominant_road = road_counts.most_common(1)[0][0]
        location_edge = rng.choice(route_edges)
        speed_limit = max(15.0, min(60.0, location_edge.speed_kph))
        school_period = rng.choices(
            ["regular", "exam", "half_day"],
            weights=[0.66, 0.19, 0.15],
            k=1,
        )[0]
        day_of_week = rng.randint(0, 5)
        hour = choose_hour(rng, school_period)
        traffic = choose_traffic(rng, hour, day_of_week, school_period)
        weather = rng.choices(
            ["clear", "rain", "heavy_rain", "fog"],
            weights=[0.68, 0.20, 0.07, 0.05],
            k=1,
        )[0]
        traffic_multiplier = {
            "low": rng.uniform(0.92, 1.16),
            "medium": rng.uniform(1.24, 1.68),
            "high": rng.uniform(1.72, 2.65),
        }[traffic]
        weather_multiplier = {
            "clear": rng.uniform(0.98, 1.06),
            "rain": rng.uniform(1.08, 1.24),
            "heavy_rain": rng.uniform(1.25, 1.55),
            "fog": rng.uniform(1.15, 1.38),
        }[weather]
        schedule_multiplier = {
            "regular": 1.0,
            "exam": rng.uniform(0.96, 1.08),
            "half_day": rng.uniform(1.02, 1.16),
        }[school_period]
        central_distance = math.hypot(
            (location_edge.latitude - 27.704) * 111.0,
            (location_edge.longitude - 85.318) * 98.0,
        )
        central_multiplier = 1.10 if central_distance < 3.2 else 1.0
        total_stops = rng.randint(3, 12)
        samples = rng.randint(24, 48)
        progress_values = sorted(
            {0.0, *[rng.uniform(0.01, 0.985) for _ in range(samples - 1)]}
        )

        for progress in progress_values:
            if len(rows) >= row_count:
                break
            distance_remaining = total_distance * (1.0 - progress)
            baseline_remaining = total_baseline * (1.0 - progress)
            stops_remaining = max(0, math.ceil(total_stops * (1.0 - progress)))
            incident = int(rng.random() < 0.045)
            incident_delay = rng.uniform(70, 420) if incident else 0.0
            stop_delay = stops_remaining * rng.uniform(18, 42)
            effective_multiplier = (
                traffic_multiplier
                * weather_multiplier
                * schedule_multiplier
                * central_multiplier
            )
            current_speed = max(
                2.5,
                min(
                    speed_limit,
                    speed_limit / effective_multiplier * rng.uniform(0.82, 1.12),
                ),
            )
            target = (
                baseline_remaining * effective_multiplier
                + stop_delay
                + incident_delay
            )
            target *= rng.uniform(0.94, 1.07)
            target = max(0.0, target)

            rows.append(
                {
                    "trip_id": trip_id,
                    "latitude": round(location_edge.latitude + rng.uniform(-0.002, 0.002), 7),
                    "longitude": round(location_edge.longitude + rng.uniform(-0.002, 0.002), 7),
                    "distance_remaining_m": round(distance_remaining, 2),
                    "baseline_remaining_sec": round(baseline_remaining, 2),
                    "current_speed_kmh": round(current_speed, 2),
                    "speed_limit_kmh": round(speed_limit, 2),
                    "route_progress": round(progress, 5),
                    "hour_of_day": hour,
                    "day_of_week": day_of_week,
                    "stops_remaining": stops_remaining,
                    "road_type": dominant_road,
                    "traffic_level": traffic,
                    "weather": weather,
                    "school_period": school_period,
                    "incident": incident,
                    "actual_remaining_sec": round(target, 2),
                }
            )
        trip_id += 1
    return rows


def write_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Kathmandu OSM-grounded synthetic ETA training rows."
    )
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.rows < 1_000:
        parser.error("--rows must be at least 1000")

    print(f"Reading Kathmandu road attributes from {args.graph}...")
    edges = load_graph_edges(args.graph)
    print(f"Loaded {len(edges):,} usable directed road edges.")
    rows = generate_rows(edges, args.rows, args.seed)
    write_csv(rows, args.output)
    trip_count = len({row["trip_id"] for row in rows})
    print(f"Saved {len(rows):,} rows from {trip_count:,} synthetic trips to {args.output}")


if __name__ == "__main__":
    main()
