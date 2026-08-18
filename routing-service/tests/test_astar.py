from __future__ import annotations

import unittest

from routing.astar import RouteNotFound, astar_search
from routing.dijkstra import dijkstra_search


class TinyMultiDiGraph:
    """Small NetworkX-compatible fixture for dependency-free algorithm tests."""

    def __init__(self):
        self.adj = {}

    def __contains__(self, node):
        return node in self.adj

    def add_node(self, node):
        self.adj.setdefault(node, {})

    def add_edge(self, start, end, *, key, **attributes):
        self.add_node(start)
        self.add_node(end)
        self.adj[start].setdefault(end, {})[key] = attributes


def sample_graph() -> TinyMultiDiGraph:
    graph = TinyMultiDiGraph()
    graph.add_edge("A", "B", key=0, travel_time=4.0, length=100.0)
    graph.add_edge("A", "B", key=1, travel_time=7.0, length=80.0)
    graph.add_edge("B", "D", key=0, travel_time=5.0, length=100.0)
    graph.add_edge("A", "C", key=0, travel_time=2.0, length=70.0)
    graph.add_edge("C", "D", key=0, travel_time=10.0, length=100.0)
    graph.add_node("Z")
    return graph


class AStarTests(unittest.TestCase):
    def test_selects_lowest_cost_parallel_edge_and_path(self):
        result = astar_search(sample_graph(), "A", "D", weight="travel_time")
        self.assertEqual(result.nodes, ["A", "B", "D"])
        self.assertEqual(result.edges[0], ("A", "B", 0))
        self.assertEqual(result.cost, 9.0)

    def test_matches_dijkstra_reference_cost(self):
        graph = sample_graph()
        astar_result = astar_search(graph, "A", "D", weight="travel_time")
        dijkstra_result = dijkstra_search(graph, "A", "D", weight="travel_time")
        self.assertEqual(astar_result.cost, dijkstra_result.cost)

    def test_same_origin_and_destination(self):
        result = astar_search(sample_graph(), "A", "A")
        self.assertEqual(result.nodes, ["A"])
        self.assertEqual(result.edges, [])
        self.assertEqual(result.cost, 0.0)

    def test_unreachable_destination_raises(self):
        with self.assertRaises(RouteNotFound):
            astar_search(sample_graph(), "A", "Z")


if __name__ == "__main__":
    unittest.main()
