from __future__ import annotations

import os
import threading
from typing import Optional

# Mobile/PRoot safety: keep native numerical libraries from creating a large
# worker pool before ONNX Runtime receives its explicit session options.
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

from .jarvis_core import JarvisCore
from ..identity.jarvis_identity import JarvisIdentity
from .internal_state import InternalState
from .event_bus import EventBus
from .heartbeat import Heartbeat
from .lifecycle import Lifecycle
from core.orchestration.blueprint_brain import BlueprintBrain
from core.orchestration.llm_bridge import HybridLLMBridge
from core.orchestration.cognitive_router import CognitiveRouter
from core.orchestration.perception import PerceptionEngine, NativePerceptionProvider
from ..memory.memory_manager import MemoryManager
from ..memory.memory_consolidator import MemoryConsolidator
from ..learning.experience_engine import ExperienceEngine
from ..learning.self_evaluator import SelfEvaluator
from ..learning.knowledge_builder import KnowledgeBuilder
from ..learning.learning_coordinator import LearningCoordinator
from ..learning.controlled_evolution import ControlledEvolutionEngine
from ..learning.runtime_evolution_adapter import RuntimeEvolutionAdapter
from ..autonomy.curiosity import Curiosity
from ..autonomy.goal_manager import GoalManager
from ..autonomy.planner import Planner
from ..autonomy.scheduler import Scheduler
from ..autonomy.idle_loop import IdleLoop
from ..skills.skill_registry import SkillRegistry
from ..skills.skill_executor import SkillExecutor
from ..skills.skill_learner import SkillLearner
from ..cognition.semantic_understanding import SemanticUnderstanding
from ..runtime.runtime_monitor import RuntimeMonitor
from ..runtime.state_bus import get_state_bus


def create_jarvis(identity=None, personality=None, values=None,
                  heartbeat_interval: float = 5.0,
                  idle_threshold: float = 30.0) -> JarvisCore:
    state = InternalState()
    events = EventBus(internal_state=state)
    heartbeat = Heartbeat(event_bus=events, internal_state=state,
                          interval=heartbeat_interval, idle_threshold=idle_threshold)
    memory = MemoryManager(event_bus=events)
    # UK's #1 recall/learning/memory proposal, persistence half: load
    # back any personal typo corrections learned in a previous session
    # (see core/cognition/translator.py's load_personal_corrections) --
    # without this, everything learned during a session was silently
    # lost on every restart.
    try:
        from ..cognition.translator import load_personal_corrections
        load_personal_corrections(memory)
    except Exception:
        pass
    experience_engine = ExperienceEngine(memory_manager=memory, event_bus=events, internal_state=state)
    evaluator = SelfEvaluator(memory_manager=memory, event_bus=events, internal_state=state)
    knowledge_builder = KnowledgeBuilder(event_bus=events, internal_state=state, memory_manager=memory)
    consolidator = MemoryConsolidator(memory_manager=memory, event_bus=events)
    skill_learner = SkillLearner()
    skill_registry = SkillRegistry()
    learning = LearningCoordinator(
        evaluator=evaluator, knowledge_builder=knowledge_builder, consolidator=consolidator,
        memory_manager=memory, event_bus=events, internal_state=state,
        skill_learner=skill_learner, skill_registry=skill_registry,
    )
    evolution = ControlledEvolutionEngine(event_bus=events, internal_state=state, memory_manager=memory)
    runtime_evolution_adapter = RuntimeEvolutionAdapter(event_bus=events, memory_manager=memory)
    evolution.register_adapter(RuntimeEvolutionAdapter.TARGET, runtime_evolution_adapter)
    goal_manager = GoalManager(store=memory.store)
    curiosity = Curiosity()
    scheduler = Scheduler()
    # Auto-detect by default (fast 1.5s connectivity probe -> Groq only if
    # actually reachable). Forcing "online" unconditionally here was
    # bypassing that probe and going straight to a blind 6-key Groq
    # attempt (~8s timeout each = up to ~48s) even with no network at
    # all -- that is the actual cause of "hangs the moment I say hi" on
    # a flaky/offline Termux connection. Only force a mode when the user
    # explicitly asks for one via JARVIS_LLM_MODE.
    llm_mode = os.getenv("JARVIS_LLM_MODE") or None
    llm_bridge = HybridLLMBridge(force_mode=llm_mode)
    planner = Planner(llm_bridge=llm_bridge)
    skill_executor = SkillExecutor(skill_registry)
    cognitive_router = CognitiveRouter()
    perception = PerceptionEngine(state=state, providers=[NativePerceptionProvider()])
    semantic_understanding = SemanticUnderstanding(semantic_memory=memory.semantic)

    brain = BlueprintBrain(
        memory_manager=memory,
        experience_engine=experience_engine,
        learning_coordinator=learning,
        self_evaluator=evaluator,
        knowledge_builder=knowledge_builder,
        memory_consolidator=consolidator,
        evolution_engine=evolution,
        planner=planner,
        goal_manager=goal_manager,
        event_bus=events,
        internal_state=state,
        cognitive_router=cognitive_router,
        perception_engine=perception,
        skill_registry=skill_registry,
        skill_executor=skill_executor,
        llm_bridge=llm_bridge,
        semantic_understanding=semantic_understanding,
    )

    idle_loop = IdleLoop(
        goal_manager=goal_manager, curiosity=curiosity, planner=planner, scheduler=scheduler,
        state=state, event_bus=events, store=memory.store, executor=brain.execute_autonomous_step,
        pattern_detector=getattr(brain, "fallback_pattern_detector", None),
        category_learner=getattr(brain, "category_word_learner", None),
        semantic_memory=memory.semantic,
        standing_instructions=getattr(brain, "standing_instructions", None),
    )
    runtime_monitor = RuntimeMonitor()
    idle_lock = threading.Lock()
    last_idle_run = [0.0]
    idle_cooldown = max(30.0, float(os.getenv("JARVIS_IDLE_COOLDOWN", "30")))
    # Snapshot writes do real disk I/O (JSON serialize + write + rename).
    # Doing that on *every* heartbeat tick (every 2s, forever, even while
    # actively chatting) is continuous background disk activity that adds
    # up on Termux/Android storage. Throttle it independently of the idle
    # cooldown above -- this one should stay live during active use too,
    # just not every single tick.
    monitor_cooldown = max(10.0, float(os.getenv("JARVIS_MONITOR_COOLDOWN", "15")))
    last_monitor_run = [0.0]

    def _on_heartbeat(event) -> None:
        payload = getattr(event, "payload", {}) or {}
        now = __import__("time").time()
        if now - last_monitor_run[0] >= monitor_cooldown:
            last_monitor_run[0] = now
            runtime_monitor.write_snapshot(jarvis=None, organs={
                "heartbeat": heartbeat,
                "llm_bridge": llm_bridge,
                "memory": memory,
                "learning": learning,
                "evaluator": evaluator,
                "knowledge_builder": knowledge_builder,
                "evolution": evolution,
                "idle_loop": idle_loop,
                "state": state,
                # UK explicitly asked to be able to SEE this happen
                # (monitor.py showed no idle-consolidation activity at
                # all before) -- exposed the same way every other organ
                # already is, via RuntimeMonitor._stats()'s generic
                # `.statistics()` lookup (aliased to .status() on
                # MemoryConsolidator).
                "consolidator": consolidator,
            })
        if payload.get("idle"):
            with idle_lock:
                if now - last_idle_run[0] >= idle_cooldown:
                    last_idle_run[0] = now
                    idle_loop.step()
                    # Background knowledge maintenance: before this, both
                    # LearningCoordinator.consolidate() and
                    # KnowledgeBuilder.accept_reliable() were fully
                    # implemented but never actually called by anything
                    # at runtime -- the organism would idle-cycle on
                    # goals/curiosity forever while accepted-but-pending
                    # knowledge candidates and consolidatable episodic
                    # memory just sat there unprocessed. Piggyback on the
                    # same idle tick (and its cooldown) used above so
                    # this runs "whenever JARVIS isn't busy talking to
                    # someone", each step independently guarded so one
                    # failing never blocks the other or the idle loop.
                    try:
                        learning.consolidate(limit=25)
                    except Exception as exc:
                        events.safe_emit(
                            "IDLE_CONSOLIDATION_FAILED", {"error": str(exc)}, source="bootstrap"
                        ) if hasattr(events, "safe_emit") else None
                    try:
                        knowledge_builder.accept_reliable(minimum_confidence=0.75, limit=25)
                    except Exception as exc:
                        events.safe_emit(
                            "IDLE_KNOWLEDGE_ACCEPT_FAILED", {"error": str(exc)}, source="bootstrap"
                        ) if hasattr(events, "safe_emit") else None
                    try:
                        # 2026-09-11 roadmap Phase 5 (previously dead
                        # code): SemanticEvolutionCycle/SemanticKnowledge
                        # Promotion were fully written but NEVER imported
                        # anywhere -- every LLM-fallback semantic
                        # interpretation sat in learning_boundary.py's
                        # in-memory candidates dict forever, never
                        # promoted into LearnedSemanticRegistry, so
                        # JARVIS kept re-asking the LLM for input
                        # patterns it had already successfully
                        # interpreted before. semantic_evolution_cycle
                        # is constructed lazily here (not at bootstrap
                        # top) so it always sees the SAME
                        # learning_boundary instance Brain actually
                        # wired up in _configure_semantic_fallback().
                        boundary = getattr(semantic_understanding, "learning_boundary", None)
                        if boundary is not None:
                            from core.cognition.semantic_understanding.evolution_cycle import SemanticEvolutionCycle
                            evolution_cycle = SemanticEvolutionCycle(boundary=boundary, learning_coordinator=learning)
                            promo_result = evolution_cycle.promote_ready_candidates(min_confidence=0.75, limit=10)
                            if promo_result.get("promoted"):
                                events.safe_emit(
                                    "IDLE_SEMANTIC_CANDIDATES_PROMOTED", promo_result, source="bootstrap"
                                ) if hasattr(events, "safe_emit") else None
                    except Exception as exc:
                        events.safe_emit(
                            "IDLE_SEMANTIC_PROMOTION_FAILED", {"error": str(exc)}, source="bootstrap"
                        ) if hasattr(events, "safe_emit") else None
                    try:
                        # SELF-AUTHORED EXTRACTION PATTERNS (2026-09-12,
                        # UK's explicit "regex = hardcoding" objection):
                        # cluster boundary.candidates (real inputs where
                        # native symbolic parsing failed and the LLM had
                        # to step in -- see learning_boundary.py) by a
                        # cheap shared-shape heuristic (same first two
                        # words), and if 2+ genuinely similar failures
                        # exist, ask JARVIS's own pattern_synthesizer to
                        # propose+sandbox-test a new native pattern for
                        # that shape. Nothing here ever applies a
                        # pattern live -- see Brain.confirm_pattern();
                        # this only ever WRITES A PENDING PROPOSAL, same
                        # as self-authored behavioral rules.
                        boundary = getattr(semantic_understanding, "learning_boundary", None)
                        synthesizer = getattr(brain, "pattern_synthesizer", None)
                        if boundary is not None and synthesizer is not None:
                            from collections import defaultdict
                            clusters = defaultdict(list)
                            for candidate in boundary.candidates.values():
                                text = getattr(candidate, "input_text", "") or ""
                                words = text.strip().lower().split()
                                if len(words) >= 2:
                                    clusters[" ".join(words[:2])].append(text)
                            for shape, examples in clusters.items():
                                if len(examples) >= 2:
                                    proposal = synthesizer.propose_from_candidates(
                                        similar_examples=examples[:5],
                                        gap_description=f"native extraction repeatedly failed on inputs shaped like '{shape}...'",
                                    )
                                    if proposal:
                                        events.safe_emit(
                                            "IDLE_PATTERN_PROPOSED", proposal, source="bootstrap"
                                        ) if hasattr(events, "safe_emit") else None
                                    break  # one proposal per idle cycle -- stay cheap, stay reviewable at UK's pace
                    except Exception as exc:
                        events.safe_emit(
                            "IDLE_PATTERN_SYNTHESIS_FAILED", {"error": str(exc)}, source="bootstrap"
                        ) if hasattr(events, "safe_emit") else None
                    try:
                        # UK's #5 recall/learning/memory proposal: mine
                        # the persistent trace log for repeated, safe,
                        # always-consistent small talk and promote it
                        # into a zero-LLM-call native template.
                        brain.native_response_learner.run_idle_cycle()
                    except Exception as exc:
                        events.safe_emit(
                            "IDLE_NATIVE_RESPONSE_LEARNING_FAILED", {"error": str(exc)}, source="bootstrap"
                        ) if hasattr(events, "safe_emit") else None
                    try:
                        # UK's #3 recall/learning/memory proposal
                        # (spaced-repetition-inspired decay): personal
                        # facts nobody has recalled/reinforced in 14+
                        # days quietly weaken, mirroring the forgetting
                        # curve, instead of every fact sitting at equal
                        # permanent weight forever.
                        decayed_ids = memory.semantic.decay_unused(days_threshold=14.0, confidence_delta=0.02)
                        events.safe_emit(
                            "MEMORY_DECAY_COMPLETED",
                            {"decayed_count": len(decayed_ids), "timestamp": __import__("time").time()},
                            source="bootstrap",
                        ) if hasattr(events, "safe_emit") else None
                    except Exception as exc:
                        events.safe_emit(
                            "IDLE_MEMORY_DECAY_FAILED", {"error": str(exc)}, source="bootstrap"
                        ) if hasattr(events, "safe_emit") else None

    events.subscribe("HEARTBEAT", _on_heartbeat)

    organs = {
        "memory": memory, "experience": experience_engine, "evaluator": evaluator,
        "knowledge_builder": knowledge_builder, "consolidator": consolidator,
        "learning": learning, "evolution": evolution, "curiosity": curiosity,
        "goal_manager": goal_manager, "planner": planner, "scheduler": scheduler,
        "idle_loop": idle_loop, "skill_registry": skill_registry,
        "skill_executor": skill_executor, "skill_learner": skill_learner,
        "perception": perception, "cognitive_router": cognitive_router,
        "brain": brain, "llm_bridge": llm_bridge,
        "semantic_understanding": semantic_understanding,
        "runtime_evolution_adapter": runtime_evolution_adapter,
        "runtime_monitor": runtime_monitor,
    }
    jarvis = JarvisCore(identity=identity, personality=personality, values=values,
                        state=state, event_bus=events, heartbeat=heartbeat, organs=organs)
    jarvis.idle_loop = idle_loop
    # So the self-awareness fast path (brain-scoped, not organism-scoped)
    # can answer "good morning, what did you do overnight" directly from
    # idle_loop's real accumulated log, without needing a wider,
    # riskier wiring change to pass the whole organism through.
    brain.idle_loop = idle_loop
    runtime_monitor.bind_jarvis(jarvis)

    # Structured identity (INVARIANTS / CURRENT SELF / HISTORY) -- see
    # core/identity/jarvis_identity.py. Constructed here rather than
    # earlier because it needs live references to brain/memory/goal_manager
    # to answer "what can you actually do right now" truthfully instead
    # of from a static, possibly-stale profile.
    jarvis_identity = JarvisIdentity(brain=brain, memory=memory, goal_manager=goal_manager)
    brain.identity_system = jarvis_identity
    jarvis.identity_system = jarvis_identity
    # So idle_loop's periodic review cycle can checkpoint runtime (see
    # JarvisIdentity.checkpoint_runtime()) -- attached after
    # construction since JarvisIdentity is built after IdleLoop in this
    # bootstrap order.
    idle_loop.identity = jarvis_identity

    # Cross-process IPC state bus: derives the live PERCEIVING/INDEXING/
    # EXECUTING/IDLE pipeline stage from events Brain already emits, and
    # polls coarse organ/heartbeat/learning-queue health in the
    # background so `python3 monitor.py` (run in a second Termux/tmux/
    # SSH session) can render it -- with no GUI-terminal auto-spawn and
    # no extra pip dependency, unlike the previous monitor attempts.
    get_state_bus().attach(jarvis=jarvis, brain=brain, event_bus=events)

    return jarvis


def start_jarvis(identity=None, personality=None, values=None,
                 heartbeat_interval: float = 5.0,
                 idle_threshold: float = 30.0) -> JarvisCore:
    jarvis = create_jarvis(identity=identity, personality=personality, values=values,
                           heartbeat_interval=heartbeat_interval, idle_threshold=idle_threshold)
    lifecycle = Lifecycle(jarvis, internal_state=jarvis.state,
                          event_bus=jarvis.event_bus, heartbeat=jarvis.heartbeat)
    jarvis.lifecycle = lifecycle
    lifecycle.start()
    jarvis.start()
    return jarvis


def stop_jarvis(jarvis: Optional[JarvisCore]) -> None:
    if jarvis is None:
        return
    try:
        get_state_bus().stop()
    except Exception:
        pass
    try:
        lifecycle = getattr(jarvis, "lifecycle", None)
        if lifecycle is None:
            lifecycle = Lifecycle(jarvis, internal_state=jarvis.state,
                                  event_bus=jarvis.event_bus, heartbeat=jarvis.heartbeat)
        lifecycle.stop()
    except Exception:
        try:
            if hasattr(jarvis, "heartbeat") and jarvis.heartbeat is not None:
                jarvis.heartbeat.stop()
        except Exception:
            pass
        try:
            if hasattr(jarvis, "stop"):
                jarvis.stop()
        except Exception:
            pass
    # Was never called anywhere: without this, a session ending via
    # Ctrl+C never got a final WAL checkpoint at all, and the per-call
    # connection leak in semantic_memory.py (now fixed) meant open
    # connections just accumulated for the process's whole life. This is
    # the actual mechanism behind the database ballooning to hundreds of
    # MB while holding almost no real data -- run this last, after every
    # other organ has stopped, so nothing tries to write after close().
    try:
        memory = jarvis.get_organ("memory") if hasattr(jarvis, "get_organ") else None
        if memory is not None and hasattr(memory, "close"):
            memory.close()
    except Exception:
        pass
