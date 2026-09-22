from __future__ import annotations

"""NativeReasoner -- unified, first-class native cognition capability
(blueprint section 27).

Before this module, JARVIS's zero-LLM-call answering capability was
scattered across ad-hoc functions called from different places in
brain.py: try_direct_recall_answer and try_identity_answer (see
core/orchestration/response_brief.py), each independently deciding
when to fire. This module gives them one shared home, one shared
tracing shape (which resolver answered and why), and adds a genuine
NEW capability the blueprint explicitly names as an example: multi-hop
graph traversal ("USER --works_on--> JARVIS, JARVIS --contains-->
SemanticMemory" answering "mera project ka memory system kya hai?"
without any LLM call).

Resolvers run in a fixed, cheapest-first order and stop at the first
hit -- this is the same escalation discipline as the rest of the
pipeline (native before anything else), just now expressed as one
list instead of duplicated conditionals in Brain.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..orchestration.response_brief import (
    try_direct_recall_answer, try_identity_answer, try_self_awareness_answer, detect_recall_miss,
    _ASK_WORD_TO_PREDICATE, _RECALL_PATTERNS,
)
from .meta_awareness import (
    try_architecture_answer, try_live_status_answer, try_workflow_narration_answer,
    try_self_diagnostic_answer, try_confidence_answer, try_calibration_answer,
)
from ..memory.graph_rag import multi_hop_lookup
from ..orchestration.slm_bridge import try_classify_predicate


@dataclass
class NativeAnswer:
    text: str
    resolver: str  # which resolver produced it -- feeds dependency_metrics' answered_by


# "mera project ka X kya hai" / "mera project ki X kya hai" -- a 2-hop
# question chain: USER --works_on--> <project> --X--> <value>.
_PROJECT_ATTRIBUTE_PATTERN = re.compile(r"\bmera\s+project\s+k[ai]\s+(.+?)\s+kya\s+hai\b", re.I)


class NativeReasoner:
    """Consolidated native (zero-LLM-cost) answering capability.

    Usage: `reasoner.try_answer(user_input, context, speaker_name=...)`
    returns a NativeAnswer or None. None means "no native resolver
    could handle this turn" -- the caller (Brain) falls through to
    the router/LLM cascade exactly as before; nothing here ever blocks
    or degrades the existing pipeline, it only adds fast, free hits.
    """

    def __init__(self, memory_manager: Any = None, identity_system: Any = None, llm_bridge: Any = None, brain: Any = None, native_response_learner: Any = None):
        self.memory = memory_manager
        self.identity = identity_system
        self.llm_bridge = llm_bridge
        self.brain = brain
        # UK's #5: repeated, consistently-grounded small talk gets
        # answered from a learned template instead of the LLM. See
        # core/learning/native_response_learning.py's module docstring
        # for why this is restricted to a narrow, non-fact intent
        # allowlist -- it must never risk serving a stale personal fact.
        self.native_response_learner = native_response_learner

    def _try_improvement_request(self, user_input: str) -> Optional[str]:
        """UK explicitly telling JARVIS "this is a bug" / "I want this
        feature" -- recorded durably and honestly acknowledged (see
        core/learning/improvement_requests.py's module docstring for
        the full honest-scope explanation: narrow vocabulary asks get
        genuinely sandbox-tested; anything broader is recorded and
        surfaced for Claude/a developer, not silently attempted)."""
        try:
            from ..learning.improvement_requests import is_improvement_request, ImprovementRequestStore, honest_acknowledgement
        except Exception:
            return None
        if not is_improvement_request(user_input):
            return None
        store = ImprovementRequestStore(memory=self.memory)
        entry = store.record(user_input)
        return honest_acknowledgement(entry)

    def try_answer(self, user_input: str, context: Dict[str, Any], speaker_name: Optional[str] = None) -> Optional[NativeAnswer]:
        for resolver_name, resolver in (
            ("learned_template", lambda: self._try_learned_template(user_input)),
            ("direct_recall", lambda: try_direct_recall_answer(user_input, context, on_hit=self._reinforce_recalled_fact)),
            ("embedding_recall", lambda: self._try_embedding_recall(user_input)),
            ("slm_assisted_recall", lambda: self._try_slm_assisted_recall(user_input, context)),
            ("graph_multi_hop", lambda: self._try_graph_multi_hop(user_input)),
            ("identity", lambda: try_identity_answer(user_input, self.identity, speaker_name=speaker_name)),
            ("self_awareness", lambda: try_self_awareness_answer(user_input, self.brain)),
            # UK's "talk to brain.py directly" ask: five more zero-LLM-
            # cost introspection resolvers, ordered narrowest-trigger
            # first so each gets a clean shot before falling through.
            ("architecture_self_description", lambda: try_architecture_answer(user_input, self.brain)),
            ("live_status", lambda: try_live_status_answer(user_input, self.brain)),
            ("workflow_narration", lambda: try_workflow_narration_answer(user_input, self.brain)),
            ("self_diagnostic", lambda: try_self_diagnostic_answer(user_input, self.brain)),
            ("confidence_report", lambda: try_confidence_answer(user_input, self.brain)),
            ("calibration_report", lambda: try_calibration_answer(user_input, self.brain)),
            ("improvement_request", lambda: self._try_improvement_request(user_input)),
        ):
            try:
                result = resolver()
            except Exception:
                result = None
            if result is not None:
                return NativeAnswer(text=result, resolver=resolver_name)
        return None

    def _try_learned_template(self, user_input: str) -> Optional[str]:
        """Exact-match lookup only -- see native_response_learning.py's
        module docstring for the full safety reasoning. The mining
        step already enforced "safe intent + repeated + grounded";
        this side only needs to match text, never re-derive intent."""
        if self.native_response_learner is None:
            return None
        try:
            return self.native_response_learner.match(user_input)
        except Exception:
            return None

    def _reinforce_recalled_fact(self, item: Any) -> None:
        """Spaced-repetition-inspired reinforcement (the 'testing
        effect' from memory psychology: retrieval strengthens a
        memory more than passive storage does). SemanticMemory had
        .reinforce()/.weaken() built already but nothing ever called
        them -- this is the actual wiring. Deliberately a SMALL delta
        (0.03, not the method's 0.1 default) since this fires on
        every single recall hit, potentially many times a day; a
        strong delta would saturate confidence to 1.0 almost
        immediately and stop meaning anything."""
        semantic = getattr(self.memory, "semantic", self.memory)
        if semantic is None or not hasattr(semantic, "reinforce"):
            return
        knowledge_id = item.get("knowledge_id") if isinstance(item, dict) else getattr(item, "knowledge_id", None)
        if knowledge_id:
            semantic.reinforce(knowledge_id, confidence_delta=0.03)

    # Visibility counters for UK's #4 proposal -- monitor.py reads
    # these via NativeReasoner.embedding_recall_stats().
    _embedding_recall_hits = 0
    _embedding_recall_misses = 0

    def _try_embedding_recall(self, user_input: str) -> Optional[str]:
        """Neuro-symbolic recall (UK's #4 recall/learning/memory
        proposal): only reached when the exact regex-based
        direct_recall found NOTHING for this same narrow "what is my
        X" phrasing -- so a paraphrase/synonym ("meri saheli kaha
        rehti hai" instead of the exact word "girlfriend") can still
        recall the right fact via embedding similarity, without
        touching the reliable exact-match path at all.

        Two conservative safety gates, because an embedding match is
        fundamentally a GUESS about meaning, not a literal lookup:
          1. top match must clear a high similarity floor (0.72)
          2. top match must lead the second-best candidate by a clear
             margin (0.08) -- an ambiguous case is left unanswered
             (falls through to the LLM route) rather than guessed.
        """
        if self.memory is None:
            return None
        semantic = getattr(self.memory, "semantic", None)
        if semantic is None or not hasattr(semantic, "semantic_search_scored"):
            return None
        text = (user_input or "").strip()
        if not text or len(text) > 80:
            return None
        # Must still look like a recall QUESTION -- reuse the exact
        # same narrow phrasing gate direct_recall uses, so this never
        # fires on an ordinary statement.
        if not any(pattern.search(text) for pattern in _RECALL_PATTERNS):
            return None
        try:
            results = semantic.semantic_search_scored(text, similarity_threshold=0.55, top_k=3)
        except Exception:
            return None
        if not results:
            NativeReasoner._embedding_recall_misses += 1
            return None
        results.sort(key=lambda pair: pair[1], reverse=True)
        top_item, top_score = results[0]
        if top_score < 0.72:
            NativeReasoner._embedding_recall_misses += 1
            return None
        if len(results) > 1:
            _, second_score = results[1]
            if (top_score - second_score) < 0.08:
                NativeReasoner._embedding_recall_misses += 1
                return None  # too ambiguous -- don't guess
        value = getattr(top_item, "value", None)
        predicate = str(getattr(top_item, "predicate", "") or "").replace("_", " ")
        if not value:
            NativeReasoner._embedding_recall_misses += 1
            return None
        self._reinforce_recalled_fact(top_item)
        NativeReasoner._embedding_recall_hits += 1
        return f"Aapka {predicate} {value} hai. (paraphrase se match kiya, exact wording nahi thi)"

    @classmethod
    def embedding_recall_stats(cls) -> Dict[str, int]:
        return {"hits": cls._embedding_recall_hits, "misses": cls._embedding_recall_misses}

    def _try_slm_assisted_recall(self, user_input: str, context: Dict[str, Any]) -> Optional[str]:
        """SLM tier (blueprint LEVEL 4/5) -- see core/orchestration/
        slm_bridge.py. Only fires for the specific gap direct_recall
        already detects (question shape matched, predicate word
        didn't). Uses the LOCAL model ONLY, never the cloud/full LLM
        path, and only ever narrows down to an already-known predicate
        -- it cannot introduce a fact that wasn't already stored."""
        if self.llm_bridge is None:
            return None
        unresolved = detect_recall_miss(user_input, context)
        if not unresolved:
            return None
        known_predicates = list(_ASK_WORD_TO_PREDICATE.values())
        classified = try_classify_predicate(self.llm_bridge, unresolved, known_predicates)
        if not classified:
            return None
        for item in context.get("relevant_knowledge") or []:
            get = (lambda k: getattr(item, k, None)) if not isinstance(item, dict) else item.get
            if str(get("predicate") or "").lower() == classified:
                value = get("value")
                if value:
                    return f"Aapka {unresolved} {value} hai. (SLM ne '{unresolved}' ko '{classified}' se match kiya.)"
        return None

    def _try_graph_multi_hop(self, user_input: str) -> Optional[str]:
        """The blueprint section 27 example, generalized: a 2-hop chain
        starting from the user's own project relation. Deliberately
        narrow (one specific phrasing pattern) -- this is a genuine new
        capability, not a general graph-QA system; it extends exactly
        as far as it can be verified to answer correctly."""
        match = _PROJECT_ATTRIBUTE_PATTERN.search(user_input or "")
        if not match or self.memory is None:
            return None
        semantic = getattr(self.memory, "semantic", self.memory)
        if semantic is None or not hasattr(semantic, "find"):
            return None
        attribute_phrase = match.group(1).strip()
        predicate_guess = attribute_phrase.lower().replace(" ", "_")
        value = multi_hop_lookup(semantic, "user", ["works_on", predicate_guess])
        if not value:
            return None
        return f"Aapke project ka {attribute_phrase} {value} hai."
