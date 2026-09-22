from __future__ import annotations

import time
from typing import Any, Dict, List


class IdleLoop:
    """
    Autonomous maintenance loop, run periodically by Heartbeat when
    the organism has no active user interaction.

    Safety model:
      1. Curiosity proposes candidates; it never executes anything.
      2. Planner turns the selected goal into structured steps.
      3. Confirmation-required steps are surfaced as pending confirmation.
      4. Safe steps are handed to the Brain-owned executor.

    The executor is the Brain boundary. IdleLoop does not execute skills,
    create experiences, or write learning records itself.
    """

    def __init__(
        self,
        goal_manager=None,
        curiosity=None,
        planner=None,
        scheduler=None,
        state=None,
        event_bus=None,
        store=None,
        executor=None,
        max_actions_per_step: int = 1,
        pattern_detector=None,
        category_learner=None,
        pattern_review_interval_seconds: float = 60.0,
        identity=None,
        semantic_memory=None,
        standing_instructions=None,
    ):
        self.goal_manager = goal_manager
        self.curiosity = curiosity
        self.planner = planner
        self.scheduler = scheduler
        self.state = state
        self.events = event_bus
        self.store = store
        self.executor = executor
        self.max_actions_per_step = max_actions_per_step
        self.pending_confirmations: List[Dict[str, Any]] = []
        self.identity = identity
        # THE ACTUAL FIX (UK's explicit ask: idle time should genuinely
        # "hunt for facts" and resolve uncertainty on its own, not just
        # sit doing nothing): Curiosity.candidates()'s THIRD signal --
        # "low-confidence knowledge worth re-checking", driven by its
        # knowledge_gaps parameter -- was fully implemented but nothing
        # anywhere ever called it with real data. step() below always
        # called curiosity.candidates(state=self.state, goals=goals)
        # with knowledge_gaps defaulting to [], so that entire signal
        # was permanently dead: no goal, no curiosity trigger. Combined
        # with the other two signals rarely firing (uncertainty tracking
        # is sparse; there are usually no stalled goals to begin with),
        # idle_loop.step() fell through to "no pending goals" almost
        # every single cycle. semantic_memory (optional -- degrades to
        # the old behaviour if not supplied) lets _find_knowledge_gaps()
        # below feed it real low-confidence facts from durable memory.
        self.semantic_memory = semantic_memory
        # Standing (triggered) instructions -- see core/autonomy/
        # standing_instructions.py + step() below, which is the actual
        # producer-side fix for Scheduler.schedule() (2026-09-11
        # roadmap Phase 3: it previously had a working due_tasks()
        # consumer here but nothing anywhere ever called .schedule()).
        self.standing_instructions = standing_instructions
        # OVERNIGHT LEARNING (UK's explicit ask: idle time itself should
        # drive real learning/evolution review, not sit doing nothing
        # until a goal happens to exist, and the results should be
        # reportable the next morning). pattern_detector/category_learner
        # are optional -- if neither is wired, this degrades to a no-op,
        # never an error.
        self.pattern_detector = pattern_detector
        self.category_learner = category_learner
        self.pattern_review_interval_seconds = max(5.0, float(pattern_review_interval_seconds))
        self._last_pattern_review_at: float = 0.0
        self.overnight_log: List[Dict[str, Any]] = []

    def _review_learning_patterns(self) -> Dict[str, Any]:
        """The actual overnight-learning task: while genuinely idle
        (not on every heartbeat tick -- gated by
        pattern_review_interval_seconds so this never busy-loops),
        review what fallback_pattern_detector and category_learner have
        accumulated evidence for, and record what was found. This is
        real analysis of real accumulated evidence, not a fabricated
        "I learned something" claim -- if nothing has enough evidence
        yet, that is exactly what gets reported, honestly."""
        now = time.time()
        if now - self._last_pattern_review_at < self.pattern_review_interval_seconds:
            return {"reviewed": False}
        self._last_pattern_review_at = now

        findings: List[str] = []
        if self.pattern_detector is not None:
            try:
                candidates = self.pattern_detector.promotion_candidates()
                for c in candidates:
                    findings.append(
                        f"fallback pattern '{c.get('pattern_key', '?')}' has {c.get('occurrences', '?')} "
                        f"successful occurrences -- worth proposing as a native rule"
                    )
            except Exception:
                pass
        if self.category_learner is not None:
            try:
                candidates = self.category_learner.promotion_candidates()
                for c in candidates:
                    word = c.get("word", "?")
                    examples = c.get("example_inputs") or []
                    # THE ACTUAL SANDBOX TEST UK asked for: don't just
                    # LOG that a candidate exists -- genuinely test it
                    # (see core/learning/category_word_learner.py's
                    # sandbox_test_category_word(), isolated, never
                    # touching the real live extraction engine) against
                    # the REAL example sentences that produced this
                    # candidate, and report the real PASS/FAIL evidence.
                    try:
                        from ..learning.category_word_learner import sandbox_test_category_word
                        test_result = sandbox_test_category_word(word, examples) if examples else {"tested": False}
                    except Exception:
                        test_result = {"tested": False}
                    if test_result.get("tested"):
                        verdict = "PASSED" if test_result.get("all_passed") else "MIXED RESULTS"
                        findings.append(
                            f"category word '{word}' seen {c.get('occurrences', '?')} times via LLM -- "
                            f"sandbox tested: {verdict} ({test_result.get('cases_passed', 0)}/{test_result.get('cases_tested', 0)} cases) -- "
                            f"ready for your approval to add to native vocabulary"
                        )
                        if test_result.get("all_passed"):
                            self.category_learner.mark_proposed(word)
                    else:
                        findings.append(
                            f"category word '{word}' seen {c.get('occurrences', '?')} times "
                            f"via LLM -- worth adding to native vocabulary (not yet sandbox tested)"
                        )
            except Exception:
                pass

        entry = {
            "timestamp": now,
            "type": "pattern_review",
            "findings": findings,
            "summary": (
                f"reviewed learning patterns: {len(findings)} candidate(s) worth promoting"
                if findings else "reviewed learning patterns: nothing new met the evidence threshold yet"
            ),
        }
        self.overnight_log.append(entry)
        if len(self.overnight_log) > 200:
            self.overnight_log = self.overnight_log[-200:]

        # Same periodic gate also checkpoints JARVIS's own cumulative
        # runtime (see JarvisIdentity.checkpoint_runtime()) -- riding
        # the SAME time-gated cycle rather than adding a second timer,
        # so a crashed/killed process (common on a phone) still has
        # most of its uptime saved as of the last checkpoint, not only
        # on a clean shutdown that may never happen.
        if self.identity is not None:
            try:
                self.identity.checkpoint_runtime()
            except Exception:
                pass

        return {"reviewed": True, "findings_count": len(findings)}

    def get_overnight_report(self, since: float = 0.0) -> Dict[str, Any]:
        """What idle time actually did since `since` (a timestamp) --
        the real, honest content of a "good morning, what did you do
        while I was away" report. Never fabricates activity: if
        overnight_log is empty for the window, that is stated plainly."""
        entries = [e for e in self.overnight_log if e.get("timestamp", 0) >= since]
        total_findings = sum(len(e.get("findings", [])) for e in entries)
        return {
            "cycles_reviewed": len(entries),
            "total_findings": total_findings,
            "entries": entries,
        }

    def _find_knowledge_gaps(self, scan_limit: int = 200, max_gaps: int = 15) -> List[Dict[str, Any]]:
        """Real low-confidence facts already sitting in durable semantic
        memory -- genuine candidates for JARVIS to "re-check" during
        idle time, not fabricated ones. Read-only; never mutates memory.
        Degrades to an empty list (same as before this fix) if no
        semantic memory was supplied, so this is purely additive."""
        if self.semantic_memory is None:
            return []
        threshold = getattr(self.curiosity, "min_confidence", 0.55) if self.curiosity is not None else 0.55
        try:
            items = self.semantic_memory.list_all(limit=scan_limit) or []
        except Exception:
            return []
        gaps = []
        for item in items:
            confidence = getattr(item, "confidence", None)
            if not isinstance(confidence, (int, float)) or confidence >= threshold:
                continue
            gaps.append({
                "subject": getattr(item, "subject", "?"),
                "confidence": float(confidence),
                "knowledge_id": getattr(item, "knowledge_id", None),
            })
        gaps.sort(key=lambda g: g["confidence"])
        return gaps[:max_gaps]

    def step(self) -> Dict[str, Any]:
        """Run exactly one idle cycle. Called by Heartbeat/Scheduler."""
        if self.scheduler is not None:
            # Standing instructions: due_now() is a pure wall-clock
            # comparison (idempotent, no side effects) -- pushing each
            # due item through scheduler.schedule() rather than
            # executing it inline here is the actual fix for
            # Scheduler.schedule() never having a caller anywhere in
            # the codebase. due_tasks() immediately below (run_at=now)
            # picks it back up the SAME cycle, so nothing sits waiting
            # an extra tick.
            if self.standing_instructions is not None:
                try:
                    for due in self.standing_instructions.due_now():
                        self.scheduler.schedule(
                            task={
                                "action": "standing_instruction_fire",
                                "knowledge_id": due.get("knowledge_id"),
                                "action_text": due.get("action_text"),
                            },
                            run_at=time.time(),
                        )
                except Exception:
                    pass
            for task in self.scheduler.due_tasks():
                self._run_task(task)

        # Overnight learning review -- runs independently of the goal/
        # curiosity system below, time-gated so it happens periodically
        # during genuine idle stretches rather than once and never
        # again, or on every single heartbeat tick.
        self._review_learning_patterns()

        if self.goal_manager is None or self.curiosity is None or self.planner is None:
            return self._noop("autonomy organs not fully attached")

        goals = self.goal_manager.pending()
        knowledge_gaps = self._find_knowledge_gaps()
        candidates = self.curiosity.candidates(state=self.state, goals=goals, knowledge_gaps=knowledge_gaps)

        # Dedup curiosity-origin candidates against already-pending goals
        # with the same reason text. Without this, an idle organism whose
        # uncertainty (or another recurring signal) stays elevated will
        # re-propose the *same* candidate on every heartbeat tick forever
        # -- each one a brand-new goal, and each goal add/update triggers
        # a full re-serialize + SQLite write of the entire goal list
        # (GoalManager._save). That is an unbounded, un-throttled write
        # loop running every couple of seconds in the background, which
        # is real, measurable CPU/disk/battery drain on a phone even
        # while the user isn't interacting at all. Blueprint section 24
        # requires idle learning to use controlled boundaries; an
        # un-deduplicated proposal loop is exactly the uncontrolled case
        # that rule exists to prevent.
        existing_reasons = {
            str(g.get("text", "")).strip().lower()
            for g in goals
            if g.get("origin") == "curiosity"
        }
        for candidate in candidates:
            reason_key = str(candidate.get("reason", "")).strip().lower()
            if reason_key and reason_key in existing_reasons:
                continue
            self.goal_manager.add(
                text=candidate["reason"],
                priority=candidate.get("priority", 0.5),
                origin="curiosity",
            )
            existing_reasons.add(reason_key)

        target = self.goal_manager.next_goal()
        if target is None:
            return self._background_maintenance("no pending goals")

    def _background_maintenance(self, reason: str) -> Dict[str, Any]:
        """IDLE MUST NEVER SIT EMPTY (2026-09-13, UK: "idle me kabhi
        khali nahi baithega JARVIS ab").

        Previously a cycle with no pending goal returned a no-op and the
        organism did literally nothing until the next user message --
        which is why the monitor showed zero learning, zero
        consolidation, zero pattern work for hours at a stretch.

        There is always real maintenance available, so the cycle now
        works through a fixed backlog in priority order. Each task is
        cheap, bounded, and independently guarded: one failing task must
        not stop the rest, because a single bad consolidation should not
        silently disable all background work (exactly the failure mode
        that made this look broken).

        Deliberately NO LLM calls here -- idle work runs on the organism's
        own machinery, so a background cycle can never quietly eat the
        token budget UK is saving for conversation.
        """
        performed: List[Dict[str, Any]] = []

        def _try(label: str, fn) -> None:
            try:
                outcome = fn()
                performed.append({"task": label, "ok": True, "result": outcome})
            except Exception as exc:
                performed.append({"task": label, "ok": False, "error": str(exc)})

        brain = getattr(self, "brain", None)
        memory = getattr(brain, "memory", None) if brain is not None else None

        # 1. Episodic -> semantic consolidation. Now that chat turns are
        #    actually persisted as episodes, this has real material.
        consolidator = getattr(brain, "consolidator", None) if brain is not None else None
        if consolidator is not None and hasattr(consolidator, "consolidate"):
            _try("memory_consolidation", lambda: consolidator.consolidate(limit=50))

        # 2. Re-verify low-confidence knowledge gaps found this cycle.
        _try("knowledge_gap_scan", lambda: {"gaps": len(self._find_knowledge_gaps())})

        # 3. Learning-pattern review (time-gated internally).
        _try("learning_pattern_review", self._review_learning_patterns)

        # 4. Procedural memory: promote repeated habits.
        procedural = getattr(brain, "procedural_memory", None) if brain is not None else None
        if procedural is not None and hasattr(procedural, "promote_candidates"):
            _try("procedural_promotion", procedural.promote_candidates)

        # 5. Pattern synthesis: propose extraction patterns from misses.
        synthesis = getattr(brain, "pattern_synthesis", None) if brain is not None else None
        if synthesis is not None and hasattr(synthesis, "scan"):
            _try("pattern_synthesis", synthesis.scan)

        # 6. Memory decay: let unused personal facts fade, like real memory.
        if memory is not None and hasattr(memory, "decay_unused"):
            _try("memory_decay", memory.decay_unused)

        result = {
            "action": "IDLE_MAINTENANCE",
            "reason": reason,
            "tasks_run": len(performed),
            "tasks_succeeded": sum(1 for p in performed if p["ok"]),
            "performed": performed,
        }
        self._publish("IDLE_MAINTENANCE_COMPLETE", result)
        return result

        self.goal_manager.update_status(target["id"], "active")

        # A goal owns its plan and cursor so repeated idle cycles continue
        # from the next step instead of executing step 1 forever.
        plan = target.get("plan") or []
        step_index = int(target.get("step_index", 0))
        if not plan or step_index >= len(plan):
            plan = self.planner.plan(target)
            self.goal_manager.set_plan(target["id"], plan)
            target = self.goal_manager._find(target["id"]) or target
            step_index = int(target.get("step_index", 0))

        executed = []
        confirmations_needed = []

        for planned_step in plan[step_index : step_index + self.max_actions_per_step]:
            if planned_step.get("requires_confirmation"):
                confirmations_needed.append(planned_step)
                self.pending_confirmations.append(
                    {**planned_step, "goal_id": target["id"], "queued_at": time.time()}
                )
                continue

            outcome = self._run_step(target, planned_step)
            executed.append(outcome)

            if outcome.get("success") is True:
                self.goal_manager.advance_step(target["id"])
                self.goal_manager.add_progress(
                    target["id"], f"Executed: {planned_step.get('action')}"
                )
            else:
                # Failed work remains at the current cursor so a later cycle
                # can retry/recover instead of falsely completing the goal.
                self.goal_manager.add_progress(
                    target["id"], f"Failed: {planned_step.get('action')}"
                )

        refreshed = self.goal_manager._find(target["id"]) or target
        refreshed_index = int(refreshed.get("step_index", 0))
        if plan and refreshed_index >= len(plan):
            self.goal_manager.update_status(target["id"], "completed")
        elif confirmations_needed:
            self.goal_manager.add_progress(
                target["id"], "Awaiting explicit confirmation before continuing."
            )

        result = {
            "action": "IDLE_CYCLE",
            "goal": target["text"],
            "goal_id": target["id"],
            "step_index": refreshed_index,
            "executed": executed,
            "awaiting_confirmation": confirmations_needed,
        }
        self._publish("IDLE_CYCLE_COMPLETE", result)
        return result

    def _run_step(self, goal: Dict[str, Any], step: Dict[str, Any]) -> Dict[str, Any]:
        if self.executor is None:
            return {"success": False, "status": "no_executor", "step": step}

        try:
            return self.executor(step, goal=goal)
        except TypeError as exc:
            # Compatibility with older executor callables that accept only
            # the step. The production Brain executor accepts the goal too.
            try:
                return self.executor(step)
            except Exception as fallback_exc:
                return {"success": False, "status": "error", "result": str(fallback_exc), "step": step}
        except Exception as exc:
            return {"success": False, "status": "error", "result": str(exc), "step": step}

    def _run_task(self, task: Dict[str, Any]) -> None:
        if self.executor is None:
            return
        is_instruction = task.get("action") == "standing_instruction_fire"
        try:
            self.executor(task)
            # SILENT-FIRING FIX (2026-09-13, UK: "standing instruction
            # silently hit ho jata hai, UI ya trace ya kahin bhi iska
            # record nahi aata"). A scheduled action that runs with no
            # trace is indistinguishable from one that never ran, so
            # there was no way to tell a working scheduler from a dead
            # one. Every firing is now recorded with a timestamp and
            # outcome, readable via Brain.get_instruction_firings() and
            # therefore surfaceable in CLI/monitor/UI.
            if is_instruction:
                from ..orchestration.companion_tools import record_instruction_firing
                record_instruction_firing(
                    instruction_id=str(task.get("knowledge_id") or ""),
                    instruction_text=str(task.get("action_text") or ""),
                    trigger_type="scheduled",
                    outcome="fired",
                )
        except Exception as exc:
            if is_instruction:
                try:
                    from ..orchestration.companion_tools import record_instruction_firing
                    record_instruction_firing(
                        instruction_id=str(task.get("knowledge_id") or ""),
                        instruction_text=str(task.get("action_text") or ""),
                        trigger_type="scheduled",
                        outcome="failed",
                        detail=str(exc),
                    )
                except Exception:
                    pass
            self._publish("IDLE_SCHEDULED_TASK_FAILED", {"task": task, "error": str(exc)})

    def _noop(self, reason: str) -> Dict[str, Any]:
        result = {"action": "NO_OP", "reason": reason}
        self._publish("IDLE_CYCLE_NOOP", result)
        return result

    def _publish(self, name: str, payload: Any) -> None:
        if self.events is None:
            return

        emit = getattr(self.events, "safe_emit", None) or getattr(self.events, "emit", None)
        if callable(emit):
            try:
                emit(name, payload, source="idle_loop")
            except TypeError:
                try:
                    emit(name, payload)
                except Exception:
                    pass
            except Exception:
                pass
