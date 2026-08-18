from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import inf
from typing import TYPE_CHECKING, Any, Callable, Hashable

if TYPE_CHECKING:
    import networkx as nx

Node = Hashable
Heuristic = Callable[[Node, Node], float]


class RouteNotFound(RuntimeError):
    """Raised when a destination cannot be reached from an origin."""


@dataclass(frozen=True)
class SearchResult:
    nodes: list[Node]
    edges: list[tuple[Node, Node, Hashable]]
    cost: float
    visited_nodes: int


def astar_search(
    graph: "nx.MultiDiGraph | Any",
    source: Node,
    target: Node,
    *,
    weight: str = "travel_time",
    heuristic: Heuristic | None = None,
) -> SearchResult:
    """Find the lowest-cost directed path with A*.

    Parallel road edges are evaluated separately. The result retains each edge
    key so the API can return the correct OSM road geometry.
    """

    if source not in graph or target not in graph:
        raise RouteNotFound("The origin or destination is outside the graph.")

    if source == target:
        return SearchResult(nodes=[source], edges=[], cost=0.0, visited_nodes=1)

    estimate = heuristic or (lambda _node, _target: 0.0)
    best_cost: dict[Node, float] = {source: 0.0}
    came_from: dict[Node, tuple[Node, Hashable]] = {}
    queue: list[tuple[float, float, int, Node]] = []
    tie_breaker = count()
    heappush(queue, (estimate(source, target), 0.0, next(tie_breaker), source))
    visited_nodes = 0

    while queue:
        _priority, queued_cost, _order, current = heappop(queue)
        if queued_cost > best_cost.get(current, inf):
            continue

        visited_nodes += 1
        if current == target:
            nodes, edges = _reconstruct_path(came_from, source, target)
            return SearchResult(
                nodes=nodes,
                edges=edges,
                cost=best_cost[target],
                visited_nodes=visited_nodes,
            )

        for neighbor, keyed_edges in graph.adj[current].items():
            for edge_key, attributes in keyed_edges.items():
                edge_cost = attributes.get(weight)
                if edge_cost is None:
                    continue

                edge_cost = float(edge_cost)
                if edge_cost < 0:
                    raise ValueError("A* cannot use a negative road-edge cost.")

                candidate = best_cost[current] + edge_cost
                if candidate >= best_cost.get(neighbor, inf):
                    continue

                best_cost[neighbor] = candidate
                came_from[neighbor] = (current, edge_key)
                priority = candidate + max(0.0, float(estimate(neighbor, target)))
                heappush(
                    queue,
                    (priority, candidate, next(tie_breaker), neighbor),
                )

    raise RouteNotFound("No directed road path connects the two points.")


def _reconstruct_path(
    came_from: dict[Node, tuple[Node, Hashable]],
    source: Node,
    target: Node,
) -> tuple[list[Node], list[tuple[Node, Node, Hashable]]]:
    nodes: list[Node] = [target]
    edges: list[tuple[Node, Node, Hashable]] = []
    current = target

    while current != source:
        if current not in came_from:
            raise RouteNotFound("The route could not be reconstructed.")
        previous, edge_key = came_from[current]
        edges.append((previous, current, edge_key))
        nodes.append(previous)
        current = previous

    nodes.reverse()
    edges.reverse()
    return nodes, edges
