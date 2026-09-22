from __future__ import annotations

"""CODING AGENT -- bounded, dependency-aware, rate-limit-safe concurrency.

UK's explicit spec (2026-09-16): real parallel workers, but --
  - only genuinely independent work runs concurrently
  - dependency ordering is preserved
  - queue/backpressure, timeout, and retry are real, not decorative
  - JARVIS stays the single orchestrator: this file's plain Python
    scheduler decides WHEN things run; the LLM only ever proposes WHAT
    the sub-objectives are and which ones depend on which (see
    agent.py's run_parallel_subtasks) -- it never controls scheduling.

TWO SEPARATE SAFETY MECHANISMS, deliberately not merged into one:
  1. RateLimiter (this file) -- bounds how many/how often WORKER
     THREADS may call the LLM at once. The default interval (0.8s)
     is the SAME number task_loop.py already uses for its own
     STEP_PACING_SECONDS -- reused, not reinvented, because it is the
     value UK's own single-threaded loop already found necessary to
     avoid tripping provider rate limits.
  2. ToolRegistry's write lock (tool_contract.py, added alongside this)
     -- bounds how many threads may MUTATE the shared workspace at
     once (always 1; read-only tools -- list_tree/search_code/
     read_file -- are NOT locked, so research genuinely overlaps).
     This module never touches the filesystem itself and does not
     duplicate that lock -- it only schedules which units of work run
     when.
"""

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


class RateLimiter:
    """Context manager: bounds concurrent AND per-second calls to
    whatever it wraps (here, always the LLM `generate` call) across
    every worker thread sharing one CodingAgent instance."""

    def __init__(self, max_concurrent: int = 2, min_interval_seconds: float = 0.8):
        self._sem = threading.Semaphore(max(1, int(max_concurrent)))
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._lock = threading.Lock()
        self._last_call_at = 0.0

    def __enter__(self) -> "RateLimiter":
        self._sem.acquire()
        with self._lock:
            wait = self._last_call_at + self._min_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last_call_at = time.time()
        return self

    def __exit__(self, *exc: Any) -> bool:
        self._sem.release()
        return False


@dataclass
class WorkerUnit:
    id: str
    fn: Callable[[], Any]
    dependencies: List[str] = field(default_factory=list)
    timeout: float = 90.0
    max_retries: int = 1


@dataclass
class WorkerResult:
    id: str
    ok: bool
    value: Any = None
    error: str = ""
    attempts: int = 0
    duration_s: float = 0.0


class WorkerPool:
    """Dependency-aware, bounded scheduler.

    Runs units in topological BATCHES: every unit whose dependencies
    have all already SUCCEEDED becomes eligible; up to `max_workers`
    eligible units run concurrently; the pool waits for that whole
    batch before computing the next one. Never more than max_workers
    in flight at once -- that IS the backpressure, by construction,
    not a separate queue-depth setting.

    A unit whose dependency FAILED is recorded as skipped, not run.
    A genuine cycle (nothing ready, work still remaining) fails every
    remaining unit explicitly instead of hanging forever.

    TIMEOUT CAVEAT, stated honestly rather than implied: Python cannot
    forcibly kill a running thread. `future.result(timeout=...)`
    stops WAITING and reports the unit as timed out/failed, but if the
    underlying call is still blocked (e.g. a hung network read) the
    thread itself keeps running in the background until it returns on
    its own. This bounds how long the POOL waits, not the thread's
    actual lifetime -- acceptable for JARVIS's bounded worker counts,
    but not a hard resource guarantee.
    """

    def __init__(self, max_workers: int = 3):
        self.max_workers = max(1, min(int(max_workers), 8))

    def run(self, units: List[WorkerUnit]) -> Dict[str, WorkerResult]:
        by_id = {u.id: u for u in units}
        if len(by_id) != len(units):
            raise ValueError("WorkerUnit ids must be unique")
        for u in units:
            for dep in u.dependencies:
                if dep not in by_id:
                    raise ValueError(f"unit '{u.id}' depends on unknown unit '{dep}'")

        results: Dict[str, WorkerResult] = {}
        remaining = dict(by_id)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while remaining:
                ready = [u for u in remaining.values()
                         if all(dep in results and results[dep].ok for dep in u.dependencies)]
                blocked = [u for u in remaining.values()
                           if u not in ready and
                           any(dep in results and not results[dep].ok for dep in u.dependencies)]
                for u in blocked:
                    results[u.id] = WorkerResult(id=u.id, ok=False,
                                                  error="a dependency failed -- skipped")
                    del remaining[u.id]

                if not ready:
                    if remaining:
                        for u in remaining.values():
                            results[u.id] = WorkerResult(id=u.id, ok=False,
                                                          error="unresolvable dependency (cycle?)")
                    break

                futures: Dict[Future, WorkerUnit] = {
                    executor.submit(self._run_with_retry, u): u for u in ready
                }
                for future, unit in futures.items():
                    try:
                        results[unit.id] = future.result(timeout=unit.timeout + 5)
                    except Exception as exc:
                        results[unit.id] = WorkerResult(id=unit.id, ok=False, error=str(exc))
                    del remaining[unit.id]
        return results

    @staticmethod
    def _run_with_retry(unit: WorkerUnit) -> WorkerResult:
        last_error = ""
        for attempt in range(1, unit.max_retries + 2):
            started = time.time()
            try:
                value = unit.fn()
                return WorkerResult(id=unit.id, ok=True, value=value, attempts=attempt,
                                     duration_s=time.time() - started)
            except Exception as exc:
                last_error = str(exc)
                time.sleep(min(2 ** attempt * 0.2, 3.0))   # bounded exponential backoff
        return WorkerResult(id=unit.id, ok=False, error=last_error, attempts=unit.max_retries + 1)
