"""
graph.py — Builds a NetworkX DiGraph from extracted entities and relationships,
attaches metadata and confidence scores, and handles persistence (pickle + GraphML).
"""

import pickle
from pathlib import Path
from typing import List, Optional, Dict, Any

import networkx as nx
from rich.console import Console

from devgraph.models import Entity, Relationship

console = Console()

GRAPH_FILE    = "devgraph.pkl"
GRAPHML_FILE  = "devgraph.graphml"


# ── Build ─────────────────────────────────────────────────────────────────────────

def build_graph(
    entities:      List[Entity],
    relationships: List[Relationship],
) -> nx.DiGraph:
    """
    Construct a directed, weighted graph from extracted triples.
    Each node carries entity metadata; each edge carries confidence + source.
    """
    G = nx.DiGraph()

    for ent in entities:
        G.add_node(
            ent.id,
            name          = ent.name,
            type          = ent.type.value,
            aliases       = ent.aliases,
            mention_count = ent.metadata.get("mention_count", 1),
            **{k: v for k, v in ent.metadata.items() if k != "mention_count"},
        )

    for rel in relationships:
        # Nodes referenced in relationships but missing from entity list
        if rel.source_id not in G:
            G.add_node(rel.source_id, name=rel.source_id, type="Unknown")
        if rel.target_id not in G:
            G.add_node(rel.target_id, name=rel.target_id, type="Unknown")

        G.add_edge(
            rel.source_id,
            rel.target_id,
            type       = rel.type.value,
            confidence = rel.confidence,
            source_url = rel.source_artifact,
            dimmed     = rel.confidence < 0.6,
        )

    console.print(
        f"[bold green]✓ Graph built: "
        f"{G.number_of_nodes()} nodes, {G.number_of_edges()} edges[/bold green]"
    )
    return G


# ── Persistence ───────────────────────────────────────────────────────────────────

def save_graph(G: nx.DiGraph, path: str = GRAPH_FILE) -> None:
    with open(path, "wb") as f:
        pickle.dump(G, f)
    console.print(f"[green]Graph saved → {path}[/green]")


def load_graph(path: str = GRAPH_FILE) -> Optional[nx.DiGraph]:
    if not Path(path).exists():
        return None
    with open(path, "rb") as f:
        G = pickle.load(f)
    console.print(
        f"[green]Graph loaded: {G.number_of_nodes()} nodes, "
        f"{G.number_of_edges()} edges[/green]"
    )
    return G


def export_graphml(G: nx.DiGraph, path: str = GRAPHML_FILE) -> None:
    """Export to GraphML for use in Gephi, yEd, etc."""
    # GraphML can't handle list-type node attributes — stringify them
    H = G.copy()
    for node, data in H.nodes(data=True):
        for k, v in data.items():
            if isinstance(v, (list, dict)):
                H.nodes[node][k] = str(v)
    nx.write_graphml(H, path)
    console.print(f"[green]GraphML exported → {path}[/green]")


# ── Merge (for incremental updates) ─────────────────────────────────────────────

def merge_graphs(base: nx.DiGraph, new: nx.DiGraph) -> nx.DiGraph:
    """Merge new graph into base, updating mention counts."""
    merged = base.copy()
    for node, data in new.nodes(data=True):
        if node in merged:
            merged.nodes[node]["mention_count"] = (
                merged.nodes[node].get("mention_count", 1) +
                data.get("mention_count", 1)
            )
        else:
            merged.add_node(node, **data)
    for src, tgt, data in new.edges(data=True):
        if not merged.has_edge(src, tgt):
            merged.add_edge(src, tgt, **data)
    return merged


# ── Query helpers ─────────────────────────────────────────────────────────────────

def get_neighbors(G: nx.DiGraph, node_id: str, rel_type: str = None) -> List[Dict]:
    """Return all nodes reachable from node_id (optionally filtered by rel_type)."""
    results = []
    for _, tgt, data in G.out_edges(node_id, data=True):
        if rel_type and data.get("type") != rel_type:
            continue
        results.append({
            "node": tgt,
            "data": dict(G.nodes[tgt]),
            "edge": data,
        })
    return results


def find_nodes_by_name(G: nx.DiGraph, name: str) -> List[str]:
    """Fuzzy search for a node by its name or aliases."""
    name_lower = name.lower()
    matches = []
    for node, data in G.nodes(data=True):
        if name_lower in data.get("name", "").lower():
            matches.append(node)
            continue
        for alias in data.get("aliases", []):
            if name_lower in str(alias).lower():
                matches.append(node)
                break
    return matches


def find_nodes_by_type(G: nx.DiGraph, entity_type: str) -> List[tuple]:
    """Return all nodes of a given entity type."""
    return [
        (node, data)
        for node, data in G.nodes(data=True)
        if data.get("type", "").lower() == entity_type.lower()
    ]


def top_nodes_by_degree(G: nx.DiGraph, entity_type: str = None, n: int = 10) -> List[tuple]:
    """Return top-n nodes by total degree (in+out), optionally filtered by type."""
    nodes = (
        find_nodes_by_type(G, entity_type)
        if entity_type
        else list(G.nodes(data=True))
    )
    ranked = sorted(
        nodes,
        key=lambda x: G.degree(x[0]),
        reverse=True,
    )
    return ranked[:n]
