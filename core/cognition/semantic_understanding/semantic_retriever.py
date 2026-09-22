"""Single-source hybrid semantic retrieval facade.

SemanticRetriever owns no database, FAISS index, or graph. When a
SemanticMemory instance is supplied, all persistent retrieval is delegated to
that existing substrate. Providers remain injectable for tests and future
neural/symbolic adapters.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

Provider = Callable[..., Iterable[Any]]


class SemanticRetriever:
    """Retrieve semantic evidence without creating a second memory system."""

    VERSION = "0.2.0"

    def __init__(self, *, semantic_memory: Optional[Any] = None,
                 exact_provider: Optional[Provider] = None,
                 vector_provider: Optional[Provider] = None,
                 graph_provider: Optional[Provider] = None) -> None:
        self.semantic_memory = semantic_memory
        self.exact_provider = exact_provider or self._memory_exact
        self.vector_provider = vector_provider or self._memory_vector
        self.graph_provider = graph_provider or self._memory_graph

    @staticmethod
    def _safe_call(provider: Optional[Provider], query: str, **kwargs: Any) -> List[Any]:
        if not callable(provider):
            return []
        try:
            result = provider(query, **kwargs)
        except TypeError:
            try:
                result = provider(query)
            except Exception:
                return []
        except Exception:
            return []
        try:
            return list(result or [])
        except TypeError:
            return []

    def _memory_exact(self, query: str, *, limit: int = 8, **_: Any) -> List[Any]:
        if self.semantic_memory is None or not hasattr(self.semantic_memory, "search"):
            return []
        return self.semantic_memory.search(query, limit=limit)

    def _memory_vector(self, query: str, *, limit: int = 8,
                       similarity_threshold: float = 0.70,
                       max_candidate_cap: Optional[int] = None,
                       **_: Any) -> List[Any]:
        if self.semantic_memory is None or not hasattr(self.semantic_memory, "semantic_search"):
            return []
        cap = max(int(limit), int(max_candidate_cap or limit))
        return self.semantic_memory.semantic_search(
            query, similarity_threshold=similarity_threshold,
            max_candidate_cap=cap,
        )

    def _memory_graph(self, query: str, *, subjects: Optional[Iterable[str]] = None,
                      limit: int = 8, graph_limit: int = 5, **_: Any) -> List[Any]:
        del query
        if self.semantic_memory is None or not hasattr(self.semantic_memory, "get_graph_relations"):
            return []
        results: List[Any] = []
        seen = set()
        for raw_subject in subjects or ():
            subject = str(raw_subject).strip()
            if not subject or subject in seen:
                continue
            seen.add(subject)
            remaining = max(0, min(int(graph_limit), int(limit) - len(results)))
            if remaining == 0:
                break
            results.extend(self.semantic_memory.get_graph_relations(subject, max_limit=remaining))
        return results[:limit]

    @staticmethod
    def _subject_candidates(items: Iterable[Any]) -> List[str]:
        subjects: List[str] = []
        seen = set()
        for item in items:
            subject = getattr(item, "subject", None)
            if subject is None and isinstance(item, dict):
                subject = item.get("subject")
            if subject is not None:
                value = str(subject).strip()
                if value and value not in seen:
                    seen.add(value)
                    subjects.append(value)
        return subjects

    def retrieve(self, query: str, *, limit: int = 8,
                 similarity_threshold: float = 0.70,
                 max_candidate_cap: Optional[int] = None,
                 graph_limit: int = 5, **kwargs: Any) -> Dict[str, List[Any]]:
        limit = max(0, int(limit))
        if not query or limit == 0:
            return {"exact": [], "vector": [], "graph": []}

        exact = self._safe_call(self.exact_provider, query, limit=limit, **kwargs)[:limit]
        vector = self._safe_call(
            self.vector_provider, query, limit=limit,
            similarity_threshold=similarity_threshold,
            max_candidate_cap=max_candidate_cap, **kwargs,
        )[:limit]
        subjects = self._subject_candidates([*vector, *exact])
        graph = self._safe_call(
            self.graph_provider, query, subjects=subjects,
            limit=limit, graph_limit=graph_limit, **kwargs,
        )[:limit]
        return {"exact": exact, "vector": vector, "graph": graph}
