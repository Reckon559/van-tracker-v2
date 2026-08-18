from __future__ import annotations

import unittest

from routing.graph_store import Coordinate, GraphStore


class FakeNodes:
    def __init__(self, entries):
        self.entries = entries

    def __call__(self, data=False):
        return self.entries if data else [node for node, _data in self.entries]


class FakeGraph:
    def __init__(self, entries):
        self.nodes = FakeNodes(entries)


class FakeCrossroadGraph(FakeGraph):
    def predecessors(self, _node):
        return [2, 3, 4, 5]

    def successors(self, _node):
        return [2, 3, 4, 5]

    def in_edges(self, node, keys=False, data=False):
        return [
            (other, node, 0, {"highway": "primary"})
            for other in self.predecessors(node)
        ]

    def out_edges(self, node, keys=False, data=False):
        return [
            (node, other, 0, {"highway": "secondary"})
            for other in self.successors(node)
        ]


class FakeProfileGraph:
    def __init__(self):
        self.nodes = {
            1: {"y": 27.700, "x": 85.300},
            2: {"y": 27.700, "x": 85.301},
            3: {"y": 27.700, "x": 85.302},
        }
        self.edges = {
            (1, 2, 0): {"travel_time": 10.0},
            (2, 3, 0): {"travel_time": 20.0},
        }

class ContextDetectionTests(unittest.TestCase):
    def test_route_profile_preserves_each_osm_edge_time(self):
        store = GraphStore("unused.graphml")
        store._graph = FakeProfileGraph()
        coordinates, times = store._path_profile(
            [(1, 2, 0), (2, 3, 0)],
            [1, 2, 3],
        )
        self.assertEqual(len(times), len(coordinates) - 1)
        self.assertEqual(times, [10.0, 20.0])

    def test_detector_returns_osm_traffic_light_zone(self):
        store = GraphStore("unused.graphml")
        store._graph = FakeGraph([
            (1, {
                "y": 27.7000,
                "x": 85.3000,
                "highway": "traffic_signals",
            }),
        ])
        result = store.detect_location_context(
            Coordinate(lat=27.7001, lng=85.3000)
        )
        self.assertEqual(result["context"], "traffic_light")
        self.assertEqual(result["radius_m"], 35.0)
        self.assertLess(result["distance_m"], result["radius_m"])

    def test_detector_returns_unknown_outside_all_zones(self):
        store = GraphStore("unused.graphml")
        store._graph = FakeGraph([
            (1, {"y": 27.7000, "x": 85.3000, "highway": "bus_stop"}),
        ])
        result = store.detect_location_context(
            Coordinate(lat=27.7100, lng=85.3000)
        )
        self.assertEqual(result["context"], "unknown")
        self.assertEqual(result["radius_m"], 30.0)

    def test_route_context_zones_are_fixed_at_osm_locations(self):
        store = GraphStore("unused.graphml")
        store._graph = FakeGraph([
            (7, {
                "y": 27.7001,
                "x": 85.3000,
                "highway": "traffic_signals",
            }),
        ])
        zones = store.context_zones_near_route([
            [27.7000, 85.2990],
            [27.7000, 85.3010],
        ])
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["context"], "traffic_light")
        self.assertEqual(zones[0]["latitude"], 27.7001)
        self.assertEqual(zones[0]["radius_m"], 35.0)

    def test_major_crossroad_is_inferred_as_traffic_light(self):
        store = GraphStore("unused.graphml")
        store._graph = FakeCrossroadGraph([
            (1, {
                "y": 27.7000,
                "x": 85.3000,
                "street_count": 4,
            }),
        ])
        result = store.detect_location_context(
            Coordinate(lat=27.7001, lng=85.3000)
        )
        self.assertEqual(result["context"], "traffic_light")
        self.assertEqual(result["source"], "heuristic_major_crossroad")
        self.assertEqual(result["radius_m"], 45.0)


if __name__ == "__main__":
    unittest.main()
