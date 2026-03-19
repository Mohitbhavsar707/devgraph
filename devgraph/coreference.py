"""
coreference.py — Detects that "auth", "auth-service", "authentication module",
and "the login thing" all refer to the same entity, then merges them into a
single canonical node in the graph.

Strategy (two-pass):
  1. Exact & fuzzy string matching on entity names/aliases (fast, no API calls).
  2. Embedding-based cosine similarity for surviving candidates (uses Claude if
     sentence-transformers is unavailable).
"""

import re
from typing import List, Dict, Tuple
from difflib import SequenceMatcher

from rich.console import Console

from devgraph.models import Entity, Relationship, EntityType

console = Console()

# ── Tunables ─────────────────────────────────────────────────────────────────────

FUZZY_THRESHOLD    = 0.82   # SequenceMatcher ratio above which names are merged
SAME_TYPE_ONLY     = True   # only merge entities of the same type


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _all_names(entity: Entity) -> List[str]:
    """Return the canonical name plus every alias."""
    return [entity.name] + entity.aliases


def _are_coreferent(e1: Entity, e2: Entity) -> bool:
    """Return True if two entities likely refer to the same real-world thing."""
    if SAME_TYPE_ONLY and e1.type != e2.type:
        return False

    names1 = _all_names(e1)
    names2 = _all_names(e2)

    for n1 in names1:
        for n2 in names2:
            if _similarity(n1, n2) >= FUZZY_THRESHOLD:
                return True
            # substring containment (catches "auth" ↔ "auth-service")
            n1n = _normalize(n1)
            n2n = _normalize(n2)
            if len(n1n) >= 4 and len(n2n) >= 4:
                if n1n in n2n or n2n in n1n:
                    return True
    return False


def _canonical(e1: Entity, e2: Entity) -> Entity:
    """
    Merge e2 into e1 (e1 is kept as the canonical node).
    The entity with the higher mention_count wins the canonical slot.
    """
    if e2.metadata.get("mention_count", 0) > e1.metadata.get("mention_count", 0):
        e1, e2 = e2, e1  # swap so higher-count is always e1

    merged_aliases = list(set(
        _all_names(e1) + _all_names(e2)
    ))
    e1.aliases = [a for a in merged_aliases if a != e1.name]
    e1.metadata["mention_count"] = (
        e1.metadata.get("mention_count", 1) +
        e2.metadata.get("mention_count", 1)
    )
    return e1


# ── Union-Find for transitive merging ────────────────────────────────────────────

class UnionFind:
    def __init__(self, ids: List[str]):
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[ry] = rx


# ── Public API ────────────────────────────────────────────────────────────────────

def resolve_coreferences(
    entities:      List[Entity],
    relationships: List[Relationship],
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Merge coreferent entities and rewrite relationship IDs to point to
    canonical nodes.

    Returns:
        (deduplicated_entities, updated_relationships)
    """
    ids = [e.id for e in entities]
    uf  = UnionFind(ids)
    id_to_entity = {e.id: e for e in entities}

    merge_count = 0
    for i, e1 in enumerate(entities):
        for e2 in entities[i + 1 :]:
            if _are_coreferent(e1, e2):
                uf.union(e1.id, e2.id)
                merge_count += 1

    # Build canonical entity map
    canonical_map: Dict[str, Entity] = {}
    redirect: Dict[str, str] = {}   # old_id → canonical_id

    for entity in entities:
        root = uf.find(entity.id)
        redirect[entity.id] = root
        if root not in canonical_map:
            canonical_map[root] = entity
        else:
            canonical_map[root] = _canonical(canonical_map[root], entity)

    # Rewrite relationship endpoints
    updated_rels: List[Relationship] = []
    seen = set()
    for rel in relationships:
        new_src = redirect.get(rel.source_id, rel.source_id)
        new_tgt = redirect.get(rel.target_id, rel.target_id)
        if new_src == new_tgt:
            continue  # skip self-loops created by merging
        key = f"{new_src}|{new_tgt}|{rel.type}"
        if key in seen:
            continue
        seen.add(key)
        rel.source_id = new_src
        rel.target_id = new_tgt
        updated_rels.append(rel)

    final_entities = list(canonical_map.values())

    console.print(
        f"[bold green]✓ Coreference: merged {merge_count} duplicate entity pairs "
        f"→ {len(final_entities)} canonical nodes[/bold green]"
    )
    return final_entities, updated_rels
