from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class SkillLearner:
    """Turns repeated verified experiences into governed skill proposals."""

    VERSION = "0.3.0"

    def __init__(self, min_repetitions: int = 3, min_success_rate: float = 0.8):
        if min_repetitions < 1:
            raise ValueError("min_repetitions must be >= 1")
        if not 0.0 <= min_success_rate <= 1.0:
            raise ValueError("min_success_rate must be between 0 and 1")
        self.min_repetitions = min_repetitions
        self.min_success_rate = min_success_rate
        self._experiences: List[Dict[str, Any]] = []
        self._proposals: Dict[str, Dict[str, Any]] = {}

    def observe(self, experience: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(experience, dict):
            raise TypeError("experience must be a dictionary")
        normalized = self._normalize_experience(experience)
        if normalized is None or not normalized["success"]:
            return []
        self._experiences.append(normalized)
        return self.propose(self._experiences)

    def propose(self, experiences: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        source = self._experiences if experiences is None else experiences
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for raw in source:
            normalized = self._normalize_experience(raw)
            if normalized is None:
                continue
            grouped.setdefault(normalized["action"], []).append(normalized)

        proposals: List[Dict[str, Any]] = []
        for action, group in grouped.items():
            total = len(group)
            successes = sum(1 for item in group if item["success"])
            if total < self.min_repetitions or successes / total < self.min_success_rate:
                continue
            name = self._skill_name(action)
            existing = self._proposals.get(name)
            status = existing.get("status", "proposed") if existing else "proposed"
            # Registered proposals remain registered; repeated observation must
            # never silently reopen or replace an already approved capability.
            proposal = {
                "name": name,
                "based_on_action": action,
                "repetitions": total,
                "success_rate": round(successes / total, 2),
                "example_detail": group[-1].get("detail", ""),
                "goal": group[-1].get("goal", ""),
                "proposed_at": existing.get("proposed_at", time.time()) if existing else time.time(),
                "status": status,
            }
            for key in ("approved_at", "registered_at", "rejection_reason", "rejected_at"):
                if existing and key in existing:
                    proposal[key] = existing[key]
            self._proposals[name] = proposal
            proposals.append(dict(proposal))
        return proposals

    def list_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        values = list(self._proposals.values())
        if status is not None:
            values = [p for p in values if p.get("status") == status]
        return [dict(p) for p in values]

    def approve(self, name: str) -> Dict[str, Any]:
        proposal = self._proposals.get(name)
        if proposal is None:
            raise KeyError(f"Unknown skill proposal: {name}")
        if proposal.get("status") != "proposed":
            raise ValueError(f"Skill proposal is not awaiting approval: {name}")
        proposal["status"] = "approved"
        proposal["approved_at"] = time.time()
        return dict(proposal)

    def reject(self, name: str, reason: str = "") -> Dict[str, Any]:
        proposal = self._proposals.get(name)
        if proposal is None:
            raise KeyError(f"Unknown skill proposal: {name}")
        if proposal.get("status") == "registered":
            raise ValueError(f"Registered skill proposal cannot be rejected: {name}")
        proposal["status"] = "rejected"
        proposal["rejection_reason"] = reason
        proposal["rejected_at"] = time.time()
        return dict(proposal)

    def mark_registered(self, name: str) -> Dict[str, Any]:
        proposal = self._proposals.get(name)
        if proposal is None:
            raise KeyError(f"Unknown skill proposal: {name}")
        if proposal.get("status") != "approved":
            raise PermissionError("Only approved proposals may become registered")
        proposal["status"] = "registered"
        proposal["registered_at"] = time.time()
        return dict(proposal)

    @classmethod
    def _normalize_experience(cls, experience: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        action = experience.get("action")
        outcome = experience.get("outcome") or {}
        context = experience.get("context") or {}
        if isinstance(action, dict):
            action_name = action.get("skill") or action.get("name") or action.get("action")
            if not action_name or "jarvis_response" in action:
                return None
            detail = action.get("detail", "")
        else:
            action_name = action
            detail = experience.get("detail", "")
        if not isinstance(action_name, str) or not action_name.strip():
            return None
        explicit_success = outcome.get("success") if isinstance(outcome, dict) else None
        if explicit_success is None and "success" in experience:
            explicit_success = experience.get("success")
        if explicit_success is None:
            status = str(experience.get("status", outcome.get("status", "") if isinstance(outcome, dict) else "")).lower()
            success = status in {"success", "completed", "done"}
        else:
            success = bool(explicit_success)
        if not detail and isinstance(outcome, dict):
            detail = outcome.get("detail", "")
        goal = context.get("goal", "") if isinstance(context, dict) else ""
        return {"action": action_name.strip(), "detail": str(detail or ""), "goal": str(goal or ""), "success": success}

    @staticmethod
    def _skill_name(action: str) -> str:
        return "skill_" + "".join(c if c.isalnum() else "_" for c in action.lower()).strip("_")

    def statistics(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "observed_experiences": len(self._experiences),
            "proposal_count": len(self._proposals),
            "proposed": len(self.list_proposals("proposed")),
            "approved": len(self.list_proposals("approved")),
            "registered": len(self.list_proposals("registered")),
            "rejected": len(self.list_proposals("rejected")),
            "min_repetitions": self.min_repetitions,
            "min_success_rate": self.min_success_rate,
        }
