from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..runtime.log import log_event


@dataclass
class OrganismEvent:
    """
    A single event inside the JARVIS organism.

    Events are the communication mechanism between organs.
    """

    name: str
    payload: Any = None
    source: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    event_id: int = 0


class EventBus:
    """
    Internal nervous system of the JARVIS organism.

    Organs should communicate through events rather than directly
    depending on one another.

    Example:

        bus.subscribe("USER_INPUT", brain.handle_input)

        bus.emit(
            "USER_INPUT",
            {"text": "Hello Jarvis"},
            source="conversation"
        )

    This keeps the organism modular and allows new organs to be
    added without rewriting existing organs.
    """

    VERSION = "0.1.0"

    def __init__(self, internal_state=None):
        self.internal_state = internal_state

        self._subscribers: Dict[
            str,
            List[Callable[[OrganismEvent], Any]]
        ] = {}

        self._event_counter = 0

        self._lock = threading.RLock()

        self._history: List[OrganismEvent] = []

        # Prevent unlimited memory growth.
        self.max_history = 500

        self.running = True

    # =============================================================
    # SUBSCRIBE
    # =============================================================

    def subscribe(
        self,
        event_name: str,
        callback: Callable[[OrganismEvent], Any],
    ) -> None:
        """
        Register an organ/function for an event.
        """

        if not event_name:
            raise ValueError("event_name cannot be empty")

        if not callable(callback):
            raise TypeError("callback must be callable")

        event_name = str(event_name).upper().strip()

        with self._lock:

            subscribers = self._subscribers.setdefault(
                event_name,
                []
            )

            if callback not in subscribers:
                subscribers.append(callback)

    # =============================================================
    # UNSUBSCRIBE
    # =============================================================

    def unsubscribe(
        self,
        event_name: str,
        callback: Callable[[OrganismEvent], Any],
    ) -> bool:
        """
        Remove a previously registered listener.

        Returns True if removed.
        """

        event_name = str(event_name).upper().strip()

        with self._lock:

            subscribers = self._subscribers.get(
                event_name,
                []
            )

            if callback in subscribers:

                subscribers.remove(callback)

                if not subscribers:
                    self._subscribers.pop(
                        event_name,
                        None
                    )

                return True

        return False

    # =============================================================
    # EMIT
    # =============================================================

    def emit(
        self,
        event_name: str,
        payload: Any = None,
        source: Optional[str] = None,
    ) -> OrganismEvent:
        """
        Create and distribute an event.
        """

        if not self.running:
            raise RuntimeError("EventBus is stopped")

        event_name = str(event_name).upper().strip()

        with self._lock:

            self._event_counter += 1

            event = OrganismEvent(
                name=event_name,
                payload=payload,
                source=source,
                event_id=self._event_counter,
            )

            self._history.append(event)

            if len(self._history) > self.max_history:
                self._history = self._history[
                    -self.max_history:
                ]

            subscribers = list(
                self._subscribers.get(
                    event_name,
                    []
                )
            )

            # Wildcard subscribers receive every event.
            subscribers += list(
                self._subscribers.get(
                    "*",
                    []
                )
            )

        # Update organism state before notifying organs.
        if self.internal_state is not None:

            try:
                self.internal_state.record_event(
                    event_name=event.name,
                    payload=event.payload,
                    source=event.source,
                )

            except Exception as exc:

                log_event("event_bus", f"internal state update failed: {exc}", level="error")

        # Notify outside the lock.
        for callback in subscribers:

            try:
                callback(event)

            except Exception as exc:

                log_event("event_bus", f"subscriber error on {event.name}: {exc}\n{traceback.format_exc()}", level="error")

        return event

    # =============================================================
    # SAFE EMIT
    # =============================================================

    def safe_emit(
        self,
        event_name: str,
        payload: Any = None,
        source: Optional[str] = None,
    ) -> Optional[OrganismEvent]:
        """
        Emit without allowing an event failure to crash JARVIS.
        """

        try:

            return self.emit(
                event_name,
                payload,
                source,
            )

        except Exception as exc:

            log_event("event_bus", f"emit error on {event_name}: {exc}", level="error")

            return None

    # =============================================================
    # WAIT-FREE EVENT QUERY
    # =============================================================

    def get_history(
        self,
        event_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[OrganismEvent]:
        """
        Return recent events.

        This is useful for cognition, debugging and later
        experience formation.
        """

        if limit <= 0:
            return []

        with self._lock:

            history = list(self._history)

        if event_name:

            event_name = str(
                event_name
            ).upper().strip()

            history = [
                event
                for event in history
                if event.name == event_name
            ]

        return history[-limit:]

    # =============================================================
    # INSPECTION
    # =============================================================

    def get_subscribers(
        self,
        event_name: Optional[str] = None,
    ) -> Dict[str, int]:

        with self._lock:

            if event_name:

                event_name = str(
                    event_name
                ).upper().strip()

                return {
                    event_name: len(
                        self._subscribers.get(
                            event_name,
                            []
                        )
                    )
                }

            return {
                name: len(callbacks)
                for name, callbacks
                in self._subscribers.items()
            }

    # =============================================================
    # EVENT COUNT
    # =============================================================

    @property
    def event_count(self) -> int:
        return self._event_counter

    # =============================================================
    # CLEAR HISTORY
    # =============================================================

    def clear_history(self) -> None:

        with self._lock:
            self._history.clear()

    # =============================================================
    # STOP
    # =============================================================

    def stop(self) -> None:

        self.running = False

    # =============================================================
    # START
    # =============================================================

    def start(self) -> None:

        self.running = True

    # =============================================================
    # SNAPSHOT
    # =============================================================

    def snapshot(self) -> Dict[str, Any]:

        with self._lock:

            return {
                "version": self.VERSION,
                "running": self.running,
                "event_count": self._event_counter,
                "subscriber_count": sum(
                    len(callbacks)
                    for callbacks
                    in self._subscribers.values()
                ),
                "history_size": len(self._history),
            }