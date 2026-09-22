from __future__ import annotations

import heapq
import itertools
import time
from typing import Any, Dict, List, Optional


class Scheduler:
    """
    Lightweight in-process priority queue for background/idle tasks.

    Deliberately simple and dependency-free so it runs the same on a
    desktop process or inside an Android background service:
      - No threads are spawned here.
      - No task executes itself; `due_tasks()` just tells the caller
        (IdleLoop / heartbeat) what is ready to run *now*.
      - Callers remain responsible for actually executing tasks and
        for any sandboxing/confirmation logic.
    """

    def __init__(self):
        self._heap: List[tuple] = []
        self._counter = itertools.count()
        self._cancelled: set = set()

    def schedule(
        self,
        task: Dict[str, Any],
        run_at: Optional[float] = None,
        priority: float = 0.5,
    ) -> str:
        """Queue a task. Returns a schedule id usable for cancellation."""

        if run_at is None:
            run_at = time.time()

        schedule_id = f"sched-{next(self._counter)}"

        entry = {
            **task,
            "schedule_id": schedule_id,
            "run_at": run_at,
            "priority": priority,
            "queued_at": time.time(),
        }

        # Min-heap ordered by (run_at, -priority) so earlier/more
        # important tasks surface first.
        heapq.heappush(self._heap, (run_at, -priority, schedule_id, entry))

        return schedule_id

    def cancel(self, schedule_id: str) -> None:
        self._cancelled.add(schedule_id)

    def due_tasks(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Pop and return every task whose run_at has passed."""

        now = now if now is not None else time.time()
        ready = []

        while self._heap and self._heap[0][0] <= now:
            run_at, neg_priority, schedule_id, entry = heapq.heappop(self._heap)

            if schedule_id in self._cancelled:
                self._cancelled.discard(schedule_id)
                continue

            ready.append(entry)

        return ready

    def pending_count(self) -> int:
        return len(self._heap)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "pending": self.pending_count(),
            "next_run_at": self._heap[0][0] if self._heap else None,
        }
