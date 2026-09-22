from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional


class Heartbeat:
    """
    Biological-style heartbeat for the JARVIS organism.

    Responsibilities:
        - Keep a periodic organism pulse.
        - Emit HEARTBEAT events through EventBus.
        - Detect prolonged inactivity.
        - Emit IDLE_ENTER / IDLE_EXIT events.
        - Provide runtime health information.
        - Never contain cognition or LLM logic.

    Heartbeat is infrastructure, not intelligence.
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        event_bus=None,
        internal_state=None,
        interval: float = 5.0,
        idle_threshold: float = 30.0,
    ):
        self.events = event_bus
        self.state = internal_state

        self.interval = max(0.5, float(interval))
        self.idle_threshold = max(
            self.interval,
            float(idle_threshold),
        )

        # ---------------------------------------------------------
        # Runtime
        # ---------------------------------------------------------
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # ---------------------------------------------------------
        # Heartbeat statistics
        # ---------------------------------------------------------
        self.beat_count = 0
        self.started_at: Optional[float] = None
        self.last_beat_at: Optional[float] = None

        # ---------------------------------------------------------
        # Idle tracking
        # ---------------------------------------------------------
        self.is_idle = False
        self.idle_since: Optional[float] = None

        # ---------------------------------------------------------
        # Lock
        # ---------------------------------------------------------
        self._lock = threading.RLock()

    # =============================================================
    # START
    # =============================================================

    def start(self) -> None:
        """
        Start heartbeat thread.

        Calling start multiple times is safe.
        """

        with self._lock:

            if self.running:
                return

            self.running = True
            self.started_at = time.time()
            self.last_beat_at = None
            self._stop_event.clear()

            self._thread = threading.Thread(
                target=self._run,
                name="JARVIS-Heartbeat",
                daemon=True,
            )

            self._thread.start()

        self._emit(
            "HEARTBEAT_STARTED",
            {
                "interval": self.interval,
                "idle_threshold": self.idle_threshold,
            },
        )

    # =============================================================
    # STOP
    # =============================================================

    def stop(self) -> None:
        """
        Stop heartbeat safely.
        """

        with self._lock:

            if not self.running:
                return

            self.running = False
            self._stop_event.set()

            thread = self._thread

        # Never join the current heartbeat thread.
        if (
            thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=max(1.0, self.interval + 1.0))

        with self._lock:
            self._thread = None

        self._emit(
            "HEARTBEAT_STOPPED",
            {
                "beat_count": self.beat_count,
            },
        )

    # =============================================================
    # MAIN LOOP
    # =============================================================

    def _run(self) -> None:
        """
        Internal heartbeat loop.
        """

        while not self._stop_event.wait(self.interval):

            if not self.running:
                break

            try:
                self.beat()

            except Exception as exc:

                # Heartbeat must never kill itself because of
                # an unexpected monitoring error.
                self._emit(
                    "HEARTBEAT_ERROR",
                    {
                        "error": str(exc),
                    },
                )

    # =============================================================
    # SINGLE BEAT
    # =============================================================

    def beat(self) -> Dict[str, Any]:
        """
        Execute one heartbeat pulse.

        This method is also useful for tests where a real thread
        is not desirable.
        """

        now = time.time()

        with self._lock:

            self.beat_count += 1
            self.last_beat_at = now

        idle = self._check_idle(now)

        payload = {
            "beat": self.beat_count,
            "timestamp": now,
            "idle": idle,
            "running": self.running,
        }

        self._emit(
            "HEARTBEAT",
            payload,
        )

        return payload

    # =============================================================
    # IDLE DETECTION
    # =============================================================

    def _check_idle(self, now: float) -> bool:
        """
        Determine whether the organism has become idle.
        """

        if self.state is None:
            return False

        last_activity = getattr(
            self.state,
            "last_activity_at",
            None,
        )

        if last_activity is None:
            return False

        inactive_for = max(
            0.0,
            now - float(last_activity),
        )

        should_be_idle = (
            inactive_for >= self.idle_threshold
        )

        # ---------------------------------------------------------
        # Enter idle state
        # ---------------------------------------------------------
        if should_be_idle and not self.is_idle:

            self.is_idle = True
            self.idle_since = now

            self._emit(
                "IDLE_ENTER",
                {
                    "timestamp": now,
                    "inactive_for": inactive_for,
                },
            )

            return True

        # ---------------------------------------------------------
        # Exit idle state
        # ---------------------------------------------------------
        if not should_be_idle and self.is_idle:

            previous_idle_since = self.idle_since

            self.is_idle = False
            self.idle_since = None

            idle_duration = 0.0

            if previous_idle_since is not None:
                idle_duration = max(
                    0.0,
                    now - previous_idle_since,
                )

            self._emit(
                "IDLE_EXIT",
                {
                    "timestamp": now,
                    "idle_duration": idle_duration,
                },
            )

        return self.is_idle

    # =============================================================
    # EVENT EMISSION
    # =============================================================

    def _emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:
        """
        Safely communicate with EventBus.
        """

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
                source="heartbeat",
            )

    # =============================================================
    # STATUS
    # =============================================================

    def status(self) -> Dict[str, Any]:
        """
        Return heartbeat health information.
        """

        now = time.time()

        with self._lock:

            uptime = 0.0

            if self.started_at is not None:
                uptime = max(
                    0.0,
                    now - self.started_at,
                )

            return {
                "version": self.VERSION,
                "running": self.running,
                "interval": self.interval,
                "idle_threshold": self.idle_threshold,
                "beat_count": self.beat_count,
                "started_at": self.started_at,
                "last_beat_at": self.last_beat_at,
                "uptime": uptime,
                "is_idle": self.is_idle,
                "idle_since": self.idle_since,
            }

    # =============================================================
    # SNAPSHOT
    # =============================================================

    def snapshot(self) -> Dict[str, Any]:
        """
        Serializable heartbeat state.
        """

        return self.status()