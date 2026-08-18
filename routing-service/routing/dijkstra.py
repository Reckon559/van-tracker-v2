from __future__ import annotations

from typing import TYPE_CHECKING, Any, Hashable

if TYPE_CHECKING:
    import networkx as nx

from .astar import SearchResult, astar_search


def dijkstra_search(
    graph: "nx.MultiDiGraph | Any",
    source: Hashable,
    target: Hashable,
    *,
    weight: str = "travel_time",
) -> SearchResult:
    """Reference search used to verify that A* returns the same optimal cost."""

    return astar_search(
        graph,
        source,
        target,
        weight=weight,
        heuristic=lambda _node, _target: 0.0,
    )
