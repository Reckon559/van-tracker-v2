from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
import osmnx as ox

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_ROAD_SPEEDS = {
    "motorway": 60,
    "trunk": 45,
    "primary": 40,
    "secondary": 35,
    "tertiary": 30,
    "residential": 20,
    "service": 15,
    "unclassified": 20,
}


def main() -> None:
    west = float(os.getenv("KTM_WEST", "85.180"))
    south = float(os.getenv("KTM_SOUTH", "27.550"))
    east = float(os.getenv("KTM_EAST", "85.580"))
    north = float(os.getenv("KTM_NORTH", "27.850"))
    graph_path = Path(os.getenv("GRAPH_PATH", "data/kathmandu_drive.graphml"))
    if not graph_path.is_absolute():
        graph_path = BASE_DIR / graph_path
    graph_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading driveable OSM roads for {(west, south, east, north)}...")
    graph = ox.graph_from_bbox(
        (west, south, east, north),
        network_type="drive",
        simplify=True,
        retain_all=False,
    )
    graph = ox.routing.add_edge_speeds(
        graph,
        hwy_speeds=DEFAULT_ROAD_SPEEDS,
        fallback=20,
    )
    graph = ox.routing.add_edge_travel_times(graph)

    ox.save_graphml(graph, graph_path)
    print(
        f"Saved {len(graph.nodes):,} nodes and {len(graph.edges):,} directed edges "
        f"to {graph_path}"
    )


if __name__ == "__main__":
    main()

