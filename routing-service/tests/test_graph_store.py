from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routing.graph_store import Coordinate, GraphStore


class NodeView:
    def __init__(self, graph):
        self.graph = graph

    def __getitem__(self, node):
        return self.graph.node_data[node]

    def __call__(self, data=False):
        return list(self.graph.node_data.items()) if data else list(self.graph.node_data)


class EdgeView:
    def __init__(self, graph):
        self.graph = graph

    def __getitem__(self, edge):
        start, end, key = edge
        return self.graph.adj[start][end][key]


class TinyGraph:
    def __init__(self):
        self.node_data = {}
        self.adj = {}
        self.nodes = NodeView(self)
        self.edges = EdgeView(self)

    def __contains__(self, node):
        return node in self.node_data

    def add_node(self, node, **attributes):
        self.node_data[node] = attributes
        self.adj.setdefault(node, {})

    def add_edge(self, start, end, *, key, **attributes):
        self.adj[start].setdefault(end, {})[key] = attributes


def subgraph_view(graph, filter_node=None, filter_edge=None):
    view = TinyGraph()
    allowed = {
        node for node in graph.node_data
        if filter_node is None or filter_node(node)
    }
    for node in allowed:
        view.add_node(node, **graph.node_data[node])
    for start in allowed:
        for end, keyed_edges in graph.adj[start].items():
            if end not in allowed:
                continue
            for key, attributes in keyed_edges.items():
                if filter_edge is None or filter_edge(start, end, key):
                    view.add_edge(start, end, key=key, **attributes)
    return view


class GraphStoreObstacleTests(unittest.TestCase):
    def test_obstacle_route_uses_first_natural_downstream_rejoin(self):
        graph = TinyGraph()
        nodes = {
            "A": (27.0000, 85.0000),
            "B": (27.0000, 85.0010),
            "C": (27.0000, 85.0020),
            "D": (27.0000, 85.0030),
            "X": (27.0010, 85.0007),
            "Y": (27.0010, 85.0017),
        }
        for node, (latitude, longitude) in nodes.items():
            graph.add_node(node, y=latitude, x=longitude)

        def edge(start, end, seconds=10.0):
            graph.add_edge(
                start,
                end,
                key=0,
                travel_time=seconds,
                length=100.0,
                highway="residential",
            )

        edge("A", "B", 2.0)
        edge("B", "C", 2.0)
        edge("C", "D", 2.0)
        edge("A", "X")
        edge("X", "Y")
        edge("Y", "C")

        def nearest_nodes(_graph, longitude, latitude):
            return min(
                nodes,
                key=lambda node: (
                    nodes[node][0] - float(latitude)
                ) ** 2 + (
                    nodes[node][1] - float(longitude)
                ) ** 2,
            )

        fake_osmnx = SimpleNamespace(
            distance=SimpleNamespace(nearest_nodes=nearest_nodes)
        )
        fake_networkx = SimpleNamespace(subgraph_view=subgraph_view)
        store = GraphStore("unused.graphml")
        store._graph = graph
        store._coordinate_node_lookup = {
            (round(latitude, 7), round(longitude, 7)): node
            for node, (latitude, longitude) in nodes.items()
        }

        with patch.dict(
            sys.modules,
            {"osmnx": fake_osmnx, "networkx": fake_networkx},
        ):
            result = store.route_avoiding_segment(
                Coordinate(*nodes["A"]),
                Coordinate(*nodes["D"]),
                Coordinate(*nodes["B"]),
                downstream_candidates=[
                    Coordinate(*nodes["C"]),
                    Coordinate(*nodes["D"]),
                ],
            )

        self.assertEqual(result["rejoin_candidate_index"], 0)
        self.assertEqual(result["target_node"], "C")
        self.assertEqual(
            result["road_node_coordinates"],
            [list(nodes[node]) for node in ["A", "X", "Y", "C"]],
        )
        self.assertNotIn(list(nodes["B"]), result["road_node_coordinates"])


if __name__ == "__main__":
    unittest.main()
