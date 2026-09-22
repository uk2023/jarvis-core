from __future__ import annotations

from typing import Any, Dict

# Human-readable role text per organ name, as attached in
# core/organism/bootstrap.py. Used by cli.py's render_organ_matrix()
# and by backend/routes_frontend_v6.py's /api/organism/state so both
# surfaces describe the same organism the same way instead of the web
# UI making up its own generic labels.
ORGAN_ROLES: Dict[str, str] = {
    "brain": "Central Context Orchestrator & Cognitive Pipeline",
    "memory": "Vector Index (FAISS) + Semantic Knowledge Graph (NetworkX)",
    "experience_engine": "Episodic Frame Ingestion & Trajectory Structuring",
    "self_evaluator": "Output Verification & Multi-metric Confidence Scoring",
    "knowledge_builder": "Semantic Fact Extraction & Memory Candidate Ranking",
    "memory_consolidator": "Subconscious Episode Compression Engine",
    "learning_coordinator": "Inter-Organ Message Router & Memory Pipeline Controller",
    "evolution": "Self-Improvement & Code Base Runtime Patching",
    "llm": "Local LLM Neural Bridge (Qwen 2.5 LlamaCpp Interface)",
    "goal_manager": "Persisted Goal Tracking (pending/active/completed)",
    "curiosity": "Idle-time Candidate Generator (uncertainty/stalled goals)",
    "scheduler": "In-process Priority Queue for Background Tasks",
    "planner": "Goal -> Step Decomposition (rule-based + LLM-assisted)",
    "idle_loop": "Heartbeat-driven Autonomy Cycle (curiosity->plan->log)",
    "skill_registry": "Registry of Executable Learned/Native Skills",
    "skill_executor": "Sandboxed Skill Invocation",
    "skill_learner": "Repeated-Success -> Skill Proposal Generator",
}


def describe_organ(jarvis: Any, name: str, info: Dict[str, Any]) -> str:
    """
    Role text plus, for a couple of organs, a live one-line metric
    pulled straight from the organ itself (not a static label) so the
    diagnostics actually change as the organism runs.
    """
    if name == "goal_manager" and hasattr(jarvis, "get_organ"):
        gm = jarvis.get_organ("goal_manager")
        if gm is not None and hasattr(gm, "snapshot"):
            try:
                snap = gm.snapshot()
                return (
                    f"{ORGAN_ROLES[name]} | total={snap.get('total', 0)} "
                    f"pending={snap.get('pending', 0)} completed={snap.get('completed', 0)}"
                )
            except Exception:
                pass

    if name == "scheduler" and hasattr(jarvis, "get_organ"):
        sc = jarvis.get_organ("scheduler")
        if sc is not None and hasattr(sc, "snapshot"):
            try:
                snap = sc.snapshot()
                return f"{ORGAN_ROLES[name]} | pending_tasks={snap.get('pending', 0)}"
            except Exception:
                pass

    return ORGAN_ROLES.get(name, "Auxiliary Operational Organ")
