from __future__ import annotations

from typing import Any, Dict


class SkillRegistry:
    """Single source of truth for executable native and approved learned skills."""

    def __init__(self):
        self.skills: Dict[str, Any] = {}
        self.metadata: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, handler: Any) -> None:
        """Register a native capability directly."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Skill name must be a non-empty string")
        if not callable(handler):
            raise TypeError("Skill handler must be callable")
        self.skills[name] = handler
        self.metadata[name] = {"source": "native", "status": "registered"}

    def register_approved(self, proposal: Dict[str, Any], handler: Any) -> Dict[str, Any]:
        """Register an executable handler only after explicit proposal approval."""
        if not isinstance(proposal, dict):
            raise TypeError("proposal must be a dictionary")
        if proposal.get("status") != "approved":
            raise PermissionError("Only approved skill proposals may be registered")
        if not callable(handler):
            raise TypeError("Approved skill handler must be callable")

        name = proposal.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Approved proposal must contain a non-empty name")
        if name in self.skills:
            raise KeyError(f"Skill already registered: {name}")

        self.skills[name] = handler
        self.metadata[name] = {
            "source": "learned",
            "status": "registered",
            "proposal_name": name,
            "registered_at": __import__("time").time(),
        }
        return {"name": name, **self.metadata[name]}

    def get(self, name: str):
        return self.skills.get(name)

    def is_registered(self, name: str) -> bool:
        return name in self.skills
