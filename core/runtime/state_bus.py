from __future__ import annotations

"""JARVIS IPC State Bus.

A single, zero-dependency, file-based channel that lets a *second*
process (monitor.py, running in another Termux/tmux/SSH session)
observe what the running JARVIS organism is doing right now, without
sharing any Python objects and without requiring any GUI terminal
auto-spawn (the previous approach in cli_runtime_monitor.py hard-
crashed cli.py on Termux because no gnome-terminal/xterm/konsole is
ever available there).

Everything here is stdlib-only (json/os/threading/time/collections).

What it publishes, matching the required monitor surface:

    * stage            - current lifecycle stage of the SYNCHRONOUS
                          turn pipeline: IDLE, PERCEIVING, INDEXING,
                          EXECUTING. ("LEARNING" is tracked separately
                          below because it runs on its own async
                          worker thread and legitimately overlaps with
                          the next turn's IDLE/PERCEIVING.)
    * fallback_active  - True while the most recent structured
                          extraction had to fall through to the
                          Stage-3 deterministic safe default.
    * pipeline_trace    - ring buffer of the last N stage transitions.
    * extractions       - ring buffer of the last N extraction-cascade
                          results (schema, stage used, ok/fail).
    * learning          - background learning queue status (alive,
                          pending, processed, failed, dropped) plus a
                          live "active" flag while a job is running.
    * logs              - ring buffer of the last N internal log
                          events (see core.runtime.log), so warnings/
                          errors that used to be bare print() calls
                          are still visible -- just not in the main
                          chat console.
    * organs / heartbeat / llm_ready - coarse organism health, same
                          shape the old OrganismCLIMonitor exposed.

Writes are atomic (tmpfile + os.replace) and throttled for the
high-frequency organ/heartbeat refresh, but immediate for stage
transitions and extraction/log events since those are comparatively
rare and high-value.
"""

import json
import os
import tempfile
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

STAGES = ("IDLE", "PERCEIVING", "INDEXING", "EXECUTING")

_DEFAULT_PATH_CANDIDATES = []
_env_path = os.environ.get("JARVIS_STATE_IPC")
if _env_path:
    _DEFAULT_PATH_CANDIDATES.append(_env_path)
_DEFAULT_PATH_CANDIDATES.append(os.path.join(tempfile.gettempdir(), "jarvis_state.ipc"))
# Fallback used only if the temp dir turns out not to be writable
# (rare, but some locked-down Android/Termux setups restrict /tmp).
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_PATH_CANDIDATES.append(os.path.join(_BASE_DIR, "runtime", "jarvis_state.ipc"))


def _resolve_path() -> str:
    for candidate in _DEFAULT_PATH_CANDIDATES:
        directory = os.path.dirname(candidate) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            probe = candidate + f".probe{os.getpid()}"
            with open(probe, "w") as handle:
                handle.write("")
            os.unlink(probe)
            return candidate
        except OSError:
            continue
    # Last resort: cwd. write_snapshot()/publish() below still guard
    # every disk operation, so even this failing never raises upward.
    return os.path.join(os.getcwd(), "jarvis_state.ipc")


class StateBus:
    """Process-local writer/aggregator for the on-disk state file."""

    VERSION = 1

    def __init__(self, path: Optional[str] = None, trace_len: int = 40, extraction_len: int = 20, log_len: int = 40):
        self.path = path or _resolve_path()
        self._lock = threading.RLock()
        self._stage = "IDLE"
        self._stage_detail: Dict[str, Any] = {}
        self._stage_since = time.time()
        self._fallback_active = False
        self._pipeline_trace: deque = deque(maxlen=trace_len)
        self._extractions: deque = deque(maxlen=extraction_len)
        self._logs: deque = deque(maxlen=log_len)
        self._learning: Dict[str, Any] = {"active": False, "alive": False, "pending": 0, "processed": 0, "failed": 0, "dropped": 0}
        self._organs: Dict[str, Any] = {}
        self._heartbeat: Dict[str, Any] = {"running": False, "beats": 0, "idle": True}
        # Visibility into what the idle loop (core/autonomy/idle_loop.py)
        # actually does during idle time -- previously the ONLY idle
        # signal anywhere was heartbeat's plain True/False "idle" flag.
        # The idle loop itself was genuinely wired (curiosity ->
        # goals -> planner -> executor) and DID publish
        # IDLE_CYCLE_COMPLETE/IDLE_CYCLE_NOOP events on the event bus
        # the whole time, but nothing ever stored or displayed them --
        # they were received by attach()'s wildcard subscriber below
        # and silently dropped since no case handled that event name.
        self._idle_activity: deque = deque(maxlen=20)
        self._idle_last: Dict[str, Any] = {}
        # Cognitive self-awareness data (blueprint sections 43/48) --
        # previously computed extensively (DependencyMetrics,
        # ControlledEvolutionEngine proposals, post-response reasoning
        # traces, self-authored rules) but NEVER flowed into the state
        # bus at all, so monitor.py had no way to show any of it no
        # matter how the display code improved -- the data simply
        # never arrived here. Fixed at the source: the poll loop below
        # now pulls all of this every cycle.
        self._dependency_metrics: Dict[str, Any] = {}
        self._contradiction_rate: Optional[float] = None
        self._evolution_summary: Dict[str, Any] = {}
        self._latest_reasoning: Dict[str, Any] = {}
        # Most recent turn's LLM tool-call trace (see
        # core/orchestration/tool_registry.py) -- which tools the
        # model proposed and what the gate/execution returned, so
        # monitor.py can show autonomous tool use isn't a black box.
        self._latest_tool_calls: List[Dict[str, Any]] = []
        # Self-authored rules JARVIS has proposed (see Brain's
        # adopt_as_learning path) but UK hasn't reviewed yet via
        # /pending_rules|/confirm_rule|/reject_rule. Previously the
        # reasoning CYCLE that produces these was visible live here
        # (latest_reasoning below) but the RESULTING pending-approval
        # queue was only ever visible by running a CLI command -- so
        # monitor.py could show "JARVIS concluded X is worth adopting"
        # without ever showing whether X was still awaiting a decision.
        self._pending_self_rules: List[Dict[str, Any]] = []
        # Active daily standing instructions (see core/autonomy/
        # standing_instructions.py) -- so monitor.py can show "next
        # fire time" live, the same way it already shows pending
        # self-authored rules above.
        self._standing_instructions: List[Dict[str, Any]] = []
        # Contested facts (M6, 2026-09-11) -- see SemanticMemory.
        # remember()'s confidence/provenance-weighted contradiction
        # resolution branch.
        self._contested_facts: List[Dict[str, Any]] = []
        self._grounding_violation_patterns: Dict[str, Any] = {}
        self._pending_patterns: List[Dict[str, Any]] = []
        self._recent_auto_promotions: List[Dict[str, Any]] = []
        # M8 (2026-09-11) -- LLM dependency telemetry, see
        # SemanticLearningBoundary.stats() / Brain.get_llm_dependency_stats().
        self._llm_dependency_stats: Dict[str, Any] = {}
        self._training_data_stats: Dict[str, Any] = {}
        # UK explicitly asked to be able to SEE idle memory
        # consolidation happen (episodic chat -> semantic facts) --
        # previously invisible on every surface (CLI, web, monitor.py)
        # even though bootstrap.py called it every idle tick. See
        # core/memory/memory_consolidator.py's rewritten .status().
        self._memory_consolidation: Dict[str, Any] = {}
        # UK's #5 -- learned native-response-template mining status,
        # same visibility discipline as memory consolidation above.
        self._native_response_learning: Dict[str, Any] = {}
        # UK's #1 (idiolect/typo learning) and #3 (spaced-repetition
        # decay) and #5 (metacognitive calibration) recall/learning/
        # memory proposals -- same visibility discipline as the rest.
        self._idiolect_status: Dict[str, Any] = {}
        self._memory_decay: Dict[str, Any] = {}
        self._calibration: Dict[str, Any] = {}
        # UK's #2 recall/learning/memory proposal -- procedural memory
        # (the formal third memory type) status.
        self._procedural_memory: Dict[str, Any] = {}
        self._llm_ready = False
        self._llm_provider_quota: Dict[str, Any] = {}
        self._runtime = "ONLINE"
        self._last_write = 0.0
        self._min_write_interval = 0.15  # seconds; only throttles high-frequency callers
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()

    # -----------------------------------------------------------
    # PIPELINE STAGE
    # -----------------------------------------------------------

    def set_stage(self, stage: str, detail: Optional[Dict[str, Any]] = None) -> None:
        stage = stage.upper()
        with self._lock:
            now = time.time()
            self._pipeline_trace.append({
                "stage": stage,
                "detail": detail or {},
                "timestamp": now,
                "duration_in_previous": round(now - self._stage_since, 4),
                "previous_stage": self._stage,
            })
            self._stage = stage
            self._stage_detail = detail or {}
            self._stage_since = now
        self._publish(force=True)

    # -----------------------------------------------------------
    # EXTRACTION CASCADE EVENTS
    # -----------------------------------------------------------

    def record_extraction(self, log_dict: Dict[str, Any]) -> None:
        with self._lock:
            log_dict = dict(log_dict)
            log_dict.setdefault("timestamp", time.time())
            self._extractions.append(log_dict)
            self._fallback_active = bool(log_dict.get("fallback_active", False))
        self._publish(force=True)

    # -----------------------------------------------------------
    # BACKGROUND LEARNING
    # -----------------------------------------------------------

    def update_learning(self, status: Optional[Dict[str, Any]] = None, active: Optional[bool] = None) -> None:
        with self._lock:
            if status:
                self._learning.update({
                    "alive": bool(status.get("alive", self._learning.get("alive", False))),
                    "pending": status.get("pending", self._learning.get("pending", 0)),
                    "processed": status.get("processed", self._learning.get("processed", 0)),
                    "failed": status.get("failed", self._learning.get("failed", 0)),
                    "dropped": status.get("dropped", self._learning.get("dropped", 0)),
                })
            if active is not None:
                self._learning["active"] = bool(active)
        self._publish(force=True)

    # -----------------------------------------------------------
    # INTERNAL LOG MIRROR
    # -----------------------------------------------------------

    def record_log(self, tag: str, message: str, level: str = "info") -> None:
        with self._lock:
            self._logs.append({"tag": tag, "message": message, "level": level, "timestamp": time.time()})
        self._publish(force=(level in ("error", "warning")))

    # -----------------------------------------------------------
    # COARSE ORGANISM HEALTH
    # -----------------------------------------------------------

    def update_organs(self, organs: Dict[str, Any]) -> None:
        with self._lock:
            self._organs = dict(organs)
        self._publish()

    def update_heartbeat(self, running: bool, beats: int, idle: bool) -> None:
        with self._lock:
            self._heartbeat = {"running": bool(running), "beats": int(beats), "idle": bool(idle)}
        self._publish()

    def record_idle_activity(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Store one idle-loop cycle result (see core/autonomy/idle_loop.py)
        so monitor.py/CLI can show what, if anything, JARVIS actually
        did during idle time -- not just a bare True/False flag."""
        entry = {
            "timestamp": time.time(),
            "event": event_name,
            "action": payload.get("action"),
            "goal": payload.get("goal"),
            "reason": payload.get("reason"),
            "step_index": payload.get("step_index"),
            "executed_count": len(payload.get("executed") or []),
            "awaiting_confirmation_count": len(payload.get("awaiting_confirmation") or []),
        }
        with self._lock:
            self._idle_activity.append(entry)
            self._idle_last = entry
        self._publish()

    def update_llm_ready(self, ready: bool) -> None:
        with self._lock:
            self._llm_ready = bool(ready)
        self._publish()

    def update_llm_provider_quota(self, quota: Dict[str, Any]) -> None:
        """Per-provider and per-key utilization, published for monitor.py.

        UK's requirement (2026-09-16): every key should be worn down
        evenly rather than one being exhausted while others sit idle --
        "sari keys weak se weak hoke use ho hamesha" -- and he wants to
        SEE that balance, per provider and per key, in monitor.py.

        Read-only telemetry: the provider engine already computes this
        while routing, so publishing it costs nothing extra and makes
        no network call of its own.
        """
        with self._lock:
            self._llm_provider_quota = quota if isinstance(quota, dict) else {}
        self._publish()

    def update_cognitive_metrics(self, dependency_metrics: Dict[str, Any], contradiction_rate: Optional[float], training_data_stats: Optional[Dict[str, Any]] = None) -> None:
        """DependencyMetrics + contradiction rate (see core/learning/
        dependency_metrics.py) -- the measurable answer to "is JARVIS
        actually needing the LLM less over time", now genuinely
        reaching monitor.py instead of only being reachable via /about
        or direct brain.status() calls nobody was making from here.
        training_data_stats (see core/learning/training_data_collector.py)
        is the real, on-disk progress toward a future locally-trained
        model -- how many labeled examples exist so far, and from
        which mechanism (native vs LLM) they came from."""
        with self._lock:
            self._dependency_metrics = dict(dependency_metrics or {})
            self._contradiction_rate = contradiction_rate
            if training_data_stats is not None:
                self._training_data_stats = dict(training_data_stats)
        self._publish()

    def update_evolution_summary(self, proposals: Dict[str, Dict[str, Any]]) -> None:
        """Summary of ControlledEvolutionEngine's proposals by status
        (PROPOSED/VALIDATED/APPROVED/APPLIED/REJECTED) -- so "did
        evolution actually happen" has a real, visible answer instead
        of requiring a person to go dig through brain.evolution.proposals
        by hand."""
        counts: Dict[str, int] = {}
        latest = None
        for proposal in (proposals or {}).values():
            if not isinstance(proposal, dict):
                continue
            status = str(proposal.get("status", "UNKNOWN"))
            counts[status] = counts.get(status, 0) + 1
            if latest is None or proposal.get("created_at", 0) > latest.get("created_at", 0):
                latest = proposal
        with self._lock:
            self._evolution_summary = {
                "counts": counts,
                "total": sum(counts.values()),
                "latest_target": latest.get("target") if latest else None,
                "latest_reason": latest.get("reason") if latest else None,
                "latest_status": latest.get("status") if latest else None,
            }
        self._publish()

    def update_latest_reasoning(self, trace: Dict[str, Any]) -> None:
        """Latest post-response reasoning cycle result (see
        core/learning/post_response_reasoning.py) -- the FULL
        11-question self-reflection, now actually visible instead of
        only living in brain.last_reasoning_traces where nothing
        outside the process could ever see it. Previously only a
        5-field summary was kept here (mode/should_change/adopt/
        next_time/timestamp) -- monitor.py could only ever show a
        computed conclusion, never the actual Q&A a person could
        verify. All 11 fields are kept now so the full trace can be
        rendered, not just a summary of it."""
        if not isinstance(trace, dict):
            return
        with self._lock:
            self._latest_reasoning = {
                "mode": trace.get("mode"),
                "what_and_why": trace.get("what_and_why"),
                "expected_outcome": trace.get("expected_outcome"),
                "actual_outcome": trace.get("actual_outcome"),
                "outcome_gap_reason": trace.get("outcome_gap_reason"),
                "new_learning": trace.get("new_learning"),
                "capability_check": trace.get("capability_check"),
                "strategy_evidence": trace.get("strategy_evidence"),
                "should_change_strategy": trace.get("should_change_strategy"),
                "change_reason": trace.get("change_reason"),
                "evidence_reliability": trace.get("evidence_reliability"),
                "next_time_different": trace.get("next_time_different"),
                "adopt_as_learning": trace.get("adopt_as_learning"),
                "llm_cost": dict(trace.get("llm_cost") or {}),
                "timestamp": trace.get("timestamp", time.time()),
            }
        self._publish()

    def update_pending_self_rules(self, pending: Any) -> None:
        """Snapshot of Brain.list_pending_self_rules() -- JARVIS-proposed
        rules awaiting UK's /confirm_rule or /reject_rule. Read-only
        mirror; confirming/rejecting still only happens through Brain."""
        if not isinstance(pending, list):
            return
        with self._lock:
            self._pending_self_rules = [dict(item) for item in pending if isinstance(item, dict)]
        self._publish()

    def update_tool_call_trace(self, trace: Any) -> None:
        """Snapshot of Brain.last_tool_call_trace (see
        core/orchestration/tool_registry.py) -- most recent turn's
        LLM tool-call proposals and their gated results."""
        if not isinstance(trace, list):
            return
        with self._lock:
            self._latest_tool_calls = [dict(item) for item in trace if isinstance(item, dict)]
        self._publish()

    def update_standing_instructions(self, instructions: Any) -> None:
        """Snapshot of Brain.list_standing_instructions(). Read-only
        mirror; managing them still only happens through Brain/cli.py's
        /instructions, /remove_instruction."""
        if not isinstance(instructions, list):
            return
        with self._lock:
            self._standing_instructions = [dict(item) for item in instructions if isinstance(item, dict)]
        self._publish()

    def update_contested_facts(self, facts: Any) -> None:
        """Snapshot of Brain.list_contested_facts() (M6)."""
        if not isinstance(facts, list):
            return
        with self._lock:
            self._contested_facts = [dict(item) for item in facts if isinstance(item, dict)]
        self._publish()

    def update_grounding_violation_patterns(self, patterns: Any) -> None:
        """Snapshot of Brain.get_grounding_violation_patterns()."""
        if not isinstance(patterns, dict):
            return
        with self._lock:
            self._grounding_violation_patterns = dict(patterns)
        self._publish()

    def update_pending_patterns(self, items: Any) -> None:
        if not isinstance(items, list):
            return
        with self._lock:
            self._pending_patterns = [dict(i) for i in items if isinstance(i, dict)]
        self._publish()

    def update_recent_auto_promotions(self, items: Any) -> None:
        if not isinstance(items, list):
            return
        with self._lock:
            self._recent_auto_promotions = [dict(i) for i in items if isinstance(i, dict)]
        self._publish()

    def update_llm_dependency_stats(self, stats: Any) -> None:
        """Snapshot of Brain.get_llm_dependency_stats() (M8)."""
        if not isinstance(stats, dict):
            return
        with self._lock:
            self._llm_dependency_stats = dict(stats)
        self._publish()

    def update_memory_consolidation(self, result: Dict[str, Any]) -> None:
        """Idle-time episodic -> semantic consolidation result (see
        core/memory/memory_consolidator.py). UK's explicit ask: this
        must be visible somewhere, not just a silent background call
        with no observable effect."""
        if not isinstance(result, dict):
            return
        with self._lock:
            self._memory_consolidation = dict(result)
        self._publish()

    def update_native_response_learning(self, status: Dict[str, Any]) -> None:
        """UK's #5 -- native response template mining/hit status (see
        core/learning/native_response_learning.py)."""
        if not isinstance(status, dict):
            return
        with self._lock:
            self._native_response_learning = dict(status)
        self._publish()

    def update_idiolect_status(self, status: Dict[str, Any]) -> None:
        """UK's #1 recall/learning/memory proposal -- personal typo/
        idiolect learning status (see core/cognition/translator.py's
        idiolect_status())."""
        if not isinstance(status, dict):
            return
        with self._lock:
            self._idiolect_status = dict(status)
        self._publish()

    def update_memory_decay(self, result: Dict[str, Any]) -> None:
        """UK's #3 recall/learning/memory proposal -- spaced-
        repetition-inspired confidence decay for unused facts (see
        SemanticMemory.decay_unused())."""
        if not isinstance(result, dict):
            return
        with self._lock:
            self._memory_decay = dict(result)
        self._publish()

    def update_calibration(self, report: Dict[str, Any]) -> None:
        """UK's #5 recall/learning/memory proposal -- metacognitive
        calibration report (see core/learning/metacognition.py)."""
        if not isinstance(report, dict):
            return
        with self._lock:
            self._calibration = dict(report)
        self._publish()

    def update_procedural_memory(self, status: Dict[str, Any]) -> None:
        """UK's #2 recall/learning/memory proposal -- procedural
        memory (see core/memory/procedural_memory.py)."""
        if not isinstance(status, dict):
            return
        with self._lock:
            self._procedural_memory = dict(status)
        self._publish()

    # -----------------------------------------------------------
    # SNAPSHOT / PUBLISH
    # -----------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "pid": os.getpid(),
                "updated_at": time.time(),
                "runtime": self._runtime,
                "stage": self._stage,
                "stage_detail": dict(self._stage_detail),
                "stage_since": self._stage_since,
                "fallback_active": self._fallback_active,
                "pipeline_trace": list(self._pipeline_trace),
                "extractions": list(self._extractions),
                "learning": dict(self._learning),
                "logs": list(self._logs),
                "organs": dict(self._organs),
                "heartbeat": dict(self._heartbeat),
                "llm_ready": self._llm_ready,
                "llm_provider_quota": self._llm_provider_quota,
                "idle_activity": list(self._idle_activity),
                "idle_last": dict(self._idle_last),
                "dependency_metrics": dict(self._dependency_metrics),
                "contradiction_rate": self._contradiction_rate,
                "evolution_summary": dict(self._evolution_summary),
                "latest_reasoning": dict(self._latest_reasoning),
                "latest_tool_calls": list(self._latest_tool_calls),
                "pending_self_rules": list(self._pending_self_rules),
                "standing_instructions": list(self._standing_instructions),
                "contested_facts": list(self._contested_facts),
                "grounding_violation_patterns": dict(self._grounding_violation_patterns),
                "pending_patterns": list(self._pending_patterns),
                "recent_auto_promotions": list(self._recent_auto_promotions),
                "llm_dependency_stats": dict(self._llm_dependency_stats),
                "training_data_stats": dict(self._training_data_stats),
                "memory_consolidation": dict(self._memory_consolidation),
                "native_response_learning": dict(self._native_response_learning),
                "idiolect_status": dict(self._idiolect_status),
                "memory_decay": dict(self._memory_decay),
                "calibration": dict(self._calibration),
                "procedural_memory": dict(self._procedural_memory),
            }

    def _publish(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_write) < self._min_write_interval:
            return
        self._last_write = now
        snapshot = self.snapshot()
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".jarvis_state_", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(snapshot, handle, ensure_ascii=False, separators=(",", ":"))
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
        except OSError:
            pass  # publishing must never break the calling organ

    # -----------------------------------------------------------
    # EVENT BUS INTEGRATION (optional, in-process convenience)
    # -----------------------------------------------------------

    _STAGE_BY_EVENT = {
        "BRAIN_CYCLE_STARTED": "PERCEIVING",
        "PERCEPTION_COMPLETED": "INDEXING",
        "CONTEXT_RETRIEVAL_STARTED": "INDEXING",
        "COGNITION_ROUTED": "EXECUTING",
        "BRAIN_CYCLE_COMPLETED": "IDLE",
    }

    def attach(self, jarvis: Any = None, brain: Any = None, event_bus: Any = None, poll_interval: float = 2.0) -> None:
        """Wire this bus into an already-running organism.

        Subscribes to the organism's existing EventBus (wildcard) to
        derive pipeline-stage transitions from events Brain already
        emits, and starts a low-frequency background poll for organ/
        heartbeat/learning-queue health -- the same coarse telemetry
        the old OrganismCLIMonitor collected, just centralized here so
        both cli.py and monitor.py read one consistent file.
        """
        bus = event_bus or getattr(jarvis, "event_bus", None)
        if bus is not None and hasattr(bus, "subscribe"):
            def _on_event(event, _self=self) -> None:
                name = getattr(event, "name", "")
                stage = _self._STAGE_BY_EVENT.get(name)
                if stage:
                    _self.set_stage(stage, detail={"event": name})
                if name == "BRAIN_CYCLE_COMPLETED" and brain is not None:
                    try:
                        queue_status = brain.status().get("async_learning_queue", {})
                        _self.update_learning(status=queue_status)
                    except Exception:
                        pass
                if name in ("IDLE_CYCLE_COMPLETE", "IDLE_CYCLE_NOOP"):
                    try:
                        payload = getattr(event, "payload", None) or getattr(event, "data", None) or {}
                        _self.record_idle_activity(name, payload if isinstance(payload, dict) else {})
                    except Exception:
                        pass
                if name == "MEMORY_DECAY_COMPLETED":
                    try:
                        payload = getattr(event, "payload", None) or getattr(event, "data", None) or {}
                        _self.update_memory_decay(payload if isinstance(payload, dict) else {})
                    except Exception:
                        pass
            try:
                bus.subscribe("*", _on_event)
            except Exception:
                pass

        if jarvis is not None or brain is not None:
            self._start_poll(jarvis=jarvis, brain=brain, interval=poll_interval)

    def _start_poll(self, jarvis: Any, brain: Any, interval: float) -> None:
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()

        def _loop() -> None:
            while not self._poll_stop.wait(interval):
                try:
                    organs = jarvis.get_organ_status() if jarvis is not None and hasattr(jarvis, "get_organ_status") else {}
                    self.update_organs(organs)
                except Exception:
                    pass
                try:
                    hb = jarvis.heartbeat if jarvis is not None else None
                    status = hb.status() if hb is not None and hasattr(hb, "status") else {}
                    self.update_heartbeat(
                        running=bool(status.get("running", False)),
                        beats=int(status.get("beat_count", 0)),
                        idle=bool(status.get("is_idle", True)),
                    )
                except Exception:
                    pass
                try:
                    llm = getattr(brain, "llm", None) if brain is not None else None
                    # llm_ready=False BUG (2026-09-13, UK's monitor):
                    # HybridLLMBridge.is_ready starts False and only
                    # flips True INSIDE a successful generate() call. So
                    # straight after a restart -- exactly when the idle
                    # loop runs first -- the organism reported its own
                    # LLM as unavailable even though it was configured
                    # and working, and anything gated on readiness sat
                    # out the whole idle window.
                    #
                    # Readiness now means "can this backend be used",
                    # which is a property of configuration, with the
                    # proven-working flag still winning when set. This
                    # stays honest: if no backend is configured at all,
                    # it still reports False.
                    ready = False
                    if llm is not None:
                        ready = bool(getattr(llm, "is_ready", False))
                        if not ready:
                            for probe in ("is_available", "has_usable_backend"):
                                checker = getattr(llm, probe, None)
                                if callable(checker):
                                    try:
                                        ready = bool(checker())
                                        break
                                    except Exception:
                                        pass
                            else:
                                # No probe exposed -- fall back to whether a
                                # backend is configured at all.
                                ready = bool(
                                    getattr(llm, "_groq_engine", None)
                                    or getattr(llm, "_local_engine", None)
                                    or getattr(llm, "api_key", None)
                                )
                    self.update_llm_ready(ready)
                except Exception:
                    pass
                try:
                    if brain is not None:
                        full_status = brain.status()
                        queue_status = full_status.get("async_learning_queue", {})
                        self.update_learning(status=queue_status)
                        try:
                            from ..learning.training_data_collector import get_training_data_collector
                            training_stats = get_training_data_collector().stats()
                        except Exception:
                            training_stats = None
                        self.update_cognitive_metrics(
                            dependency_metrics=full_status.get("dependency_metrics", {}),
                            contradiction_rate=full_status.get("contradiction_rate"),
                            training_data_stats=training_stats,
                        )
                except Exception:
                    pass
                try:
                    evolution = getattr(brain, "evolution", None) if brain is not None else None
                    proposals = getattr(evolution, "proposals", None) if evolution is not None else None
                    if isinstance(proposals, dict):
                        self.update_evolution_summary(proposals)
                except Exception:
                    pass
                try:
                    traces = getattr(brain, "last_reasoning_traces", None) if brain is not None else None
                    if traces:
                        self.update_latest_reasoning(traces[-1])
                except Exception:
                    pass
                try:
                    tool_trace = getattr(brain, "last_tool_call_trace", None) if brain is not None else None
                    if tool_trace is not None:
                        self.update_tool_call_trace(tool_trace)
                except Exception:
                    pass
                try:
                    if brain is not None and hasattr(brain, "list_pending_self_rules"):
                        self.update_pending_self_rules(brain.list_pending_self_rules())
                except Exception:
                    pass
                try:
                    if brain is not None and hasattr(brain, "list_standing_instructions"):
                        self.update_standing_instructions(brain.list_standing_instructions())
                except Exception:
                    pass
                try:
                    if brain is not None and hasattr(brain, "list_contested_facts"):
                        self.update_contested_facts(brain.list_contested_facts())
                except Exception:
                    pass
                try:
                    if brain is not None and hasattr(brain, "get_grounding_violation_patterns"):
                        self.update_grounding_violation_patterns(brain.get_grounding_violation_patterns())
                except Exception:
                    pass
                try:
                    if brain is not None and hasattr(brain, "list_pending_patterns"):
                        self.update_pending_patterns(brain.list_pending_patterns())
                except Exception:
                    pass
                try:
                    if brain is not None and hasattr(brain, "get_recent_auto_promotions"):
                        self.update_recent_auto_promotions(brain.get_recent_auto_promotions())
                except Exception:
                    pass
                try:
                    if brain is not None and hasattr(brain, "get_llm_dependency_stats"):
                        self.update_llm_dependency_stats(brain.get_llm_dependency_stats())
                except Exception:
                    pass
                try:
                    consolidator = getattr(brain, "consolidator", None) if brain is not None else None
                    if consolidator is not None and hasattr(consolidator, "status"):
                        self.update_memory_consolidation(consolidator.status())
                except Exception:
                    pass
                try:
                    learner = getattr(brain, "native_response_learner", None) if brain is not None else None
                    if learner is not None and hasattr(learner, "status"):
                        self.update_native_response_learning(learner.status())
                except Exception:
                    pass
                try:
                    from ..cognition.translator import idiolect_status
                    self.update_idiolect_status(idiolect_status())
                except Exception:
                    pass
                try:
                    from ..learning.metacognition import calibration_report
                    memory = getattr(brain, "memory", None) if brain is not None else None
                    if memory is not None:
                        self.update_calibration(calibration_report(memory))
                except Exception:
                    pass
                try:
                    proc_mem = getattr(brain, "procedural_memory", None) if brain is not None else None
                    if proc_mem is not None and hasattr(proc_mem, "status"):
                        self.update_procedural_memory(proc_mem.status())
                except Exception:
                    pass

        self._poll_thread = threading.Thread(target=_loop, name="jarvis-state-bus-poll", daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._poll_stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None
        # Publish a final OFFLINE snapshot instead of deleting the file:
        # a monitor watching this path should see an explicit shutdown
        # state, not have the file silently vanish and sit at "waiting
        # for state...".
        with self._lock:
            self._runtime = "OFFLINE"
            self._stage = "IDLE"
        self._publish(force=True)


# =====================================================================
# PROCESS-WIDE SINGLETON
# =====================================================================

_singleton: Optional[StateBus] = None
_singleton_lock = threading.Lock()


def get_state_bus(create: bool = True) -> Optional[StateBus]:
    """Return the process-wide StateBus, creating it on first use.

    `create=False` lets low-level callers (core.runtime.log,
    core.contracts.extraction) mirror events into the bus *if one is
    already running* without forcing every standalone script/test
    that merely imports those modules to spin up an IPC file.
    """
    global _singleton
    if _singleton is not None:
        return _singleton
    if not create:
        return None
    with _singleton_lock:
        if _singleton is None:
            _singleton = StateBus()
        return _singleton


def read_snapshot(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Read-only disk read for a *different* process (e.g. monitor.py).

    monitor.py intentionally keeps its own tiny copy of this function
    so it never has to import anything beyond the stdlib -- this
    version is provided for in-process callers (tests, backend routes)
    that already import core.runtime.state_bus for other reasons.
    """
    target = path or _resolve_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None
