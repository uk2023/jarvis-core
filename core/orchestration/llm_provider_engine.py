from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Groq's documented per-key rate limit (Bug 1, UK's spec, 2026-09-17):
# 30 requests per minute per key. Enforced as a sliding window in
# KeyUsage.available()/seconds_until_rpm_slot() below.
GROQ_RPM_LIMIT = 30

# MINIMUM GAP BETWEEN USES OF THE SAME KEY (2026-09-17, UK's exact
# spec: "key ka 2 sec sleep and thenafter use"). The 30-RPM sliding
# window alone allows a key to be re-selected again the instant it
# drops under 30 calls in the last 60s -- nothing stops several calls
# from landing on the SAME key within the same second under bursty
# concurrent load (parallel subtasks, a fast retry loop), which is
# exactly the shape of UK's monitor.py trace: several keys accumulating
# fail=6-9 with repeated HTTP 429s. A flat per-key reuse floor closes
# that gap regardless of the 60s window's state.
MIN_KEY_REUSE_INTERVAL_SECONDS = 2.0

# Upper bound on how long a caller will block waiting for an RPM-limited
# key to free up (Bug 1 #6 / Bug 2 #6: controlled waiting, not an
# unbounded hang). Past this, fail with an honest rate-limit message
# instead of freezing the request.
_MAX_CONTROLLED_WAIT_SECONDS = 5.0

try:
    import requests
except ImportError:
    requests = None

try:
    from ..runtime.log import log_event
except ImportError:
    def log_event(tag: str, message: str, level: str = "info") -> None:
        pass


# ============================================================
# ENV HELPERS
# ============================================================

def _csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [x.strip() for x in value.replace(" ", "").split(",") if x.strip()]


def _env_csv(*names: str) -> List[str]:
    """Read the first configured comma-separated environment variable."""
    for name in names:
        values = _csv(os.getenv(name))
        if values:
            return values
    return []


def _logical_model() -> str:
    return os.getenv("LLM_MODEL", "openai/gpt-oss-120b").strip()


def _provider_model(provider: str) -> str:
    """Map the logical model to the provider-native model identifier."""
    logical = _logical_model()
    explicit = os.getenv(f"{provider.upper()}_MODEL")
    if explicit:
        return explicit.strip()
    if logical in {"openai/gpt-oss-120b", "gpt-oss-120b"}:
        return {
            "groq": "openai/gpt-oss-120b",
        }.get(provider, logical)
    return os.getenv(f"{provider.upper()}_MODEL", logical).strip()


def _int_list(name: str, count: int, default: int) -> List[int]:
    raw = _csv(os.getenv(name))
    if not raw:
        return [default] * count

    values = []
    for item in raw:
        try:
            values.append(max(1, int(item)))
        except ValueError:
            values.append(default)

    if len(values) == 1:
        return values * count

    while len(values) < count:
        values.append(values[-1])

    return values[:count]


def _retry_after(headers: Dict[str, Any]) -> float:
    value = headers.get("retry-after")
    if value is None:
        return 5.0

    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return 5.0


def _reset_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip().lower()

    try:
        return float(text)
    except ValueError:
        pass

    total = 0.0
    number = ""

    for char in text:
        if char.isdigit() or char == ".":
            number += char
            continue

        if not number:
            continue

        try:
            n = float(number)
        except ValueError:
            number = ""
            continue

        if char == "h":
            total += n * 3600
        elif char == "m":
            total += n * 60
        elif char == "s":
            total += n

        number = ""

    if number:
        try:
            total += float(number)
        except ValueError:
            pass

    return total if total > 0 else None


# ============================================================
# PER-KEY USAGE
# ============================================================

@dataclass
class KeyUsage:
    provider: str
    index: int
    capacity: int

    requests_used: int = 0
    requests_attempted: int = 0
    failures: int = 0

    window_started: float = field(default_factory=time.time)
    balance_reset_at: float = 0.0

    cooldown_until: float = 0.0

    # Groq live metadata only.
    live_limit_requests: Optional[int] = None
    live_remaining_requests: Optional[int] = None
    live_reset_at: Optional[float] = None

    status: str = "ESTIMATED"
    last_error: Optional[str] = None
    last_used_at: float = 0.0

    history: deque = field(
        default_factory=lambda: deque(maxlen=200)
    )

    alert_stage: int = 0

    def __post_init__(self) -> None:
        self.balance_reset_at = self.window_started + 86400

    def reset_window_if_needed(self, now: float) -> None:
        if now < self.balance_reset_at:
            return

        self.requests_used = 0
        self.requests_attempted = 0
        self.failures = 0
        self.history.clear()
        self.alert_stage = 0
        self.window_started = now
        self.balance_reset_at = now + 86400

    @property
    def utilization(self) -> float:
        # capacity <= 0 means quota is UNKNOWN, not exhausted.
        if self.capacity <= 0:
            return 0.0

        return min(
            1.0,
            self.requests_used / float(self.capacity)
        )

    @property
    def estimated_remaining(self) -> int:
        return max(
            0,
            self.capacity - self.requests_used
        )

    def available(self, now: float) -> bool:
        self.reset_window_if_needed(now)

        if now < self.cooldown_until:
            return False

        # PER-KEY REUSE FLOOR (2026-09-17, see MIN_KEY_REUSE_INTERVAL_SECONDS
        # above). Checked before the RPM window so it applies even when
        # the window has room -- a key just used seconds ago is not
        # "the least busy key" again a moment later just because the
        # count still looks low.
        if self.last_used_at and (now - self.last_used_at) < MIN_KEY_REUSE_INTERVAL_SECONDS:
            return False

        # 30 RPM SLIDING WINDOW (2026-09-17, UK's spec, Bug 1: "Every
        # Groq key has a 30 RPM limit... key must not be called
        # repeatedly in a fraction of a second when its RPM/cooldown
        # rules require waiting"). `history` already records every
        # request's timestamp (see record() below) -- nothing new to
        # track, just count how many landed in the trailing 60s. This
        # was previously UNCHECKED: rotation alone does not prevent one
        # key from being re-selected many times within a minute once
        # the pool cycles back around under heavy load.
        if len(self.history) >= GROQ_RPM_LIMIT:
            window_start = now - 60.0
            recent = sum(1 for t in self.history if t >= window_start)
            if recent >= GROQ_RPM_LIMIT:
                return False

        if self.capacity > 0 and self.requests_used >= self.capacity:
            return False

        if (
            self.live_remaining_requests is not None
            and self.live_remaining_requests <= 0
            and self.live_reset_at
            and now < self.live_reset_at
        ):
            return False

        return True

    def seconds_until_rpm_slot(self, now: float) -> float:
        """How long until this key drops under GROQ_RPM_LIMIT again --
        used to pick the SOONEST-available key when every key is
        currently RPM-limited, rather than failing outright (Bug 1
        requirement #6: controlled waiting, not uncontrolled failure).
        Also accounts for the flat per-key reuse floor."""
        reuse_wait = 0.0
        if self.last_used_at:
            reuse_wait = max(0.0, MIN_KEY_REUSE_INTERVAL_SECONDS - (now - self.last_used_at))
        window_start = now - 60.0
        recent = sorted(t for t in self.history if t >= window_start)
        if len(recent) < GROQ_RPM_LIMIT:
            return reuse_wait
        # The window has room again once the (len-RPM_LIMIT+1)-th oldest
        # request in the window ages past 60s.
        oldest_to_expire = recent[len(recent) - GROQ_RPM_LIMIT]
        rpm_wait = max(0.0, (oldest_to_expire + 60.0) - now)
        return max(reuse_wait, rpm_wait)

    def record(
        self,
        status_code: Optional[int],
        headers: Optional[Dict[str, Any]],
        success: bool,
        error: Optional[str] = None,
        parse_live_headers: bool = False,
    ) -> None:
        now = time.time()

        self.reset_window_if_needed(now)

        self.requests_attempted += 1
        self.requests_used += 1
        self.last_used_at = now
        self.history.append(now)

        if not success:
            self.failures += 1

        self.last_error = error

        if parse_live_headers and headers:
            limit = (headers.get("x-ratelimit-limit-requests")
                     or headers.get("ratelimit-limit")
                     or headers.get("x-ratelimit-limit"))
            remaining = (headers.get("x-ratelimit-remaining-requests")
                         or headers.get("ratelimit-remaining")
                         or headers.get("x-ratelimit-remaining"))
            reset = (headers.get("x-ratelimit-reset-requests")
                     or headers.get("ratelimit-reset")
                     or headers.get("x-ratelimit-reset"))

            try:
                if limit is not None:
                    self.live_limit_requests = int(limit)
                    # THE "used 16/0 -- 0.0%" BUG (fixed 2026-09-16).
                    # The provider's real limit was parsed and stored in
                    # live_limit_requests, and then never used for
                    # anything. capacity stayed at whatever it was
                    # configured to (0 = unknown), so utilization()
                    # short-circuited to 0.0 forever and monitor.py
                    # showed every key at 0.0% with "used N/0" -- UK's
                    # exact report, with live_rem=999 sitting right
                    # there in the same row proving the header HAD
                    # arrived.
                    #
                    # A confirmed limit from the provider is strictly
                    # better information than any configured guess, so
                    # it becomes the capacity. That is also what makes
                    # the balancer's per-key percentages real rather
                    # than estimated.
                    if self.live_limit_requests > 0:
                        self.capacity = self.live_limit_requests
                        self.status = "CONFIRMED"
            except (TypeError, ValueError):
                pass

            try:
                if remaining is not None:
                    self.live_remaining_requests = int(remaining)
                    # If the provider tells us the limit only via
                    # remaining + used, derive the capacity from those
                    # rather than leaving it unknown.
                    if self.capacity <= 0 and self.requests_used >= 0:
                        derived = self.live_remaining_requests + self.requests_used
                        if derived > 0:
                            self.capacity = derived
                            self.status = "CONFIRMED"
            except (TypeError, ValueError):
                pass

            reset_value = _reset_seconds(reset)

            if reset_value is not None:
                self.live_reset_at = now + reset_value

            if (
                self.live_remaining_requests is not None
                and self.live_remaining_requests <= 0
                and self.live_reset_at
            ):
                self.cooldown_until = max(
                    self.cooldown_until,
                    self.live_reset_at
                )

            self.status = "CONFIRMED"

        if status_code == 429:
            self.cooldown_until = max(
                self.cooldown_until,
                now + _retry_after(headers or {})
            )

        elif status_code in (401, 403):
            self.cooldown_until = max(
                self.cooldown_until,
                now + 60.0
            )

        elif status_code and status_code >= 500:
            self.cooldown_until = max(
                self.cooldown_until,
                now + 3.0
            )

    def request_rate(self) -> float:
        if len(self.history) < 2:
            return 0.0

        now = time.time()

        recent = [
            timestamp
            for timestamp in self.history
            if now - timestamp <= 900
        ]

        if len(recent) < 2:
            return 0.0

        elapsed = max(
            1.0,
            recent[-1] - recent[0]
        )

        return (len(recent) - 1) / elapsed

    def exhaustion_forecast(self) -> Optional[float]:
        # No provider quota is known: never invent an exhaustion time.
        if self.capacity <= 0:
            return None

        remaining = self.estimated_remaining

        if remaining <= 0:
            return time.time()

        rate = self.request_rate()

        if rate <= 0:
            return None

        seconds = remaining / rate
        forecast = time.time() + seconds

        if self.balance_reset_at:
            forecast = min(
                forecast,
                self.balance_reset_at
            )

        return forecast


# ============================================================
# PROVIDER QUOTA MANAGER
# ============================================================

class ProviderQuotaManager:

    def __init__(self) -> None:
        self.providers: Dict[str, List[KeyUsage]] = {}
        self.last_provider: str = "idle"
        self.last_key_index: Optional[int] = None
        self.model: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
        self._state_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "runtime",
            "llm_quota_state.json",
        )

        self.alert_threshold = float(
            os.getenv(
                "JARVIS_PROVIDER_ALERT_THRESHOLD",
                "0.80"
            )
        )

    def register(
        self,
        provider: str,
        key_count: int,
        capacities: List[int],
    ) -> None:

        self.providers[provider] = [
            KeyUsage(
                provider=provider,
                index=index,
                capacity=capacities[index],
            )
            for index in range(key_count)
        ]
        self._load_persisted_provider(provider)

    def keys(self, provider: str) -> List[KeyUsage]:
        return self.providers.get(provider, [])

    def provider_utilization(self, provider: str) -> float:
        keys = self.keys(provider)

        if not keys:
            return 1.0

        now = time.time()

        total_capacity = 0
        total_used = 0

        for key in keys:
            key.reset_window_if_needed(now)

            total_capacity += key.capacity
            total_used += key.requests_used

        if total_capacity <= 0:
            return 0.0

        return min(
            1.0,
            total_used / float(total_capacity)
        )

    def provider_available(self, provider: str) -> bool:
        now = time.time()

        return any(
            key.available(now)
            for key in self.keys(provider)
        )

    def provider_order(
        self,
        providers: List[str],
        excluded: Optional[set] = None,
    ) -> List[str]:

        excluded = excluded or set()

        candidates = [
            provider
            for provider in providers
            if provider not in excluded
            and self.provider_available(provider)
        ]

        candidates.sort(
            key=lambda provider: (
                self.provider_utilization(provider),
                min(
                    (
                        key.last_used_at
                        for key in self.keys(provider)
                    ),
                    default=0.0,
                ),
            )
        )

        return candidates

    def key_order(self, provider: str) -> List[KeyUsage]:

        keys = [
            key
            for key in self.keys(provider)
            if key.available(time.time())
        ]

        keys.sort(
            key=lambda key: (
                key.utilization,
                key.last_used_at,
                key.index,
            )
        )

        return keys

    def seconds_until_any_key(self, provider: str) -> Optional[float]:
        """Shortest wait, across every key of `provider`, until it clears
        its RPM window -- used for the controlled-wait fallback in
        LLMProviderEngine._generate_groq when key_order() returns empty.
        None if the provider has no registered keys at all."""
        now = time.time()
        keys = self.keys(provider)
        if not keys:
            return None
        return min(k.seconds_until_rpm_slot(now) for k in keys)

    def record(
        self,
        provider: str,
        key_index: int,
        status_code: Optional[int],
        headers: Optional[Dict[str, Any]],
        success: bool,
        error: Optional[str] = None,
        confirmed: bool = False,
    ) -> None:

        keys = self.keys(provider)

        if key_index < 0 or key_index >= len(keys):
            return

        key = keys[key_index]
        self.last_provider = provider
        self.last_key_index = key_index

        key.record(
            status_code=status_code,
            headers=headers,
            success=success,
            error=error,
            parse_live_headers=confirmed,
        )

        utilization = key.utilization

        if utilization >= 0.90 and key.alert_stage < 2:
            log_event(
                "llm_quota",
                f"{provider} key #{key_index + 1} "
                f"usage {utilization * 100:.1f}%",
                level="warning",
            )
            key.alert_stage = 2

        elif (
            utilization >= self.alert_threshold
            and key.alert_stage < 1
        ):
            log_event(
                "llm_quota",
                f"{provider} key #{key_index + 1} "
                f"usage {utilization * 100:.1f}%",
                level="warning",
            )
            key.alert_stage = 1

        self._save_persisted_state()

    def _load_persisted_provider(self, provider: str) -> None:
        try:
            import json
            with open(self._state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            saved = (data.get("providers") or {}).get(provider) or []
            now = time.time()
            for item in saved:
                idx = int(item.get("key_index", 0)) - 1
                keys = self.keys(provider)
                if idx < 0 or idx >= len(keys):
                    continue
                key = keys[idx]
                if float(item.get("balance_reset_at", 0.0) or 0.0) <= now:
                    continue
                key.requests_used = int(item.get("requests_used", 0) or 0)
                key.requests_attempted = int(item.get("requests_attempted", 0) or 0)
                key.failures = int(item.get("failures", 0) or 0)
                key.balance_reset_at = float(item.get("balance_reset_at", key.balance_reset_at))
                key.window_started = float(item.get("window_started", key.window_started))
                key.last_used_at = float(item.get("last_used_at", 0.0) or 0.0)
                key.cooldown_until = float(item.get("cooldown_until", 0.0) or 0.0)
                key.live_limit_requests = item.get("live_limit_requests")
                key.live_remaining_requests = item.get("live_remaining_requests")
                key.live_reset_at = item.get("live_reset_at")
                key.status = str(item.get("status", key.status))

                # Never restore an old synthetic capacity as if it were
                # a real provider quota. Only live-confirmed quota may
                # establish capacity.
                if key.status != "CONFIRMED":
                    key.capacity = 0
        except (OSError, ValueError, TypeError, KeyError):
            return

    def _save_persisted_state(self) -> None:
        try:
            import json
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            payload = {"version": 1, "model": self.model, "updated_at": time.time(), "providers": {}}
            for provider, keys in self.providers.items():
                payload["providers"][provider] = [
                    {
                        "key_index": key.index + 1,
                        "requests_used": key.requests_used,
                        "requests_attempted": key.requests_attempted,
                        "failures": key.failures,
                        "capacity": key.capacity,
                        "window_started": key.window_started,
                        "balance_reset_at": key.balance_reset_at,
                        "last_used_at": key.last_used_at,
                        "cooldown_until": key.cooldown_until,
                        "live_limit_requests": key.live_limit_requests,
                        "live_remaining_requests": key.live_remaining_requests,
                        "live_reset_at": key.live_reset_at,
                        "status": key.status,
                    }
                    for key in keys
                ]
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            os.replace(tmp, self._state_path)
        except (OSError, TypeError, ValueError):
            pass

    def snapshot(self) -> Dict[str, Any]:

        result: Dict[str, Any] = {
            "providers": {}
        }

        for provider, keys in self.providers.items():

            now = time.time()
            for key in keys:
                key.reset_window_if_needed(now)

            used = sum(key.requests_used for key in keys)
            attempted = sum(key.requests_attempted for key in keys)
            capacity = sum(max(0, key.capacity) for key in keys)
            remaining = sum(key.estimated_remaining for key in keys)
            confirmed = any(key.status == "CONFIRMED" for key in keys)

            provider_data = {
                "model": self.model,
                "utilization_percent": round((used / capacity * 100.0) if capacity else 0.0, 2),
                "requests_used": used,
                "requests_attempted": attempted,
                "capacity_total": capacity,
                "remaining_estimated": remaining,
                "status": "CONFIRMED" if confirmed else ("ESTIMATED" if keys else "UNKNOWN"),
                "available": self.provider_available(provider),
                "key_count": len(keys),
                "keys": [],
            }

            for key in keys:

                forecast = key.exhaustion_forecast()

                provider_data["keys"].append({
                    "key_index": key.index + 1,
                    "requests_used": key.requests_used,
                    "requests_attempted": key.requests_attempted,
                    "capacity": key.capacity,
                    "estimated_remaining":
                        key.estimated_remaining,
                    "utilization_percent":
                        round(key.utilization * 100, 2),
                    "failures": key.failures,
                    "status": key.status,
                    "live_limit_requests":
                        key.live_limit_requests,
                    "live_remaining_requests":
                        key.live_remaining_requests,
                    "live_reset_at":
                        key.live_reset_at,
                    "balance_reset_at":
                        key.balance_reset_at,
                    "expected_exhaustion_at":
                        forecast,
                    "cooldown_until":
                        key.cooldown_until,
                    "last_error":
                        key.last_error,
                })

            result["providers"][provider] = provider_data

        all_keys = [key for keys in self.providers.values() for key in keys]
        overall_used = sum(key.requests_used for key in all_keys)
        overall_capacity = sum(max(0, key.capacity) for key in all_keys)
        result["model"] = self.model
        result["overall"] = {
            "requests_used": overall_used,
            "capacity_total": overall_capacity,
            "remaining_estimated": sum(key.estimated_remaining for key in all_keys),
            "utilization_percent": round((overall_used / overall_capacity * 100.0) if overall_capacity else 0.0, 2),
            "providers": len(self.providers),
            "keys": len(all_keys),
            "last_provider": self.last_provider,
            "last_key_index": self.last_key_index + 1 if self.last_key_index is not None else None,
        }

        return result


# ============================================================
# CENTRAL PROVIDER ROUTER
# ============================================================

class LLMProviderEngine:

    """
    Thin cloud-provider router.

    IMPORTANT:
    - Does NOT replace HybridLLMBridge.
    - Does NOT manage CognitiveBudgeter.
    - Does NOT manage turn budgets.
    - Does NOT touch local GGUF.
    - Does NOT handle tool calling.
    - Existing GroqEngine remains the authority for Groq.
    """

    def __init__(
        self,
        groq_engine: Optional[Any] = None,
    ) -> None:

        self.groq_engine = groq_engine

        self.quota = ProviderQuotaManager()

        self.last_provider = "idle"
        self.last_error: Optional[str] = None

        # GROQ-ONLY (2026-09-20, UK's explicit, repeated instruction:
        # "llm_provider_engine me bas grok engine rahe" -- this
        # supersedes the earlier 2026-09-16 "disable by default, keep
        # the code" compromise. CerebrasEngine/CloudflareEngine and
        # every code path that dispatched to them have been removed
        # from this file entirely, not just disabled -- there is no
        # self.cerebras/self.cloudflare, no _generate_cerebras/
        # _generate_cloudflare, and generate() below only ever
        # considers "groq". If cloud-provider fan-out is wanted again
        # later, it is a deliberate re-add, not a flag flip.
        if self.groq_engine is not None:
            groq_count = len(
                getattr(
                    self.groq_engine,
                    "api_keys",
                    [],
                )
            )

            if groq_count:
                capacities = _int_list(
                    "JARVIS_GROQ_BALANCE_CAPACITY",
                    groq_count,
                    0,
                )

                self.quota.register(
                    "groq",
                    groq_count,
                    capacities,
                )

    # --------------------------------------------------------
    # GROQ
    # --------------------------------------------------------

    def _generate_groq(
        self,
        system_prompt: str,
        user_input: str,
        max_tokens: int,
        temperature: float,
        response_format: Optional[Dict[str, Any]],
        reasoning_effort: Optional[str],
    ) -> str:

        if self.groq_engine is None:
            raise RuntimeError("Groq engine is not configured.")

        try:
            # REAL-CAPACITY-FIRST (2026-09-20, UK's explicit ask: "grok
            # provider engine will pass the most available remaining
            # token size capacity token to hybrid llm bridge"). GroqEngine
            # itself now tracks REAL per-key remaining-token telemetry
            # from actual response headers (see llm_bridge.py's
            # _capacity_ordered_key_indices / _record_key_telemetry,
            # 2026-09-20 pass) -- that is a strictly more accurate, more
            # current source than this file's own KeyUsage RPM-window
            # estimate, since it comes from Groq's OWN last real answer
            # about this exact key's capacity. Prefer it; fall back to
            # the RPM-window estimate below only when GroqEngine has no
            # telemetry yet for any key (e.g. process just started).
            real_order = []
            if hasattr(self.groq_engine, "_capacity_ordered_key_indices"):
                try:
                    real_order = self.groq_engine._capacity_ordered_key_indices(max_tokens)
                except Exception:
                    real_order = []
            has_real_telemetry = bool(getattr(self.groq_engine, "_key_telemetry", None))

            preferred = self.quota.key_order("groq")
            if not preferred:
                # ALL 10 keys are currently RPM-limited or cooling down
                # (Bug 1 #6 / Bug 2 #6, UK's spec: "controlled waiting/
                # queueing rather than an uncontrolled immediate
                # failure"). Wait for whichever key frees up SOONEST,
                # bounded so one stuck request can't hang a whole HTTP
                # request or freeze the CLI for a full minute -- past
                # the bound, fail with a clear, honest reason rather
                # than a silent long hang.
                wait = self.quota.seconds_until_any_key(provider="groq")
                if wait is None:
                    wait = 60.0
                if wait <= _MAX_CONTROLLED_WAIT_SECONDS:
                    log_event("llm_provider_engine",
                              f"all Groq keys at 30 RPM -- waiting {wait:.1f}s for the soonest slot",
                              level="info")
                    time.sleep(wait + 0.05)
                    preferred = self.quota.key_order("groq")
                if not preferred and not (has_real_telemetry and real_order):
                    raise RuntimeError(
                        f"All Groq keys are at their 30 RPM limit "
                        f"(next slot in ~{wait:.0f}s if known) -- not a payload or "
                        f"code failure, just rate-limit capacity."
                    )
            if has_real_telemetry and real_order:
                self.groq_engine._current_index = real_order[0]
            elif preferred:
                self.groq_engine._current_index = preferred[0].index

            result = self.groq_engine.generate(
                system_prompt=system_prompt,
                user_input=user_input,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
                reasoning_effort=reasoning_effort,
            )

            self._consume_groq_attempts()

            return result

        except Exception:

            self._consume_groq_attempts()

            raise

    def _consume_groq_attempts(self) -> None:

        attempts = getattr(
            self.groq_engine,
            "_last_attempts",
            [],
        )

        if not attempts:
            return

        for attempt in attempts:

            self.quota.record(
                provider="groq",
                key_index=int(
                    attempt.get("key_index", 0)
                ),
                status_code=attempt.get(
                    "status_code"
                ),
                headers=attempt.get(
                    "headers"
                ),
                success=bool(
                    attempt.get("success")
                ),
                error=attempt.get(
                    "error"
                ),
                confirmed=True,
            )

    # --------------------------------------------------------
    # MAIN ROUTER
    # --------------------------------------------------------

    def generate(
        self,
        system_prompt: str,
        user_input: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:

        # GROQ-ONLY (2026-09-20) -- see __init__'s comment. Kept as a
        # 1-element list (not simplified further) so provider_order()/
        # last_provider/the attempted-set bookkeeping below still read
        # naturally if a provider is ever deliberately added back.
        providers = [
            provider
            for provider in ("groq",)
            if provider in self.quota.providers
        ]

        if not providers:
            raise RuntimeError(
                "No cloud LLM provider is configured."
            )

        attempted = set()
        last_error: Optional[Exception] = None

        while len(attempted) < len(providers):

            ordered = self.quota.provider_order(
                providers,
                excluded=attempted,
            )

            if not ordered:
                break

            provider = ordered[0]

            attempted.add(provider)

            log_event(
                "llm_provider",
                f"selected provider={provider} "
                f"utilization="
                f"{self.quota.provider_utilization(provider) * 100:.1f}%",
            )

            try:

                result = self._generate_groq(
                    system_prompt,
                    user_input,
                    max_tokens,
                    temperature,
                    response_format,
                    reasoning_effort,
                )

                self.last_provider = provider
                self.last_error = None

                return result

            except Exception as exc:

                last_error = exc
                self.last_error = str(exc)

                log_event(
                    "llm_provider",
                    f"{provider} failed: {exc}; "
                    f"trying next provider",
                    level="warning",
                )

        raise RuntimeError(
            f"All cloud LLM providers failed. "
            f"Last error: {last_error}"
        )

    # --------------------------------------------------------
    # MONITOR / TRACE API
    # --------------------------------------------------------

    def quota_snapshot(self) -> Dict[str, Any]:
        return self.quota.snapshot()

    def provider_status(self) -> Dict[str, Any]:
        return self.quota.snapshot()