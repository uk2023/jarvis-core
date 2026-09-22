from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Dict, Optional

try:
    from ..runtime.log import log_event
except ImportError:  # pragma: no cover - defensive, keeps this module standalone-importable
    def log_event(tag: str, message: str, level: str = "info") -> None:
        pass


class AsyncLearningQueue:
    """
    Ordered, single-worker background queue for the learning pipeline.

    ----------------------------------------------------------------
    WHY THIS EXISTS
    ----------------------------------------------------------------
    Architecture decision (final recommendation from blueprint review):

        Response synchronous, learning asynchronous + ordered queue,
        retrieval DB refreshed at the start of EVERY new prompt.

    Before this module existed, Brain.think_and_respond() called
    process_experience() (Experience -> Learning -> Evaluate ->
    KnowledgeBuilder -> DB) inline, in the same call that produced
    the chat reply. That meant every single message paid the full
    cost of the learning pipeline before the user ever saw a reply
    -- exactly the latency trap flagged in the architecture review.

    This queue fixes that without weakening consistency:

      - FIFO order: experiences are learned in the exact order the
        user produced them, even if learning falls behind chat.
      - Never blocks think_and_respond(): the user gets the reply
        the moment the LLM returns it.
      - A single worker thread means SQLite/FAISS never see two
        learning cycles writing at once, so "DB consistency ke liye
        learning queue/transaction" holds even when the next prompt
        arrives before the previous one finished learning.
      - Bounded size with oldest-drop-on-overflow, so a burst of
        rapid-fire prompts degrades gracefully instead of unbounded
        memory growth.
    """

    def __init__(self, worker: Callable[[Dict[str, Any]], Any], max_queue: int = 200):
        self._worker = worker
        self._q: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(maxsize=max_queue)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.processed = 0
        self.failed = 0
        self.dropped = 0
        self.last_error: Optional[str] = None

    # =============================================================
    # LIFECYCLE
    # =============================================================

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="JARVIS-LearningQueue", daemon=True
        )
        self._thread.start()

    def stop(self, drain: bool = True, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        if drain:
            try:
                self._q.join()
            except Exception:
                pass
        self._stop.set()
        try:
            self._q.put_nowait(None)  # unblock a pending get()
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # =============================================================
    # SUBMIT
    # =============================================================

    def submit(self, job: Dict[str, Any]) -> bool:
        """
        Enqueue one learning job. Never raises -- worst case it drops
        the oldest queued job to make room, since staying responsive
        matters more than never losing a single background fact.
        """
        try:
            self._q.put_nowait(job)
            return True
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.task_done()
                self.dropped += 1
                self._q.put_nowait(job)
                return True
            except Exception as exc:
                self.last_error = f"submit failed: {exc}"
                return False

    # =============================================================
    # WORKER LOOP
    # =============================================================

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._q.get()
            if job is None:
                self._q.task_done()
                break
            try:
                self._worker(job)
                self.processed += 1
            except Exception as exc:
                self.failed += 1
                self.last_error = str(exc)
                log_event("learning_queue", f"background job failed: {exc}", level="error")
            finally:
                self._q.task_done()

    # =============================================================
    # STATUS
    # =============================================================

    def status(self) -> Dict[str, Any]:
        return {
            "alive": self.is_alive(),
            "pending": self._q.qsize(),
            "processed": self.processed,
            "failed": self.failed,
            "dropped": self.dropped,
            "last_error": self.last_error,
        }
