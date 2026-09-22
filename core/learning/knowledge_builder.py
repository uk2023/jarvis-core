from __future__ import annotations

import time
import uuid

from typing import Any, Dict, List, Optional


class KnowledgeBuilder:
    """
    Knowledge extraction organ of JARVIS.

    Converts evaluated experiences into structured,
    traceable knowledge candidates.

    Flow:

        Experience
             ↓
        SelfEvaluator
             ↓
        KnowledgeBuilder
             ↓
        Knowledge Candidate
             ↓
        accept()
             ↓
        MemoryManager.remember_knowledge()
             ↓
        SemanticMemory
             ↓
        SQLite persistence

    Important:

        build() NEVER writes directly into trusted semantic memory.

        Knowledge remains a CANDIDATE until explicitly accepted.

    This organ does NOT:

        - modify source code
        - modify personality
        - execute actions
        - invent external facts
        - automatically trust failed experiences
    """

    VERSION = "0.3.0"

    def __init__(
        self,
        event_bus=None,
        internal_state=None,
        memory_manager=None,
    ):
        self.events = event_bus
        self.state = internal_state
        self.memory = memory_manager

        # ---------------------------------------------------------
        # Statistics
        # ---------------------------------------------------------

        self.built_count = 0
        self.accepted_count = 0
        self.rejected_count = 0

        # ---------------------------------------------------------
        # Candidate storage
        # ---------------------------------------------------------

        self.knowledge: Dict[
            str,
            Dict[str, Any],
        ] = {}

        # ---------------------------------------------------------
        # Runtime metadata
        # ---------------------------------------------------------

        self.created_at = time.time()
        self.updated_at = self.created_at

        self.last_knowledge: Optional[
            Dict[str, Any]
        ] = None

        self.last_built_at: Optional[
            float
        ] = None

    # =============================================================
    # BUILD KNOWLEDGE CANDIDATE
    # =============================================================

    def build(
        self,
        experience: Dict[str, Any],
        evaluation: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Convert a successful evaluated experience into a
        structured knowledge candidate.

        No trusted semantic memory is modified here.
        """

        if not isinstance(
            experience,
            dict,
        ):
            raise TypeError(
                "experience must be a dictionary"
            )

        evaluation = (
            evaluation
            if isinstance(
                evaluation,
                dict,
            )
            else {}
        )

        # ---------------------------------------------------------
        # Determine reliability
        # ---------------------------------------------------------

        success = self._determine_success(
            experience,
            evaluation,
        )

        score = self._get_score(
            evaluation,
            experience,
        )

        # ---------------------------------------------------------
        # Reliability gate
        # ---------------------------------------------------------

        if not success or score < 0.5:

            self.rejected_count += 1
            self.updated_at = time.time()

            self._emit(
                "KNOWLEDGE_REJECTED",
                {
                    "reason": (
                        "EXPERIENCE_NOT_RELIABLE"
                    ),
                    "score": score,
                    "success": success,
                },
            )

            return None

        # ---------------------------------------------------------
        # Extract experience components
        # ---------------------------------------------------------

        event_type = str(
            experience.get(
                "event_type",
                "UNKNOWN",
            )
        ).strip()

        context = (
            experience.get(
                "context"
            )
            or {}
        )

        action = (
            experience.get(
                "action"
            )
            or {}
        )

        outcome = (
            experience.get(
                "outcome"
            )
            or {}
        )

        # ---------------------------------------------------------
        # Safety: expected structures
        # ---------------------------------------------------------

        if not isinstance(
            context,
            dict,
        ):
            context = {}

        if not isinstance(
            action,
            dict,
        ):
            action = {}

        if not isinstance(
            outcome,
            dict,
        ):
            outcome = {}

        # ---------------------------------------------------------
        # Extract semantic structure
        # ---------------------------------------------------------

        semantic = self._extract_semantic_fact(
            event_type=event_type,
            context=context,
            action=action,
            outcome=outcome,
        )

        if semantic is None:

            self.rejected_count += 1
            self.updated_at = time.time()

            self._emit(
                "KNOWLEDGE_REJECTED",
                {
                    "reason": (
                        "NO_STRUCTURED_FACT"
                    ),
                    "event_type": event_type,
                },
            )

            return None

        subject = semantic["subject"]
        predicate = semantic["predicate"]
        value = semantic["value"]

        # ---------------------------------------------------------
        # Defense-in-depth plausibility gate.
        #
        # _extract_semantic_fact() above sources triples from several
        # places -- explicit outcome/context fields, Semantic
        # Understanding's own relations, or a conservative action/
        # outcome fallback. Semantic Understanding already runs its own
        # plausibility gate (SemanticUnderstandingEngine._is_plausible_fact)
        # before it EVER yields a relation, but this is the single choke
        # point every path through this class passes before a triple is
        # written to the CANDIDATE knowledge store, so it is checked
        # again here independently. This is what actually stops a
        # triple like favourite -> "hai. but javascript pe aur react
        # html ye sb b ata" from reaching storage even if a future
        # caller feeds context/outcome fields directly, bypassing
        # Semantic Understanding entirely.
        # ---------------------------------------------------------

        if not self._is_plausible_triple(subject, predicate, value):

            self.rejected_count += 1
            self.updated_at = time.time()

            self._emit(
                "KNOWLEDGE_REJECTED",
                {
                    "reason": "IMPLAUSIBLE_FACT_SHAPE",
                    "event_type": event_type,
                    "subject": str(subject)[:80],
                    "predicate": str(predicate)[:80],
                    "value": str(value)[:120],
                },
            )

            return None

        # ---------------------------------------------------------
        # Classify knowledge
        # ---------------------------------------------------------

        knowledge_type = self._classify_type(
            event_type=event_type,
            context=context,
            action=action,
            outcome=outcome,
        )

        # ---------------------------------------------------------
        # Confidence
        # ---------------------------------------------------------

        confidence = self._calculate_confidence(
            evaluation=evaluation,
            experience=experience,
        )

        # ---------------------------------------------------------
        # Importance
        # ---------------------------------------------------------

        importance = self._calculate_importance(
            experience=experience,
            evaluation=evaluation,
        )

        # ---------------------------------------------------------
        # Tags
        # ---------------------------------------------------------

        tags = self._build_tags(
            event_type=event_type,
            knowledge_type=knowledge_type,
            context=context,
            outcome=outcome,
        )

        # ---------------------------------------------------------
        # Candidate ID
        # ---------------------------------------------------------

        knowledge_id = str(
            uuid.uuid4()
        )

        now = time.time()

        # ---------------------------------------------------------
        # Candidate
        # ---------------------------------------------------------

        candidate = {
            "id": knowledge_id,

            "version": self.VERSION,

            "type": (
                "KNOWLEDGE_CANDIDATE"
            ),

            "knowledge_type": knowledge_type,

            # -----------------------------------------------------
            # SemanticMemory-compatible structure
            # -----------------------------------------------------

            "subject": subject,

            "predicate": predicate,

            "value": value,

            "confidence": confidence,

            "importance": importance,

            "source": (
                f"experience:{event_type}"
            ),

            "tags": tags,

            # -----------------------------------------------------
            # Traceability
            # -----------------------------------------------------

            "source_experience": experience,

            "source_evaluation": evaluation,

            # -----------------------------------------------------
            # Lifecycle
            # -----------------------------------------------------

            "status": "CANDIDATE",

            "created_at": now,

            "updated_at": now,
        }

        self.knowledge[
            knowledge_id
        ] = candidate

        self.built_count += 1

        self.last_knowledge = candidate

        self.last_built_at = now

        self.updated_at = now

        self._emit(
            "KNOWLEDGE_BUILT",
            candidate,
        )

        # Process any ADDITIONAL relations from the SAME turn's semantic
        # understanding. THE ACTUAL BUG THIS FIXES: step "3.5" above (a
        # few lines up) already correctly reads context["semantic"]
        # ["relations"] -- the multi-fact extraction fix made earlier
        # this session genuinely produces a full LIST of relations when
        # a message states more than one fact -- but this method still
        # only ever converted the FIRST one into a candidate and
        # silently dropped the rest, every single time. A message like
        # "meri favourite hobby coding hai aur meri favourite sport
        # cricket hai" extracted BOTH facts correctly, but only ever
        # got as far as storing one of them. Reusing this same build()
        # method recursively (with the next relation forced into
        # outcome directly, so step 1 matches immediately without
        # re-scanning the relations list) means every additional fact
        # goes through the exact same confidence/importance/tags/
        # classification logic as the first, not a separate, untested
        # path.
        additional_candidate_ids: List[str] = []
        semantic_ctx = context.get("semantic")
        if isinstance(semantic_ctx, dict):
            relations = semantic_ctx.get("relations")
            if isinstance(relations, list) and len(relations) > 1:
                used_triple = (str(subject), str(predicate))
                seen = {used_triple}
                for relation in relations:
                    if not isinstance(relation, dict):
                        continue
                    if not all(key in relation for key in ("subject", "predicate", "value")):
                        continue
                    rel_subject = str(relation["subject"]).strip()
                    rel_predicate = str(relation["predicate"]).strip()
                    if not rel_subject or not rel_predicate:
                        continue
                    key = (rel_subject, rel_predicate)
                    if key in seen:
                        continue
                    seen.add(key)
                    forced_outcome = dict(outcome)
                    forced_outcome["subject"] = rel_subject
                    forced_outcome["predicate"] = rel_predicate
                    forced_outcome["value"] = relation["value"]
                    # THE ACTUAL BUG (found via a real, observed
                    # evidence_count explosion: 66 -> 153 -> 253 for a
                    # single fact, discovered by testing this exact
                    # scenario): the recursive build() call below used
                    # to receive the SAME context, unchanged -- so
                    # INSIDE that recursive call, its OWN copy of this
                    # same loop scanned context["semantic"]["relations"]
                    # again, found the ORIGINAL (now-"other") relation
                    # not yet in ITS fresh `seen` set, and recursively
                    # called build() for THAT one -- which then found
                    # THIS one not yet seen, and so on, back and forth,
                    # until Python's recursion limit was hit and
                    # silently swallowed by the except below. Directly
                    # measured: build() was invoked 498 times for what
                    # should have been exactly 2 relations. The fix:
                    # strip "semantic" from the context passed to the
                    # recursive call, so its own scan-for-additional-
                    # relations step finds nothing and terminates after
                    # building exactly the one candidate it was asked
                    # to build.
                    forced_context = {k: v for k, v in context.items() if k != "semantic"}
                    try:
                        sibling = self.build(
                            experience={**experience, "context": forced_context, "action": action, "outcome": forced_outcome},
                            evaluation=evaluation,
                        )
                    except Exception:
                        sibling = None
                    if isinstance(sibling, dict) and sibling.get("id"):
                        additional_candidate_ids.append(sibling["id"])
        if additional_candidate_ids:
            candidate["additional_candidates"] = additional_candidate_ids

        return candidate

    # =============================================================
    # ACCEPT
    # =============================================================

    def accept(
        self,
        knowledge_id: str,
    ) -> Dict[str, Any]:
        """
        Accept a knowledge candidate.

        ONLY HERE does the candidate enter SemanticMemory.

        MemoryManager then persists it into SQLite.
        """

        knowledge = self._get(
            knowledge_id
        )

        # ---------------------------------------------------------
        # Already processed
        # ---------------------------------------------------------

        if knowledge["status"] != "CANDIDATE":
            return knowledge

        # ---------------------------------------------------------
        # MemoryManager required
        # ---------------------------------------------------------

        if self.memory is None:

            raise RuntimeError(
                "MemoryManager is required "
                "to accept knowledge."
            )

        # ---------------------------------------------------------
        # Write into semantic memory
        # ---------------------------------------------------------

        # Bug 15 fix (2026-09-11 trace-log audit): a malformed
        # extraction ("user.paas=nahin" -- a fragment of "paas nahi"/
        # "don't have", mis-parsed into a fake subject.predicate=value
        # triple) was reaching permanent storage with nothing checking
        # whether what got extracted is actually a coherent fact.
        # This is the ONE chokepoint every candidate passes through
        # before persisting (see the docstring above), so it's the
        # correct place for a lightweight sanity gate -- deliberately
        # conservative (only rejects clear fragments/stopwords-as-
        # values, never guesses at "is this a REAL fact" beyond that)
        # so it doesn't accidentally block legitimate short facts.
        _JUNK_TOKENS = {
            "nahi", "nahin", "haan", "han", "hai", "hain", "tha", "thi", "the",
            "ka", "ki", "ke", "ko", "se", "me", "mein", "bhi", "hi", "to", "toh", "na",
        }
        predicate_str = str(knowledge.get("predicate", "")).strip().lower()
        value_str = str(knowledge.get("value", "")).strip().lower()
        if predicate_str in _JUNK_TOKENS or value_str in _JUNK_TOKENS or len(predicate_str) < 2 or len(value_str) < 1:
            knowledge["status"] = "REJECTED_MALFORMED"
            knowledge["rejection_reason"] = f"predicate/value looks like a sentence fragment, not a fact: predicate={predicate_str!r} value={value_str!r}"
            return knowledge

        semantic_knowledge = (
            self.memory.remember_knowledge(
                subject=knowledge[
                    "subject"
                ],
                predicate=knowledge[
                    "predicate"
                ],
                value=knowledge[
                    "value"
                ],
                confidence=knowledge[
                    "confidence"
                ],
                importance=knowledge[
                    "importance"
                ],
                source=knowledge[
                    "source"
                ],
                tags=knowledge[
                    "tags"
                ],
            )
        )

        # ---------------------------------------------------------
        # Candidate lifecycle
        # ---------------------------------------------------------

        now = time.time()

        knowledge["status"] = "ACCEPTED"

        knowledge["accepted_at"] = now

        knowledge["updated_at"] = now

        knowledge[
            "semantic_knowledge_id"
        ] = (
            semantic_knowledge.knowledge_id
        )

        self.accepted_count += 1

        self.updated_at = now

        self._emit(
            "KNOWLEDGE_ACCEPTED",
            {
                "candidate": knowledge,
                "semantic_knowledge": (
                    semantic_knowledge.to_dict()
                ),
            },
        )

        return knowledge

    # =============================================================
    # REJECT
    # =============================================================

    def reject(
        self,
        knowledge_id: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Reject a knowledge candidate.

        Rejected knowledge never enters SemanticMemory.
        """

        knowledge = self._get(
            knowledge_id
        )

        # ---------------------------------------------------------
        # Already processed
        # ---------------------------------------------------------

        if knowledge["status"] != "CANDIDATE":
            return knowledge

        now = time.time()

        knowledge["status"] = "REJECTED"

        knowledge[
            "rejection_reason"
        ] = str(reason)

        knowledge["rejected_at"] = now

        knowledge["updated_at"] = now

        self.rejected_count += 1

        self.updated_at = now

        self._emit(
            "KNOWLEDGE_REJECTED",
            knowledge,
        )

        return knowledge

    # =============================================================
    # SEMANTIC EXTRACTION
    # =============================================================

    @staticmethod
    def _is_plausible_triple(subject: Any, predicate: Any, value: Any) -> bool:
        """Reject subject/predicate/value shapes that look like a mis-split
        sentence fragment rather than an actual fact, independent of
        which extraction path produced them. Mirrors (but does not
        import, to keep this organ dependency-light per this class's
        own module docstring) the checks in
        SemanticUnderstandingEngine._is_plausible_fact."""

        import re as _re

        subject_text = str(subject or "").strip()
        predicate_text = str(predicate or "").strip()
        value_text = str(value or "").strip()

        if not subject_text or not predicate_text or not value_text:
            return False

        # A sentence terminator followed by more text means the value
        # bled past the end of the intended statement into the next one.
        if _re.search(r"[.!?]\s*\S", value_text):
            return False

        if len(value_text) > 120:
            return False

        filler_words = {
            "kya", "batao", "bataye", "bataiye", "lekin", "but",
            "abhi", "pehle", "phla", "toh", "ok", "okay", "acha",
        }
        value_words = {w.strip(".,!?").lower() for w in value_text.split()}
        if value_words & filler_words:
            return False
        predicate_words = {w.lower() for w in _re.split(r"[_\s]+", predicate_text) if w}
        if predicate_words & filler_words:
            return False

        return True

    @staticmethod
    def _extract_semantic_fact(
        event_type: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Extract a conservative subject/predicate/value triple.

        Priority:

            1. Explicit semantic fields in outcome
            2. Explicit semantic fields in context
            3. Explicit knowledge object
            4. Structured action/outcome relationship

        No external knowledge is invented.
        """

        # ---------------------------------------------------------
        # 1. Explicit semantic fact in outcome
        # ---------------------------------------------------------

        if all(
            key in outcome
            for key in (
                "subject",
                "predicate",
                "value",
            )
        ):

            subject = str(
                outcome["subject"]
            ).strip()

            predicate = str(
                outcome["predicate"]
            ).strip()

            if subject and predicate:

                return {
                    "subject": subject,
                    "predicate": predicate,
                    "value": outcome[
                        "value"
                    ],
                }

        # ---------------------------------------------------------
        # 2. Explicit semantic fact in context
        # ---------------------------------------------------------

        if all(
            key in context
            for key in (
                "subject",
                "predicate",
                "value",
            )
        ):

            subject = str(
                context["subject"]
            ).strip()

            predicate = str(
                context["predicate"]
            ).strip()

            if subject and predicate:

                return {
                    "subject": subject,
                    "predicate": predicate,
                    "value": context[
                        "value"
                    ],
                }

        # ---------------------------------------------------------
        # 3. Explicit knowledge object
        # ---------------------------------------------------------

        explicit = outcome.get(
            "knowledge"
        )

        if isinstance(
            explicit,
            dict,
        ):

            if all(
                key in explicit
                for key in (
                    "subject",
                    "predicate",
                    "value",
                )
            ):

                subject = str(
                    explicit["subject"]
                ).strip()

                predicate = str(
                    explicit["predicate"]
                ).strip()

                if subject and predicate:

                    return {
                        "subject": subject,
                        "predicate": predicate,
                        "value": explicit[
                            "value"
                        ],
                    }

        # ---------------------------------------------------------
        # 3.5. Semantic Understanding relations (ordinary chat turns)
        #
        # A normal USER_CHAT experience never has subject/predicate/
        # value at the top level of context/outcome -- the Semantic
        # Understanding layer already extracts exactly that structure
        # into context["semantic"]["relations"], but nothing here was
        # ever looking at it. That gap meant every ordinary "remember
        # X" style statement got rejected as NO_STRUCTURED_FACT and
        # only ever survived as raw episodic chat log text (which
        # ages out once it leaves the recent-experiences window),
        # never as a durable knowledge-graph fact. Use the first
        # relation Semantic Understanding found, if any.
        # ---------------------------------------------------------

        semantic_ctx = context.get("semantic")

        if isinstance(semantic_ctx, dict):

            relations = semantic_ctx.get("relations")

            if isinstance(relations, list):

                for relation in relations:

                    if not isinstance(relation, dict):
                        continue

                    if not all(
                        key in relation
                        for key in ("subject", "predicate", "value")
                    ):
                        continue

                    subject = str(relation["subject"]).strip()
                    predicate = str(relation["predicate"]).strip()

                    if subject and predicate:

                        return {
                            "subject": subject,
                            "predicate": predicate,
                            "value": relation["value"],
                        }

        # ---------------------------------------------------------
        # 4. Conservative action/outcome fallback
        # ---------------------------------------------------------

        if action and outcome:

            subject = action.get(
                "subject"
            )

            predicate = action.get(
                "predicate"
            )

            value = outcome.get(
                "value"
            )

            if (
                subject is not None
                and predicate is not None
                and value is not None
            ):

                subject = str(
                    subject
                ).strip()

                predicate = str(
                    predicate
                ).strip()

                if subject and predicate:

                    return {
                        "subject": subject,
                        "predicate": predicate,
                        "value": value,
                    }

        return None

    # =============================================================
    # SUCCESS
    # =============================================================

    @staticmethod
    def _determine_success(
        experience: Dict[str, Any],
        evaluation: Dict[str, Any],
    ) -> bool:
        """
        Determine whether the experience is reliable enough
        to become a knowledge candidate.
        """

        if "success" in evaluation:

            return bool(
                evaluation["success"]
            )

        if "success" in experience:

            return bool(
                experience["success"]
            )

        outcome = (
            experience.get(
                "outcome"
            )
            or {}
        )

        if isinstance(
            outcome,
            dict,
        ) and "success" in outcome:

            return bool(
                outcome["success"]
            )

        return True

    # =============================================================
    # SCORE
    # =============================================================

    @staticmethod
    def _get_score(
        evaluation: Dict[str, Any],
        experience: Dict[str, Any],
    ) -> float:
        """
        Get normalized evaluation score [0, 1].
        """

        score = evaluation.get(
            "score"
        )

        if score is None:

            outcome = (
                experience.get(
                    "outcome"
                )
                or {}
            )

            if isinstance(
                outcome,
                dict,
            ):

                score = outcome.get(
                    "score"
                )

        if score is None:
            return 1.0

        try:

            return max(
                0.0,
                min(
                    1.0,
                    float(score),
                ),
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0.0

    # =============================================================
    # TYPE
    # =============================================================

    @staticmethod
    def _classify_type(
        event_type: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> str:
        """
        Classify the type of extracted knowledge.
        """

        event = str(
            event_type
        ).upper()

        if "TASK" in event:
            return "TASK_KNOWLEDGE"

        if "ROUTE" in event:
            return "ROUTING_KNOWLEDGE"

        if "ERROR" in event:
            return "ERROR_KNOWLEDGE"

        if "INTERACTION" in event:
            return "INTERACTION_KNOWLEDGE"

        if (
            context
            and action
            and outcome
        ):
            return "PROCEDURAL_KNOWLEDGE"

        return "EXPERIENTIAL_KNOWLEDGE"

    # =============================================================
    # CONFIDENCE
    # =============================================================

    @staticmethod
    def _calculate_confidence(
        evaluation: Dict[str, Any],
        experience: Dict[str, Any],
    ) -> float:
        """
        Calculate confidence in the candidate.
        """

        explicit = evaluation.get(
            "confidence"
        )

        if explicit is None:

            outcome = (
                experience.get(
                    "outcome"
                )
                or {}
            )

            if isinstance(
                outcome,
                dict,
            ):

                explicit = outcome.get(
                    "confidence"
                )

        if explicit is not None:

            try:

                return max(
                    0.0,
                    min(
                        1.0,
                        float(explicit),
                    ),
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        return KnowledgeBuilder._get_score(
            evaluation,
            experience,
        )

    # =============================================================
    # IMPORTANCE
    # =============================================================

    @staticmethod
    def _calculate_importance(
        experience: Dict[str, Any],
        evaluation: Dict[str, Any],
    ) -> float:
        """
        Calculate importance of the candidate.
        """

        explicit = experience.get(
            "importance"
        )

        if explicit is None:

            outcome = (
                experience.get(
                    "outcome"
                )
                or {}
            )

            if isinstance(
                outcome,
                dict,
            ):

                explicit = outcome.get(
                    "importance"
                )

        if explicit is None:

            explicit = evaluation.get(
                "importance"
            )

        if explicit is None:
            return 0.5

        try:

            return max(
                0.0,
                min(
                    1.0,
                    float(explicit),
                ),
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0.5

    # =============================================================
    # TAGS
    # =============================================================

    @staticmethod
    def _build_tags(
        event_type: str,
        knowledge_type: str,
        context: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> List[str]:
        """
        Build normalized tags for semantic retrieval.
        """

        tags = [
            "knowledge",
            "experience-derived",
            str(event_type).lower(),
            knowledge_type.lower(),
        ]

        if context:
            tags.append(
                "contextual"
            )

        if outcome:
            tags.append(
                "outcome-backed"
            )

        return list(
            dict.fromkeys(
                str(tag).strip().lower()
                for tag in tags
                if str(tag).strip()
            )
        )

    # =============================================================
    # GET
    # =============================================================

    def get(
        self,
        knowledge_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Return a candidate by ID.
        """

        return self.knowledge.get(
            knowledge_id
        )

    # =============================================================
    # INTERNAL GET
    # =============================================================

    def _get(
        self,
        knowledge_id: str,
    ) -> Dict[str, Any]:
        """
        Return candidate or raise KeyError.
        """

        knowledge = self.get(
            knowledge_id
        )

        if knowledge is None:

            raise KeyError(
                f"Unknown knowledge id: "
                f"{knowledge_id}"
            )

        return knowledge

    # =============================================================
    # LIST KNOWLEDGE
    # =============================================================

    def list_knowledge(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List knowledge candidates.

        Optional status:

            CANDIDATE
            ACCEPTED
            REJECTED
        """

        items = list(
            self.knowledge.values()
        )

        if status:

            status = str(
                status
            ).upper().strip()

            items = [
                item
                for item in items
                if item.get(
                    "status"
                ) == status
            ]

        items.sort(
            key=lambda item: item.get(
                "created_at",
                0,
            ),
            reverse=True,
        )

        return items[
            :max(0, int(limit))
        ]

    # =============================================================
    # CANDIDATES
    # =============================================================

    def pending(
        self,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Return candidates waiting for acceptance/rejection.
        """

        return self.list_knowledge(
            status="CANDIDATE",
            limit=limit,
        )

    # =============================================================
    # ACCEPT ALL RELIABLE CANDIDATES
    # =============================================================

    def accept_reliable(
        self,
        minimum_confidence: float = 0.7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Accept pending candidates that meet a confidence threshold.

        This method is still conservative:
        it only processes existing candidates and does not
        generate new knowledge.
        """

        threshold = max(
            0.0,
            min(
                1.0,
                float(
                    minimum_confidence
                ),
            ),
        )

        accepted = []

        candidates = self.pending(
            limit=limit
        )

        for candidate in candidates:

            confidence = float(
                candidate.get(
                    "confidence",
                    0.0,
                )
            )

            if confidence < threshold:
                continue

            try:

                accepted.append(
                    self.accept(
                        candidate["id"]
                    )
                )

            except Exception as exc:

                self._emit(
                    "KNOWLEDGE_ACCEPT_ERROR",
                    {
                        "knowledge_id": candidate.get(
                            "id"
                        ),
                        "error": str(exc),
                    },
                )

        return accepted

    # =============================================================
    # STATISTICS
    # =============================================================

    def statistics(self) -> Dict[str, Any]:
        """
        Return KnowledgeBuilder statistics.
        """

        candidate_count = 0
        accepted_count = 0
        rejected_count = 0

        for item in self.knowledge.values():

            status = item.get(
                "status"
            )

            if status == "CANDIDATE":
                candidate_count += 1

            elif status == "ACCEPTED":
                accepted_count += 1

            elif status == "REJECTED":
                rejected_count += 1

        return {
            "version": self.VERSION,

            "built": self.built_count,

            "accepted": self.accepted_count,

            "rejected": self.rejected_count,

            "stored_candidates": len(
                self.knowledge
            ),

            "pending": candidate_count,

            "accepted_candidates": (
                accepted_count
            ),

            "rejected_candidates": (
                rejected_count
            ),

            "last_built_at": (
                self.last_built_at
            ),

            "updated_at": self.updated_at,
        }

    # =============================================================
    # RESET
    # =============================================================

    def reset(self) -> None:
        """
        Clear runtime knowledge candidates and statistics.

        This does NOT clear SemanticMemory.
        """

        self.knowledge.clear()

        self.built_count = 0
        self.accepted_count = 0
        self.rejected_count = 0

        self.last_knowledge = None
        self.last_built_at = None

        self.updated_at = time.time()

        self._emit(
            "KNOWLEDGE_BUILDER_RESET",
            {
                "timestamp": self.updated_at,
            },
        )

    # =============================================================
    # EVENT BUS
    # =============================================================

    def _emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:
        """
        Safely publish KnowledgeBuilder events.
        """

        if self.events is None:
            return

        safe_emit = getattr(
            self.events,
            "safe_emit",
            None,
        )

        if callable(safe_emit):

            safe_emit(
                event_name,
                payload,
                source="knowledge_builder",
            )
            return

        emit = getattr(
            self.events,
            "emit",
            None,
        )

        if callable(emit):

            try:

                emit(
                    event_name,
                    payload,
                    source="knowledge_builder",
                )

            except Exception as exc:

                print(
                    "[KnowledgeBuilder "
                    f"Event Error] {exc}"
                )