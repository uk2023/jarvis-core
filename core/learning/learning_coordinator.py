from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class LearningCoordinator:
    """Central orchestration organ for controlled learning, proposals, and activation."""

    VERSION = "0.4.0"

    def __init__(self, evaluator=None, knowledge_builder=None, consolidator=None,
                 memory_manager=None, event_bus=None, internal_state=None,
                 skill_learner=None, skill_registry=None):
        self.evaluator = evaluator
        self.knowledge_builder = knowledge_builder
        self.consolidator = consolidator
        self.memory = memory_manager
        self.skill_learner = skill_learner
        self.skill_registry = skill_registry
        self.events = event_bus
        self.state = internal_state
        self.learning_count = self.evaluation_count = 0
        self.knowledge_build_count = self.knowledge_accept_count = 0
        self.knowledge_reject_count = self.consolidation_count = 0
        self.skill_observation_count = self.skill_proposal_count = 0
        self.skill_registration_count = 0
        self.last_learning_at: Optional[float] = None
        self.last_result: Optional[Dict[str, Any]] = None
        self.running = True

    def learn(self, experience: Dict[str, Any], auto_accept: bool = False) -> Dict[str, Any]:
        if not self.running:
            raise RuntimeError("LearningCoordinator is stopped.")
        if not isinstance(experience, dict):
            raise TypeError("experience must be a dictionary")
        started_at = time.time()
        result = {"type": "LEARNING_CYCLE", "success": False, "experience": experience,
                  "evaluation": None, "knowledge": None, "accepted": False,
                  "skill_proposals": [], "duration": 0.0, "timestamp": None}
        if self.evaluator is None:
            raise RuntimeError("SelfEvaluator is not connected.")
        evaluation = self.evaluator.evaluate(experience)
        result["evaluation"] = evaluation
        self.evaluation_count += 1
        if self.knowledge_builder is not None:
            candidate = self.knowledge_builder.build(experience=experience, evaluation=evaluation)
            result["knowledge"] = candidate
            if candidate is not None:
                self.knowledge_build_count += 1
                if auto_accept:
                    accepted = self.accept_knowledge(candidate["id"])
                    result["accepted"] = accepted.get("status") == "ACCEPTED"
                    # THE OTHER HALF of the multi-fact storage fix: build()
                    # now returns sibling candidate IDs for every additional
                    # fact the same turn's semantic understanding found
                    # (see KnowledgeBuilder.build()'s docstring on this) --
                    # each one needs its own accept() call too, or a message
                    # with two facts would build both candidates but only
                    # ever commit one of them to durable memory.
                    additional_ids = candidate.get("additional_candidates") or []
                    accepted_additional = 0
                    for extra_id in additional_ids:
                        try:
                            extra_result = self.accept_knowledge(extra_id)
                            if extra_result.get("status") == "ACCEPTED":
                                accepted_additional += 1
                        except Exception:
                            pass
                    if additional_ids:
                        result["additional_accepted"] = accepted_additional
        if self.skill_learner is not None:
            observe = getattr(self.skill_learner, "observe", None)
            if callable(observe):
                proposals = observe(experience)
                self.skill_observation_count += 1
                result["skill_proposals"] = proposals
                self.skill_proposal_count = len(proposals or [])
                if proposals:
                    self._emit("SKILL_PROPOSALS_GENERATED", {"proposals": proposals})
        self.learning_count += 1
        self.last_learning_at = time.time()
        result["success"] = True
        result["duration"] = time.time() - started_at
        result["timestamp"] = self.last_learning_at
        self.last_result = result
        self._emit("LEARNING_COMPLETED", result)
        return result

    def evaluate(self, experience):
        if not self.running:
            raise RuntimeError("LearningCoordinator is stopped.")
        if self.evaluator is None:
            raise RuntimeError("SelfEvaluator is not connected.")
        result = self.evaluator.evaluate(experience)
        self.evaluation_count += 1
        self._emit("LEARNING_EVALUATION_COMPLETED", result)
        return result

    def build_knowledge(self, experience, evaluation=None):
        if self.knowledge_builder is None:
            raise RuntimeError("KnowledgeBuilder is not connected.")
        if evaluation is None:
            evaluation = self.evaluate(experience)
        candidate = self.knowledge_builder.build(experience=experience, evaluation=evaluation)
        if candidate is not None:
            self.knowledge_build_count += 1
            self._emit("LEARNING_KNOWLEDGE_BUILT", candidate)
        return candidate

    def accept_knowledge(self, knowledge_id):
        if self.knowledge_builder is None:
            raise RuntimeError("KnowledgeBuilder is not connected.")
        candidate = self.knowledge_builder.accept(knowledge_id)
        if candidate.get("status") == "ACCEPTED":
            self.knowledge_accept_count += 1
            self._emit("LEARNING_KNOWLEDGE_ACCEPTED", candidate)
        return candidate

    def reject_knowledge(self, knowledge_id, reason=""):
        if self.knowledge_builder is None:
            raise RuntimeError("KnowledgeBuilder is not connected.")
        candidate = self.knowledge_builder.reject(knowledge_id=knowledge_id, reason=reason)
        self.knowledge_reject_count += 1
        self._emit("LEARNING_KNOWLEDGE_REJECTED", candidate)
        return candidate

    def list_skill_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.skill_learner is None:
            return []
        method = getattr(self.skill_learner, "list_proposals", None)
        return method(status=status) if callable(method) else []

    def approve_skill_proposal(self, name: str) -> Dict[str, Any]:
        if self.skill_learner is None:
            raise RuntimeError("SkillLearner is not connected.")
        method = getattr(self.skill_learner, "approve", None)
        if not callable(method):
            raise RuntimeError("SkillLearner does not expose approve().")
        result = method(name)
        self._emit("SKILL_PROPOSAL_APPROVED", result)
        return result

    def reject_skill_proposal(self, name: str, reason: str = "") -> Dict[str, Any]:
        if self.skill_learner is None:
            raise RuntimeError("SkillLearner is not connected.")
        method = getattr(self.skill_learner, "reject", None)
        if not callable(method):
            raise RuntimeError("SkillLearner does not expose reject().")
        result = method(name, reason=reason)
        self._emit("SKILL_PROPOSAL_REJECTED", result)
        return result

    def activate_skill_proposal(self, name: str, handler: Any) -> Dict[str, Any]:
        """Explicitly activate an approved proposal with a supplied callable handler."""
        if self.skill_learner is None:
            raise RuntimeError("SkillLearner is not connected.")
        if self.skill_registry is None:
            raise RuntimeError("SkillRegistry is not connected.")
        proposals = self.list_skill_proposals()
        proposal = next((p for p in proposals if p.get("name") == name), None)
        if proposal is None:
            raise KeyError(f"Unknown skill proposal: {name}")
        if proposal.get("status") != "approved":
            raise PermissionError("Only approved skill proposals may be activated")
        register = getattr(self.skill_registry, "register_approved", None)
        if not callable(register):
            raise RuntimeError("SkillRegistry does not expose register_approved().")
        registration = register(proposal, handler)
        mark_registered = getattr(self.skill_learner, "mark_registered", None)
        if not callable(mark_registered):
            raise RuntimeError("SkillLearner does not expose mark_registered().")
        updated = mark_registered(name)
        self.skill_registration_count += 1
        result = {"proposal": updated, "registration": registration, "status": "registered"}
        self._emit("SKILL_PROPOSAL_ACTIVATED", result)
        return result

    def consolidate(self, limit=50):
        if self.consolidator is None:
            raise RuntimeError("MemoryConsolidator is not connected.")
        result = self.consolidator.consolidate(limit=limit)
        self.consolidation_count += 1
        self._emit("LEARNING_CONSOLIDATION_COMPLETED", result)
        return result

    def learn_and_consolidate(self, experience, auto_accept=False, consolidation_limit=50):
        learning = self.learn(experience=experience, auto_accept=auto_accept)
        consolidation = self.consolidate(limit=consolidation_limit)
        return {"learning": learning, "consolidation": consolidation, "timestamp": time.time()}

    def get_candidate(self, knowledge_id):
        if self.knowledge_builder is None:
            return None
        getter = getattr(self.knowledge_builder, "get", None)
        return getter(knowledge_id) if callable(getter) else None

    def list_candidates(self, status=None, limit=50):
        if self.knowledge_builder is None:
            return []
        method = getattr(self.knowledge_builder, "list_knowledge", None)
        return method(status=status, limit=limit) if callable(method) else []

    def status(self):
        def safe_status(obj, method_name):
            if obj is None:
                return {}
            method = getattr(obj, method_name, None)
            if not callable(method):
                return {}
            try:
                return method()
            except Exception as exc:
                return {"error": str(exc)}
        return {"version": self.VERSION, "running": self.running,
                "learning_count": self.learning_count, "evaluation_count": self.evaluation_count,
                "knowledge_build_count": self.knowledge_build_count,
                "knowledge_accept_count": self.knowledge_accept_count,
                "knowledge_reject_count": self.knowledge_reject_count,
                "consolidation_count": self.consolidation_count,
                "skill_observation_count": self.skill_observation_count,
                "skill_proposal_count": self.skill_proposal_count,
                "skill_registration_count": self.skill_registration_count,
                "last_learning_at": self.last_learning_at,
                "evaluator": safe_status(self.evaluator, "statistics"),
                "knowledge_builder": safe_status(self.knowledge_builder, "statistics"),
                "consolidator": safe_status(self.consolidator, "status"),
                "skill_learner": safe_status(self.skill_learner, "statistics"),
                "skill_registry": safe_status(self.skill_registry, "statistics")}

    def reset_statistics(self):
        self.learning_count = self.evaluation_count = self.knowledge_build_count = 0
        self.knowledge_accept_count = self.knowledge_reject_count = self.consolidation_count = 0
        self.skill_observation_count = self.skill_proposal_count = self.skill_registration_count = 0
        self.last_learning_at = self.last_result = None

    def start(self): self.running = True
    def stop(self): self.running = False

    def _emit(self, event_name, payload=None):
        if self.events is None:
            return
        safe_emit = getattr(self.events, "safe_emit", None)
        if callable(safe_emit):
            safe_emit(event_name, payload, source="learning_coordinator")
