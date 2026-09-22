from __future__ import annotations

"""Formal GraphRAG retrieval pipeline (blueprint section 37).

    Query -> Entity Detection -> Graph Retrieval
        (direct facts, neighboring entities, multi-hop paths)
        -> Context Assembly -> [Native Reasoner / SLM / LLM]

Before this module, one-hop neighbor lookup already existed
(SemanticMemory.get_graph_relations, used implicitly inside
MemoryManager.build_context()) but there was no MULTI-HOP traversal
and no single named entry point matching the blueprint's own pipeline
shape. This module:

    1. Adds genuine multi-hop traversal (multi_hop_paths,
       multi_hop_lookup) using the same networkx graph that already
       exists -- no new storage, no new dependency.
    2. Gives the pipeline an explicit, orderable, testable entry point
       (graph_rag_retrieve) instead of leaving retrieval implicit.

Honest scope: entity detection here is a small deterministic heuristic
(_guess_subject), not a trained NER model -- this formalizes and
extends the RETRIEVAL step the blueprint describes; it does not add a
new NLU layer. Document retrieval and episodic evidence (also named in
section 37's pipeline) are out of scope here -- Document Knowledge
ingestion doesn't exist yet at all (see the roadmap), so there is
nothing to retrieve from that source yet.
"""

from collections import deque
from typing import Any, Dict, List, Optional


def multi_hop_paths(semantic_memory: Any, start_subject: str, max_hops: int = 2, max_paths: int = 8) -> List[List[Dict[str, Any]]]:
    """BFS traversal beyond the existing 1-hop neighbor lookup.

    Returns a list of paths; each path is a list of hop dicts
    {subject, predicate, target}, in traversal order, so a 2-hop path
    reads as [hop1, hop2] with hop1["target"] == hop2["subject"].
    """
    graph = getattr(semantic_memory, "graph", None)
    if graph is None:
        return []
    subject = semantic_memory._normalize(start_subject) if hasattr(semantic_memory, "_normalize") else str(start_subject).strip().lower()
    if subject not in graph:
        return []

    paths: List[List[Dict[str, Any]]] = []
    seen_path_keys = set()
    queue = deque([(subject, [])])
    while queue and len(paths) < max_paths:
        current, path_so_far = queue.popleft()
        if len(path_so_far) >= max_hops:
            continue
        for neighbor in graph.successors(current):
            edge_data = graph.get_edge_data(current, neighbor) or {}
            hop = {"subject": current, "predicate": edge_data.get("predicate", "related_to"), "target": neighbor}
            new_path = path_so_far + [hop]
            path_key = tuple((h["subject"], h["predicate"], h["target"]) for h in new_path)
            if path_key in seen_path_keys:
                continue
            seen_path_keys.add(path_key)
            paths.append(new_path)
            if len(new_path) < max_hops:
                queue.append((neighbor, new_path))
            if len(paths) >= max_paths:
                break
    return paths


def multi_hop_lookup(semantic_memory: Any, start_subject: str, predicate_chain: List[str]) -> Optional[str]:
    """Deterministic chained lookup: follow predicate_chain hop by hop.

    E.g. start_subject="user", predicate_chain=["works_on", "contains"]
    resolves USER --works_on--> X, then X --contains--> Y, returning Y.
    This is exactly the blueprint section 27 example
    ("mera project kya hai?" via native graph traversal) generalized
    to more than one hop.
    """
    current = start_subject
    for predicate in predicate_chain:
        try:
            facts = semantic_memory.find(subject=current, predicate=predicate)
        except Exception:
            return None
        if not facts:
            return None
        current = str(facts[0].value)
    return current


def _guess_subject(query: str) -> Optional[str]:
    """Small deterministic entity-detection heuristic -- not NER."""
    text = f" {(query or '').lower()} "
    if any(word in text for word in (" mera ", " meri ", " mujhe ", " mere ")) or text.strip().startswith("my "):
        return "user"
    if "jarvis" in text:
        return "jarvis"
    if "project" in text:
        return "project"
    return None


def graph_rag_retrieve(
    memory_manager: Any,
    query: str,
    entity_hint: Optional[str] = None,
    max_hops: int = 2,
    max_neighbors: int = 5,
    max_paths: int = 8,
) -> Dict[str, Any]:
    """The formal pipeline entry point. Returns a structured context
    dict (direct facts, one-hop neighbors, multi-hop paths) ready for
    Context Assembly by NativeReasoner / SLM / LLM -- see
    core/cognition/native_reasoner.py for the consumer side.
    """
    semantic = getattr(memory_manager, "semantic", memory_manager)
    if semantic is None or not hasattr(semantic, "find"):
        return {"entity": None, "direct_facts": [], "neighboring_entities": [], "multi_hop_paths": []}

    subject_guess = entity_hint or _guess_subject(query)
    if not subject_guess:
        return {"entity": None, "direct_facts": [], "neighboring_entities": [], "multi_hop_paths": []}

    try:
        direct_facts = semantic.find(subject=subject_guess)
    except Exception:
        direct_facts = []
    try:
        neighbors = semantic.get_graph_relations(subject_guess, max_limit=max_neighbors) if hasattr(semantic, "get_graph_relations") else []
    except Exception:
        neighbors = []
    try:
        paths = multi_hop_paths(semantic, subject_guess, max_hops=max_hops, max_paths=max_paths)
    except Exception:
        paths = []

    return {
        "entity": subject_guess,
        "direct_facts": [f.to_dict() if hasattr(f, "to_dict") else f for f in direct_facts],
        "neighboring_entities": neighbors,
        "multi_hop_paths": paths,
    }
