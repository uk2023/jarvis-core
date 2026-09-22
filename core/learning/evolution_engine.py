from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional


class EvolutionEngine:
    """
    Controlled self-improvement organ of JARVIS.

    Flow:

        SelfEvaluator
              ↓
        EvolutionEngine
              ↓
        Improvement Proposal
              ↓
        Validation
              ↓
        Approval
              ↓
        Application (later)

    IMPORTANT:
        This engine never directly modifies source code.
        Evolution must remain observable, reversible and controlled.
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        event_bus=None,
        internal_state=None,
        memory_manager=None,
    ):
        self.events = event_bus
        self.state = internal_state
        self.memory = memory_manager

        self.proposals: Dict[
            str,
            Dict[str, Any]
        ] = {}

        self.approved_count = 0
        self.rejected_count = 0
        self.applied_count = 0

        self.last_proposal: Optional[
            Dict[str, Any]
        ] = None

        self.last_evolution_at: Optional[
            float
        ] = None

    # =============================================================
    # CREATE PROPOSAL
    # =============================================================

    def propose(
        self,
        evaluation: Dict[str, Any],
        target: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a controlled improvement proposal.

        Example target:

            "response_routing"
            "memory_retrieval"
            "task_planning"
            "confidence_calibration"
        """

        if not target:
            raise ValueError(
                "Evolution target cannot be empty."
            )

        proposal_id = str(
            uuid.uuid4()
        )

        score = self._get_score(
            evaluation
        )

        errors = list(
            evaluation.get(
                "errors",
                [],
            )
        )

        strengths = list(
            evaluation.get(
                "strengths",
                [],
            )
        )

        proposal = {
            "id": proposal_id,

            "version": self.VERSION,

            "target": target,

            "reason": (
                reason
                or self._generate_reason(
                    errors
                )
            ),

            "trigger": {
                "evaluation_score": score,
                "errors": errors,
                "strengths": strengths,
            },

            "status": "PROPOSED",

            "created_at": time.time(),

            "validated_at": None,

            "approved_at": None,

            "applied_at": None,

            "change": {
                "type": "BEHAVIORAL_IMPROVEMENT",
                "description": (
                    "Improve target behaviour "
                    "based on evaluation feedback."
                ),
            },
        }

        self.proposals[
            proposal_id
        ] = proposal

        self.last_proposal = proposal

        self._emit(
            "EVOLUTION_PROPOSED",
            proposal,
        )

        return proposal

    # =============================================================
    # VALIDATE
    # =============================================================

    def validate(
        self,
        proposal_id: str,
    ) -> Dict[str, Any]:
        """
        Validate an improvement proposal.

        Validation currently checks structural safety.
        """

        proposal = self._get_proposal(
            proposal_id
        )

        if proposal["status"] != "PROPOSED":

            return proposal

        errors = []

        if not proposal.get(
            "target"
        ):
            errors.append(
                "MISSING_TARGET"
            )

        if not proposal.get(
            "change"
        ):
            errors.append(
                "MISSING_CHANGE"
            )

        if errors:

            proposal["status"] = (
                "INVALID"
            )

            proposal["validation_errors"] = (
                errors
            )

        else:

            proposal["status"] = (
                "VALIDATED"
            )

            proposal["validated_at"] = (
                time.time()
            )

        self._emit(
            "EVOLUTION_VALIDATED",
            {
                "proposal_id": proposal_id,
                "status": proposal["status"],
                "errors": errors,
            },
        )

        return proposal

    # =============================================================
    # APPROVE
    # =============================================================

    def approve(
        self,
        proposal_id: str,
    ) -> Dict[str, Any]:
        """
        Approve a validated proposal.

        Approval does not apply the change.
        """

        proposal = self._get_proposal(
            proposal_id
        )

        if proposal["status"] != "VALIDATED":

            raise RuntimeError(
                "Only VALIDATED proposals can be approved."
            )

        proposal["status"] = "APPROVED"

        proposal["approved_at"] = (
            time.time()
        )

        self.approved_count += 1

        self._emit(
            "EVOLUTION_APPROVED",
            proposal,
        )

        return proposal

    # =============================================================
    # REJECT
    # =============================================================

    def reject(
        self,
        proposal_id: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Reject a proposal.
        """

        proposal = self._get_proposal(
            proposal_id
        )

        proposal["status"] = "REJECTED"

        proposal["rejection_reason"] = (
            reason
        )

        self.rejected_count += 1

        self._emit(
            "EVOLUTION_REJECTED",
            {
                "proposal_id": proposal_id,
                "reason": reason,
            },
        )

        return proposal

    # =============================================================
    # APPLY
    # =============================================================

    def apply(
        self,
        proposal_id: str,
    ) -> Dict[str, Any]:
        """
        Apply an approved evolution.

        Current version records the application only.

        Actual behavioral adapters will be connected later.
        """

        proposal = self._get_proposal(
            proposal_id
        )

        if proposal["status"] != "APPROVED":

            raise RuntimeError(
                "Only APPROVED proposals can be applied."
            )

        proposal["status"] = "APPLIED"

        proposal["applied_at"] = (
            time.time()
        )

        self.applied_count += 1

        self.last_evolution_at = (
            time.time()
        )

        self._emit(
            "EVOLUTION_APPLIED",
            proposal,
        )

        return proposal

    # =============================================================
    # PROPOSAL LOOKUP
    # =============================================================

    def get_proposal(
        self,
        proposal_id: str,
    ) -> Optional[Dict[str, Any]]:

        return self.proposals.get(
            proposal_id
        )

    def _get_proposal(
        self,
        proposal_id: str,
    ) -> Dict[str, Any]:

        proposal = self.get_proposal(
            proposal_id
        )

        if proposal is None:

            raise KeyError(
                f"Unknown evolution proposal: "
                f"{proposal_id}"
            )

        return proposal

    # =============================================================
    # LIST PROPOSALS
    # =============================================================

    def list_proposals(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:

        proposals = list(
            self.proposals.values()
        )

        if status:

            status = status.upper()

            proposals = [
                proposal
                for proposal in proposals
                if proposal["status"] == status
            ]

        proposals.sort(
            key=lambda item: item.get(
                "created_at",
                0,
            ),
            reverse=True,
        )

        return proposals[:limit]

    # =============================================================
    # SCORE
    # =============================================================

    @staticmethod
    def _get_score(
        evaluation: Dict[str, Any],
    ) -> float:

        try:

            return max(
                0.0,
                min(
                    1.0,
                    float(
                        evaluation.get(
                            "score",
                            0.0,
                        )
                    ),
                ),
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0.0

    # =============================================================
    # REASON
    # =============================================================

    @staticmethod
    def _generate_reason(
        errors: List[Any],
    ) -> str:

        if errors:

            return (
                "Improvement proposed because "
                f"evaluation detected: {errors}"
            )

        return (
            "Improvement proposed from "
            "self-evaluation feedback."
        )

    # =============================================================
    # STATISTICS
    # =============================================================

    def statistics(self) -> Dict[str, Any]:

        return {
            "version": self.VERSION,

            "proposals": len(
                self.proposals
            ),

            "approved": (
                self.approved_count
            ),

            "rejected": (
                self.rejected_count
            ),

            "applied": (
                self.applied_count
            ),

            "last_evolution_at": (
                self.last_evolution_at
            ),
        }

    # =============================================================
    # SNAPSHOT
    # =============================================================

    def snapshot(self) -> Dict[str, Any]:

        return {
            "version": self.VERSION,

            "proposals": list(
                self.proposals.values()
            ),

            "statistics": self.statistics(),
        }

    # =============================================================
    # RESTORE
    # =============================================================

    def restore(
        self,
        snapshot: Dict[str, Any],
    ) -> None:

        if not isinstance(
            snapshot,
            dict,
        ):
            return

        proposals = snapshot.get(
            "proposals",
            [],
        )

        if not isinstance(
            proposals,
            list,
        ):
            return

        self.proposals.clear()

        for proposal in proposals:

            if not isinstance(
                proposal,
                dict,
            ):
                continue

            proposal_id = proposal.get(
                "id"
            )

            if proposal_id:

                self.proposals[
                    proposal_id
                ] = proposal

    # =============================================================
    # EVENT BUS
    # =============================================================

    def _emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:

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
                source="evolution_engine",
            )