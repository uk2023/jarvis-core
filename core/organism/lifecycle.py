from __future__ import annotations

import time
import threading
from typing import Any, Dict, Optional

from ..runtime.log import log_event


class Lifecycle:
    """
    Lifecycle manager of the JARVIS organism.

    Responsibilities:
        BOOT
          ↓
        STARTING
          ↓
        RUNNING
          ↓
        STOPPING
          ↓
        STOPPED

    Also provides a basic recovery path.

    IMPORTANT:
        Lifecycle controls the organism.
        It does not perform cognition, reasoning, memory or learning.
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        jarvis=None,
        internal_state=None,
        event_bus=None,
        heartbeat=None,
    ):
        self.jarvis = jarvis
        self.state = internal_state
        self.events = event_bus
        self.heartbeat = heartbeat

        self._lock = threading.RLock()

        self.status = "BOOT"
        self.started_at: Optional[float] = None
        self.stopped_at: Optional[float] = None

        self.start_count = 0
        self.stop_count = 0
        self.recovery_count = 0

    # =============================================================
    # START
    # =============================================================

    def start(self) -> bool:
        """
        Start the complete organism lifecycle.

        Safe to call multiple times.
        """

        with self._lock:

            if self.status == "RUNNING":
                return True

            self.status = "STARTING"

        self._update_state(
            mode="STARTING",
            running=False,
        )

        self._emit(
            "LIFECYCLE_STARTING",
            {
                "timestamp": time.time(),
            },
        )

        try:

            # -----------------------------------------------------
            # EventBus
            # -----------------------------------------------------

            if self.events is not None:

                start_method = getattr(
                    self.events,
                    "start",
                    None,
                )

                if callable(start_method):
                    start_method()

            # -----------------------------------------------------
            # Heartbeat
            # -----------------------------------------------------

            if self.heartbeat is not None:

                heartbeat_start = getattr(
                    self.heartbeat,
                    "start",
                    None,
                )

                if callable(heartbeat_start):
                    heartbeat_start()

            # -----------------------------------------------------
            # Core state
            # -----------------------------------------------------

            self._update_state(
                mode="ACTIVE",
                running=True,
            )

            with self._lock:

                self.status = "RUNNING"
                self.started_at = time.time()
                self.stopped_at = None
                self.start_count += 1

            self._emit(
                "LIFECYCLE_STARTED",
                {
                    "timestamp": time.time(),
                    "start_count": self.start_count,
                },
            )

            return True

        except Exception as exc:

            self._update_state(
                mode="ERROR",
                running=False,
            )

            with self._lock:
                self.status = "ERROR"

            self._emit(
                "LIFECYCLE_START_ERROR",
                {
                    "error": str(exc),
                    "timestamp": time.time(),
                },
            )

            return False

    # =============================================================
    # STOP
    # =============================================================

    def stop(self) -> bool:
        """
        Safely stop the organism.

        Shutdown order:

            STOPPING
                ↓
            Heartbeat stops
                ↓
            Final lifecycle event
                ↓
            EventBus stops
                ↓
            STOPPED
        """

        with self._lock:

            if self.status == "STOPPED":
                return True

            if self.status == "STOPPING":
                return False

            self.status = "STOPPING"

        self._update_state(
            mode="STOPPING",
            running=False,
        )

        self._emit(
            "LIFECYCLE_STOPPING",
            {
                "timestamp": time.time(),
            },
        )

        try:

            # -----------------------------------------------------
            # 1. Stop heartbeat first.
            #
            # No new heartbeat/autonomous pulses should be
            # generated while shutdown is in progress.
            # -----------------------------------------------------

            if self.heartbeat is not None:

                heartbeat_stop = getattr(
                    self.heartbeat,
                    "stop",
                    None,
                )

                if callable(heartbeat_stop):
                    heartbeat_stop()

            # -----------------------------------------------------
            # 2. Update lifecycle bookkeeping BEFORE final event.
            # -----------------------------------------------------

            with self._lock:

                self.stopped_at = time.time()
                self.stop_count += 1

                stop_count = self.stop_count
                stopped_at = self.stopped_at

            # -----------------------------------------------------
            # 3. Final lifecycle event.
            #
            # EventBus MUST still be running here.
            # -----------------------------------------------------

            self._emit(
                "LIFECYCLE_STOPPED",
                {
                    "timestamp": stopped_at,
                    "stop_count": stop_count,
                },
            )

            # -----------------------------------------------------
            # 4. Now stop EventBus.
            #
            # No lifecycle event is emitted after this point.
            # -----------------------------------------------------

            if self.events is not None:

                event_stop = getattr(
                    self.events,
                    "stop",
                    None,
                )

                if callable(event_stop):
                    event_stop()

            # -----------------------------------------------------
            # 5. Final internal state.
            # -----------------------------------------------------

            self._update_state(
                mode="STOPPED",
                running=False,
            )

            with self._lock:
                self.status = "STOPPED"

            return True

        except Exception as exc:

            with self._lock:
                self.status = "ERROR"

            self._update_state(
                mode="ERROR",
                running=False,
            )

            # EventBus may still be available. safe_emit()
            # protects us if it has already stopped.

            self._emit(
                "LIFECYCLE_STOP_ERROR",
                {
                    "error": str(exc),
                    "timestamp": time.time(),
                },
            )

            return False

    # =============================================================
    # RESTART
    # =============================================================

    def restart(self) -> bool:
        """
        Restart the organism cleanly.
        """

        self._emit(
            "LIFECYCLE_RESTARTING",
            {
                "timestamp": time.time(),
            },
        )

        self.stop()

        # Give background components a moment to settle.
        time.sleep(0.05)

        return self.start()

    # =============================================================
    # RECOVERY
    # =============================================================

    def recover(self, reason: str = "UNKNOWN") -> bool:
        """
        Attempt to recover the organism from an ERROR state.

        Recovery currently performs a clean restart.

        Later this can become much smarter:
            - identify failed organ
            - restart only failed organ
            - restore persisted state
            - rebuild corrupted component
        """

        with self._lock:
            self.recovery_count += 1

            recovery_number = self.recovery_count

        self._emit(
            "LIFECYCLE_RECOVERY_STARTED",
            {
                "reason": reason,
                "recovery_count": recovery_number,
                "timestamp": time.time(),
            },
        )

        success = self.restart()

        self._emit(
            "LIFECYCLE_RECOVERY_COMPLETED",
            {
                "success": success,
                "recovery_count": recovery_number,
                "timestamp": time.time(),
            },
        )

        return success

    # =============================================================
    # STATE UPDATE
    # =============================================================

    def _update_state(self, **changes) -> None:
        """
        Safely update InternalState.
        """

        if self.state is None:
            return

        update = getattr(
            self.state,
            "update",
            None,
        )

        if callable(update):

            try:
                update(**changes)

            except Exception as exc:

                log_event("lifecycle", f"state update failed: {exc}", level="error")

    # =============================================================
    # EVENT
    # =============================================================

    def _emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:
        """
        Safely emit lifecycle events.
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
                source="lifecycle",
            )

    # =============================================================
    # IS RUNNING
    # =============================================================

    def is_running(self) -> bool:
        with self._lock:
            return self.status == "RUNNING"

    # =============================================================
    # SNAPSHOT
    # =============================================================

    def snapshot(self) -> Dict[str, Any]:
        """
        Return serializable lifecycle information.
        """

        with self._lock:

            uptime = 0.0

            if self.started_at is not None:

                end_time = (
                    self.stopped_at
                    if self.stopped_at is not None
                    else time.time()
                )

                uptime = max(
                    0.0,
                    end_time - self.started_at,
                )

            return {
                "version": self.VERSION,
                "status": self.status,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "uptime": uptime,
                "start_count": self.start_count,
                "stop_count": self.stop_count,
                "recovery_count": self.recovery_count,
            }

    # =============================================================
    # DESCRIBE
    # =============================================================

    def describe(self) -> Dict[str, Any]:
        """
        Human-readable lifecycle information.
        """

        return {
            "component": "Lifecycle",
            "version": self.VERSION,
            "status": self.status,
            "running": self.is_running(),
            "heartbeat_connected": self.heartbeat is not None,
            "event_bus_connected": self.events is not None,
            "state_connected": self.state is not None,
            "jarvis_connected": self.jarvis is not None,
        }