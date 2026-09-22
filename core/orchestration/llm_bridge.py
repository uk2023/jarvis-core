from __future__ import annotations

import json
import os
import socket
import time
from typing import Optional, List, Dict, Any

try:
    import requests
except ImportError:
    requests = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(BASE_DIR, ".env")

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    pass

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

try:
    from ..runtime.log import log_event
except ImportError:  # pragma: no cover
    def log_event(tag: str, message: str, level: str = "info") -> None:
        pass


# ---------------------------------------------------------------------------
# NEW PROVIDER ROUTER
# ---------------------------------------------------------------------------
# HybridLLMBridge remains the public/authoritative bridge.
# This module only delegates normal cloud generation to:
#
#   1. Existing GroqEngine
#   2. Cerebras
#   3. Cloudflare Workers AI
#
# The provider engine owns provider/key balancing and failover.
#
# IMPORTANT:
# - Existing CognitiveBudgeter is untouched.
# - Existing turn budget is reserved only by HybridLLMBridge.
# - Provider failover NEVER reserves another turn budget.
# - Tool calling remains Groq-only and does not use this router.
# ---------------------------------------------------------------------------

try:
    from .llm_provider_engine import LLMProviderEngine
except ImportError:
    try:
        from core.orchestration.llm_provider_engine import LLMProviderEngine
    except ImportError:
        LLMProviderEngine = None

try:
    from core.runtime.state_bus import get_state_bus
except ImportError:
    try:
        from ..runtime.state_bus import get_state_bus
    except ImportError:
        get_state_bus = None


class CognitiveBudgetExceeded(RuntimeError):
    """Raised when one runtime turn exceeds its configured LLM budget."""


# Floors for the clamp in optimize_payload() below. A call with less
# than this is not worth dispatching -- it would return a truncated
# fragment and burn budget for nothing.
_MIN_OUTPUT_TOKENS = 256
_MIN_VIABLE_CALL_TOKENS = 512

# DEGRADED-RESULT SENTINEL (2026-09-17, from UK's screenshots showing
# "[LLM unavailable: local fallback is disabled]" rendered as the WRITE
# step's CODE). generate_response() returns these strings rather than
# raising -- fine for a chat reply, actively harmful for a caller that
# treats the return value as content: codebox wrote the sentence into
# calculator.py as source, then "verified" it and reported failure four
# retries later without ever saying the real reason was that no model
# answered. Any caller consuming output as DATA (code, JSON, a plan)
# must check this first and fail honestly instead.
LLM_UNAVAILABLE_PREFIX = "[LLM unavailable"


def is_llm_unavailable(text: Any) -> bool:
    """True when generate_response() returned a degraded-result sentinel
    rather than real model output."""
    return isinstance(text, str) and text.strip().startswith(LLM_UNAVAILABLE_PREFIX)


class CognitiveBudgeter:
    """Hard working-memory/context budgeter for every LLM backend."""

    def __init__(self, max_context_tokens: int = 4096, safety_tokens: int = 128):
        self.max_context_tokens = max(256, int(max_context_tokens))
        self.safety_tokens = max(0, int(safety_tokens))

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return int(len(text.split()) * 1.3) + 4

    @staticmethod
    def _trim_to_tokens(text: str, token_budget: int) -> str:
        if not text or token_budget <= 0:
            return ""

        words = text.split()
        if not words:
            return ""

        marker = "\n[context truncated by 4096-token budget]"

        def fits(candidate: str) -> bool:
            return CognitiveBudgeter.estimate_tokens(candidate) <= token_budget

        if fits(text):
            return text

        lo, hi = 0, len(words)
        best = ""

        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = " ".join(words[:mid]) + marker

            if fits(candidate):
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return best

    def optimize_payload(
        self,
        system_prompt: str,
        user_input: str,
        max_tokens: int = 512,
    ) -> tuple[str, str]:

        output_budget = max(1, int(max_tokens))
        input_budget = self.max_context_tokens - output_budget - self.safety_tokens

        if input_budget <= 0:
            # CLAMP, DON'T CRASH (fixed 2026-09-16 from UK's screenshots:
            # "Code generation failed on attempt 1: No input context budget
            # remains for this LLM call" on a plain calculator.py request).
            #
            # This was pure arithmetic, not an exhausted quota: the LOCAL
            # model's budgeter is built with max_context_tokens=min(n_ctx,
            # 2048), while codebox.py asks for max_tokens=2000. That leaves
            # 2048 - 2000 - 128 = -80, so EVERY codebox generation through
            # the local model raised before a single token was requested.
            # No amount of extra Groq keys could have helped -- the call
            # never reached a provider.
            #
            # A caller asking for more output than the window holds is a
            # recoverable mismatch, so shrink the request to what actually
            # fits and leave room for a real prompt. Only a window too small
            # to hold anything at all is a genuine failure.
            usable = self.max_context_tokens - self.safety_tokens
            if usable < _MIN_VIABLE_CALL_TOKENS:
                raise CognitiveBudgetExceeded(
                    f"Context window too small to be usable: "
                    f"{self.max_context_tokens} tokens minus {self.safety_tokens} safety "
                    f"leaves {usable}, under the {_MIN_VIABLE_CALL_TOKENS} needed for any call."
                )
            # Give output at most half the usable window; the rest is prompt.
            output_budget = max(_MIN_OUTPUT_TOKENS, usable // 2)
            input_budget = usable - output_budget
            log_event(
                "llm_bridge",
                f"requested max_tokens={int(max_tokens)} exceeded the "
                f"{self.max_context_tokens}-token window; clamped output to "
                f"{output_budget} so the call can proceed.",
                level="warning",
            )

        sys_tokens = self.estimate_tokens(system_prompt)

        usr_budget = max(
            1,
            input_budget - min(sys_tokens, input_budget // 2),
        )

        bounded_user = self._trim_to_tokens(
            user_input,
            usr_budget,
        )

        remaining_for_system = max(
            0,
            input_budget - self.estimate_tokens(bounded_user),
        )

        bounded_system = self._trim_to_tokens(
            system_prompt,
            remaining_for_system,
        )

        total = (
            self.estimate_tokens(bounded_system)
            + self.estimate_tokens(bounded_user)
        )

        while total > input_budget and bounded_user:
            bounded_user = " ".join(
                bounded_user.split()[:-1]
            )

            total = (
                self.estimate_tokens(bounded_system)
                + self.estimate_tokens(bounded_user)
            )

        while total > input_budget and bounded_system:
            bounded_system = " ".join(
                bounded_system.split()[:-1]
            )

            total = (
                self.estimate_tokens(bounded_system)
                + self.estimate_tokens(bounded_user)
            )

        if total > input_budget:
            raise CognitiveBudgetExceeded(
                f"Unable to fit LLM input within {input_budget} tokens"
            )

        return bounded_system, bounded_user


class LlamaCppEngine:
    def __init__(
        self,
        model_filename: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        subdir: str = "Offline_LLM",
        n_ctx: int = 2048,
        n_threads: int = 2,
    ):

        if Llama is None:
            raise ImportError(
                "llama-cpp-python is not installed."
            )

        model_path = os.path.join(
            BASE_DIR,
            "models",
            subdir,
            model_filename,
        )

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Model file not found at: {model_path}. "
                f"Run download.sh, or place the GGUF file at "
                f"models/{subdir}/{model_filename} manually."
            )

        log_event(
            "llm_bridge",
            f"loading local model from {model_path} ..."
        )

        safe_threads = max(
            1,
            min(int(n_threads), 2),
        )

        safe_ctx = max(
            1024,
            min(int(n_ctx), 2048),
        )

        self.llm = Llama(
            model_path=model_path,
            n_ctx=safe_ctx,
            n_threads=safe_threads,
            use_mlock=False,
            use_mmap=True,
            verbose=False,
        )

        self.budgeter = CognitiveBudgeter(
            max_context_tokens=safe_ctx
        )

        log_event(
            "llm_bridge",
            f"local model loaded from models/{subdir}/ "
            f"(n_ctx={safe_ctx}, n_threads={safe_threads})."
        )

    def generate(
        self,
        system_prompt: str,
        user_input: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:

        opt_system, opt_user = self.budgeter.optimize_payload(
            system_prompt,
            user_input,
            max_tokens=max_tokens,
        )

        response = self.llm.create_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": opt_system,
                },
                {
                    "role": "user",
                    "content": opt_user,
                },
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response["choices"][0]["message"]["content"].strip()


class GroqEngine:
    VALID_MODELS = [
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-20b",
        "groq/compound",
        "groq/compound-mini",
        "allam-2-7b",
    ]

    MAX_TOTAL_SECONDS = 12.0
    # 2026-09-20: bounded count of cooldown-and-retry passes in
    # _post_chat_completion (see its docstring) -- was hardcoded to
    # "at most one retry"; now a named, tunable ceiling so a short
    # multi-second rate-limit window can be waited out across more
    # than one pass without ever risking an unbounded hang.
    MAX_RATE_LIMIT_RETRIES = 3

    # REAL, PUBLISHED per-model limits (2026-09-21, sourced VERBATIM from
    # Groq's own rate-limits doc table -- console.groq.com/docs, the
    # exact doc UK pasted -- never guessed). Groq's HTTP headers give a
    # real remaining-TPM count and a real remaining-RPD count, but NO
    # header for remaining RPM at all ("Always refers to Requests Per
    # Day" is stated for every request-count header they publish). RPM
    # therefore has to be tracked locally from real call timestamps (see
    # _record_rpm_window) against this real static ceiling -- this table
    # is data Groq published, not a number this code invented.
    _GROQ_MODEL_LIMITS = {
        # model: (rpm, rpd, tpm, tpd)
        "openai/gpt-oss-120b": (30, 1_000, 8_000, 200_000),
        "openai/gpt-oss-20b": (30, 1_000, 8_000, 200_000),
        "openai/gpt-oss-safeguard-20b": (30, 1_000, 8_000, 200_000),
        "qwen/qwen3.8-27b": (30, 1_000, 8_000, 200_000),
        "qwen/qwen3.6-27b": (30, 1_000, 8_000, 200_000),
        "meta-llama/llama-prompt-guard-2-22m": (30, 14_400, 15_000, 500_000),
        "meta-llama/llama-prompt-guard-2-86m": (30, 14_400, 15_000, 500_000),
        "whisper-large-v3": (20, 2_000, None, None),
        "whisper-large-v3-turbo": (20, 2_000, None, None),
    }
    # RPM sliding-window size, matching Groq's own "per minute" definition.
    _RPM_WINDOW_SECONDS = 60.0

    def __init__(
        self,
        api_keys: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 8.0,
        # RATE-LIMIT COOLDOWN (2026-09-19) -- see _post_chat_completion's
        # docstring. 2s default matches UK's explicit ask.
        rate_limit_cooldown_seconds: float = 2.0,
    ):

        if requests is None:
            raise ImportError(
                "The 'requests' package is not installed "
                "(pip install requests)."
            )
        self._rate_limit_cooldown_seconds = rate_limit_cooldown_seconds

        raw_keys = (
            api_keys
            or os.getenv("GROQ_API_KEYS")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("GROK_API_KEY")
            or ""
        )

        self.api_keys = [
            k.strip()
            for k in raw_keys.replace(" ", "").split(",")
            if k.strip()
        ]

        if not self.api_keys:
            raise RuntimeError(
                "No Groq API key (gsk_...) found in .env file."
            )

        target_model = (
            model
            or os.getenv("LLM_MODEL")
            or os.getenv("GROQ_MODEL")
            or "openai/gpt-oss-120b"
        )

        if target_model not in self.VALID_MODELS:
            target_model = "openai/gpt-oss-120b"

        self.model = target_model

        self.base_url = (
            base_url
            or "https://api.groq.com/openai/v1"
        )

        self.timeout = max(
            2.0,
            float(timeout),
        )

        self._current_index = 0

        # -------------------------------------------------------------------
        # EXISTING OPTIONAL GEMINI STATE
        # -------------------------------------------------------------------
        gemini_keys_raw = os.getenv("GEMINI_API_KEY") or ""

        self.gemini_api_keys = [
            k.strip()
            for k in gemini_keys_raw.replace(" ", "").split(",")
            if k.strip()
        ]

        self.gemini_base_url = (
            "https://generativelanguage.googleapis.com/v1beta/openai"
        )

        self.gemini_model = (
            os.getenv("GEMINI_MODEL")
            or "gemini-3.8-flash"
        )

        self._gemini_current_index = 0

        # -------------------------------------------------------------------
        # PERSISTENT HTTP SESSION
        # -------------------------------------------------------------------
        # Keeps TCP/TLS connections alive and avoids a brand-new TLS
        # handshake for every request.
        # -------------------------------------------------------------------

        self._session = requests.Session()

        # -------------------------------------------------------------------
        # NEW QUOTA-MANAGER HOOKS
        # -------------------------------------------------------------------
        # These are metadata only.
        #
        # Existing Groq rotation remains authoritative.
        # LLMProviderEngine reads this information after generate().
        # -------------------------------------------------------------------

        self._last_attempts: List[Dict[str, Any]] = []
        self._last_used_key_index: Optional[int] = None
        self._last_response_headers: Dict[str, Any] = {}
        self._last_retry_after: Optional[str] = None

        # -------------------------------------------------------------------
        # REAL PER-KEY TELEMETRY (2026-09-20, root-cause pass -- UK's
        # explicit spec: "actual Groq metadata... never guessed value ko
        # real quota mat dikhao").
        #
        # WHY THIS LIVES HERE, NOT IN LLMProviderEngine's ProviderQuotaManager:
        # that manager is only ever updated from the generate_response()
        # cloud-routing path (LLMProviderEngine.generate() -> quota.record()).
        # generate_with_tools() deliberately bypasses LLMProviderEngine
        # entirely and calls THIS engine directly (see HybridLLMBridge's own
        # comment: "Tool calling deliberately stays directly on Groq") -- so
        # every coding-agent / run_capability_worker / tool-calling call was
        # invisible to that quota manager, meaning monitor.py's LLM PROVIDER
        # BALANCE panel silently went stale or empty during exactly the kind
        # of session UK's chat logs show (heavy tool-calling use).
        # _post_chat_completion() is the ONE place both call paths always
        # pass through, so recording real per-key state HERE (from the
        # actual HTTP response headers already captured in attempt_info)
        # is authoritative for BOTH paths, not just one of them.
        #
        # Shape (per key_index): limit/remaining/reset for both the
        # requests-per-minute and tokens-per-minute windows, plus counters
        # and the last real request's metadata. Every field is None until a
        # real response header has actually provided it -- see
        # telemetry_snapshot()'s docstring for the NOT_PUBLISHED contract.
        self._key_telemetry: Dict[int, Dict[str, Any]] = {}
        # Real call timestamps per key, for the local RPM sliding window
        # (see _record_rpm_window) -- Groq publishes no remaining-RPM
        # header, so this is the only way to know real RPM headroom.
        self._request_timestamps: Dict[int, List[float]] = {}
        # Real selection reasoning for the MOST RECENT call -- populated
        # in _post_chat_completion_single_pass right where key_order is
        # computed, published via _publish_telemetry so llm_monitor.py's
        # SELECTION section reflects an actual decision instead of
        # NOT PUBLISHED/NONE every time (2026-09-21).
        self._last_selection: Dict[str, Any] = {}

    # -----------------------------------------------------------------------
    # REAL TELEMETRY CAPTURE + CAPACITY-AWARE KEY SELECTION
    # (2026-09-20, root-cause pass)
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_groq_duration(value: Any) -> Optional[float]:
        """Groq's rate-limit reset headers (x-ratelimit-reset-tokens,
        x-ratelimit-reset-requests) are DURATIONS like '7.66s' or '1m2.5s',
        not epoch timestamps. Parses the real value Groq sent; returns None
        (never a guess) if the header is absent or unparseable."""
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            pass
        import re as _re
        m = _re.match(r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$", s)
        if not m or not any(m.groups()):
            return None
        h, mi, se = (float(g) if g else 0.0 for g in m.groups())
        return h * 3600 + mi * 60 + se

    def _record_rpm_window(self, key_index: int, st: Dict[str, Any], now_t: float) -> None:
        """REAL local RPM tracking (2026-09-21, UK's explicit ask: track
        "reset per minute token time" / real RPM headroom per key).
        Groq's docs (the exact ones UK pasted) state plainly that every
        x-ratelimit-*-requests header is RPD, not RPM -- there is no
        header for remaining RPM. So this counts this engine's own REAL
        call timestamps for this key in the last 60 real seconds
        (never a guess) against Groq's own published static RPM ceiling
        for the model in use (_GROQ_MODEL_LIMITS, sourced from their
        docs) to compute a real rpm_remaining."""
        timestamps = self._request_timestamps.setdefault(key_index, [])
        timestamps.append(now_t)
        cutoff = now_t - self._RPM_WINDOW_SECONDS
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)
        limits = self._GROQ_MODEL_LIMITS.get(self.model)
        rpm_ceiling = limits[0] if limits else None
        if rpm_ceiling is not None:
            st["rpm_limit"] = rpm_ceiling
            st["rpm_remaining"] = max(0, rpm_ceiling - len(timestamps))
            # Reset "soon" = when the oldest call in the window falls out
            # of it -- the real next moment this key's RPM count actually
            # drops, not a guess.
            st["rpm_reset_at"] = timestamps[0] + self._RPM_WINDOW_SECONDS if timestamps else now_t

    def _record_key_telemetry(self, key_index: int, attempt_info: Dict[str, Any],
                              response_json: Optional[Dict[str, Any]] = None,
                              request_tokens_hint: Optional[int] = None) -> None:
        """Update the REAL per-key state from one actual HTTP attempt's
        headers/status -- never a fabricated or estimated value. Called for
        every attempt (success or failure) from EITHER generate_response's
        or generate_with_tools's call, since both funnel through
        _post_chat_completion -> _post_chat_completion_single_pass, which
        calls this once per attempt.

        FIXED 2026-09-21 (UK pasted Groq's own rate-limits doc AND a live
        monitor.py trace showing "RPM: 998/1000" -- a number that's
        actually the DAILY budget, mislabeled): per Groq's own docs,
        x-ratelimit-{limit,remaining,reset}-requests headers ALWAYS refer
        to Requests Per DAY (RPD), never per-minute -- there is no header
        for remaining RPM at all. The previous version of this method
        wrote those header values into the RPM fields, which is exactly
        the bug UK's trace exposed. Fixed: those headers now populate
        rpd_* (real, from Groq). RPM is now tracked LOCALLY from a
        sliding 60s window of this engine's own REAL call timestamps
        (see _record_rpm_window below) against Groq's own PUBLISHED
        static per-model RPM ceiling (_GROQ_MODEL_LIMITS, sourced
        verbatim from their rate-limits doc table, never guessed) --
        real data about real calls this process actually made, not a
        header Groq doesn't send."""
        now_t = time.time()
        st = self._key_telemetry.setdefault(key_index, {
            "key_index": key_index, "requests_used": 0, "requests_attempted": 0,
            "successes": 0, "failures": 0, "last_error": None,
        })
        st["requests_attempted"] += 1
        headers = attempt_info.get("headers") or {}

        def h(*names: str) -> Optional[str]:
            for n in names:
                for actual_key in headers:
                    if actual_key.lower() == n:
                        return headers[actual_key]
            return None

        # These three headers are RPD (Requests Per Day), per Groq's own
        # docs table -- see this method's docstring. NOT RPM.
        rpd_limit = h("x-ratelimit-limit-requests")
        rpd_remaining = h("x-ratelimit-remaining-requests")
        rpd_reset = self._parse_groq_duration(h("x-ratelimit-reset-requests"))
        tpm_limit = h("x-ratelimit-limit-tokens")
        tpm_remaining = h("x-ratelimit-remaining-tokens")
        tpm_reset = self._parse_groq_duration(h("x-ratelimit-reset-tokens"))

        # Only overwrite a field when THIS response actually published it --
        # never blank out previously-real data with a header-less attempt
        # (e.g. a connection-error attempt has no headers at all).
        if rpd_limit is not None:
            st["rpd_limit"] = int(rpd_limit)
        if rpd_remaining is not None:
            st["rpd_remaining"] = int(rpd_remaining)
        if rpd_reset is not None:
            st["rpd_reset_at"] = now_t + rpd_reset
        if tpm_limit is not None:
            st["tpm_limit"] = int(tpm_limit)
        if tpm_remaining is not None:
            st["tpm_remaining"] = int(tpm_remaining)
        if tpm_reset is not None:
            st["tpm_reset_at"] = now_t + tpm_reset

        self._record_rpm_window(key_index, st, now_t)

        status_code = attempt_info.get("status_code")
        st["status"] = "AVAILABLE"
        if status_code == 429:
            st["status"] = "COOLDOWN"
            # SAME-KEY REUSE COOLDOWN (UK's explicit spec): retry-after is
            # the real, authoritative "don't reuse this exact key until
            # X" signal Groq sends on a 429 -- kept separate from the
            # rpd/tpm window resets, which describe when the BUDGET
            # refills, not when a rate-limited key becomes callable again.
            retry_after = self._parse_groq_duration(attempt_info.get("retry_after")) or tpm_reset or rpd_reset
            if retry_after is not None:
                st["cooldown_until"] = now_t + retry_after
        elif status_code in (401, 403):
            st["status"] = "FAILED"
        elif attempt_info.get("success"):
            st["cooldown_until"] = None

        st["requests_used"] += 1
        if attempt_info.get("success"):
            st["successes"] += 1
            st["last_error"] = None
        else:
            st["failures"] += 1
            st["last_error"] = attempt_info.get("error")

        latency = None
        started = attempt_info.get("_started_at")
        if started is not None:
            latency = now_t - started

        usage = (response_json or {}).get("usage") if response_json else None
        last_request = {
            "estimated_tokens": request_tokens_hint,
            "request_id": (response_json or {}).get("id") if response_json else None,
            "model": (response_json or {}).get("model", self.model) if response_json else self.model,
            "status_code": status_code,
            "latency_seconds": latency,
        }
        if isinstance(usage, dict):
            last_request["actual_prompt_tokens"] = usage.get("prompt_tokens")
            last_request["actual_output_tokens"] = usage.get("completion_tokens")
            last_request["actual_total_tokens"] = usage.get("total_tokens")
        st["last_request"] = last_request

        self._record_tpd_counter(key_index, st, usage, now_t)

        # PERSISTENT TOKEN LEDGER (2026-09-21, UK's explicit spec: a
        # dedicated, disk-backed token_management.py that survives a
        # restart, broken down per-key AND per-purpose -- see that
        # module's docstring). Only a REAL successful response with a
        # real usage block is logged; a failed attempt has no usage to
        # record. self._current_call_purpose is set by whichever caller
        # (companion_tools.py's run_capability_worker, the plain chat
        # path, etc.) knows why this call is happening -- defaults to
        # "chat" so nothing goes unlabeled.
        if isinstance(usage, dict) and attempt_info.get("success"):
            try:
                from .token_management import get_token_manager
                get_token_manager().record(
                    purpose=getattr(self, "_current_call_purpose", None) or "chat",
                    provider="groq", key_index=key_index, model=last_request["model"],
                    prompt_tokens=usage.get("prompt_tokens") or 0,
                    completion_tokens=usage.get("completion_tokens") or 0,
                    total_tokens=usage.get("total_tokens") or 0,
                    request_id=last_request["request_id"],
                )
            except Exception:
                # Persisting the ledger must never break the actual call.
                pass

        try:
            self._publish_telemetry()
        except Exception:
            # Telemetry publishing must never break the actual LLM call.
            pass

    def _record_tpd_counter(self, key_index: int, st: Dict[str, Any],
                            usage: Optional[Dict[str, Any]], now_t: float) -> None:
        """REAL local TPD (Tokens Per Day) tracking (2026-09-21, UK's
        explicit spec, with the exact 5-point logic he described):
        Groq gives no remaining-TPD header at all, so the only way to
        know real daily headroom is to add up usage.total_tokens from
        every real successful response body ourselves.

        1. AUTO-RESET: before adding anything, check whether now_t has
           passed this key's own real daily reset clock (rpd_reset_at,
           set from the REAL x-ratelimit-reset-requests header -- RPD
           and TPD reset together once a day per Groq's docs) -- if so,
           the local counter goes back to 0 first, exactly like a new
           day starting.
        2. ACCUMULATE: add this call's real usage.total_tokens (never
           an estimate) to the running total.
        3. GATEKEEP: also record tpd_limit from the published static
           table so the double-layer gatekeeper in
           _capacity_ordered_key_indices can exclude a key whose local
           counter is already close to its real daily ceiling, the
           same way it already does for TPM."""
        reset_at = st.get("rpd_reset_at")
        if reset_at is not None and now_t >= reset_at:
            st["tpd_used"] = 0
            st["tpd_window_started_at"] = now_t
        st.setdefault("tpd_used", 0)
        st.setdefault("tpd_window_started_at", now_t)
        if isinstance(usage, dict):
            total = usage.get("total_tokens")
            if isinstance(total, (int, float)):
                st["tpd_used"] = st.get("tpd_used", 0) + int(total)
        limits = self._GROQ_MODEL_LIMITS.get(self.model)
        tpd_ceiling = limits[3] if limits else None
        if tpd_ceiling is not None:
            st["tpd_limit"] = tpd_ceiling
            st["tpd_remaining"] = max(0, tpd_ceiling - st["tpd_used"])

    def _publish_telemetry(self) -> None:
        try:
            from core.runtime.state_bus import get_state_bus
        except Exception:
            try:
                from ..runtime.state_bus import get_state_bus
            except Exception:
                return
        bus = get_state_bus(create=True)
        if bus is None:
            return
        snapshot = self.telemetry_snapshot()
        if hasattr(bus, "update_llm_provider_quota"):
            bus.update_llm_provider_quota({
                "providers": {"groq": snapshot},
                "selection_state": dict(self._last_selection) if self._last_selection else {},
                "last_provider": "groq" if self._last_selection.get("selected_key_index") is not None else None,
                "last_key_index": self._last_selection.get("selected_key_index"),
                "updated_at": time.time(),
            })

    def telemetry_snapshot(self) -> Dict[str, Any]:
        """REAL per-key Groq telemetry, in llm_monitor.py's expected shape.
        A field that Groq has never actually published for a key is simply
        absent (llm_monitor.py's own `fmt_num`/`fmt_time` render that as
        "NOT PUBLISHED" -- this function never fabricates a substitute)."""
        now_t = time.time()
        keys_out = []
        for idx in range(len(self.api_keys)):
            st = dict(self._key_telemetry.get(idx, {"key_index": idx}))
            cooldown_until = st.get("cooldown_until")
            if cooldown_until is not None and cooldown_until <= now_t:
                st["cooldown_until"] = None
                if st.get("status") == "COOLDOWN":
                    st["status"] = "AVAILABLE"
            keys_out.append(st)
        return {"model": self.model, "available": True, "keys": keys_out}

    def _capacity_ordered_key_indices(self, estimated_tokens: Optional[int] = None) -> List[int]:
        """REAL-CAPACITY-AWARE, BALANCED key order (2026-09-21, UK's
        explicit spec, twice now: "sabhi keys ko balance token use karna
        hai... jitna actual token size LLM ko pass hoga usi ke hisaab se
        token chune jayenge... sabse zyada remaining capacity waala token
        select ho"). Ranks by the WORST-case remaining fraction across
        BOTH real windows this engine actually tracks -- TPM (from
        Groq's real x-ratelimit-remaining-tokens header) and RPM (from
        _record_rpm_window's real local sliding-window count, since Groq
        publishes no remaining-RPM header at all). Using the remaining
        FRACTION (not the raw remaining count) is what makes this a real
        balancer rather than a fixed favorite: whichever key currently
        has the least headroom, proportionally, on its tightest
        dimension gets pushed back, so repeated calls naturally spread
        evenly across keys instead of hammering one "most recently
        topped-up" key -- exactly UK's "ek key 40% pe, baaki sab bhi
        38-42% range mein rahen" load-balancing intent.

        A key still in a real 429 cooldown is tried last. A key with NO
        telemetry yet (never called this process lifetime) is treated as
        unknown, not assumed-empty or assumed-full, and ordered by its
        plain round-robin position among other unknowns -- never guessed
        into a false priority."""
        now_t = time.time()
        total = len(self.api_keys)

        def remaining_fraction(st: Dict[str, Any], remaining_key: str, limit_key: str) -> Optional[float]:
            remaining = st.get(remaining_key)
            limit = st.get(limit_key)
            if remaining is None or not limit:
                return None
            return max(0.0, remaining) / limit

        def sort_key(idx: int) -> Tuple[int, float, int]:
            st = self._key_telemetry.get(idx)
            if not st:
                return (1, 0.0, idx)  # unknown -- neutral priority, stable order
            cooldown_until = st.get("cooldown_until")
            in_cooldown = cooldown_until is not None and cooldown_until > now_t
            if in_cooldown:
                return (2, 0.0, idx)  # known-cooldown -- tried last

            tpm_frac = remaining_fraction(st, "tpm_remaining", "tpm_limit")
            rpm_frac = remaining_fraction(st, "rpm_remaining", "rpm_limit")
            known_fracs = [f for f in (tpm_frac, rpm_frac) if f is not None]
            if not known_fracs:
                return (1, 0.0, idx)  # known key, but no real capacity data published yet
            # Worst-case (tightest) real dimension decides -- a key that's
            # nearly out of RPM is just as unusable as one nearly out of
            # TPM, whichever hits first.
            return (0, -min(known_fracs), idx)

        order = sorted(range(total), key=sort_key)

        # DOUBLE-LAYER GATEKEEPER (2026-09-21, UK's explicit spec: exclude
        # a key whose REAL remaining budget can't serve this call at all,
        # on ANY of the four windows Groq actually enforces -- not just
        # TPM. RPM/RPD/TPD exhaustion is checked unconditionally (a key
        # truly out of daily requests is unusable no matter the request
        # size); the TPM-vs-this-request check only applies when we have
        # a real size estimate to compare against. A key with no
        # published data for a given window is never excluded on a guess
        # for that window.
        def fits(i: int) -> bool:
            st = self._key_telemetry.get(i, {})
            rpm_rem = st.get("rpm_remaining")
            if rpm_rem is not None and rpm_rem <= 0:
                return False
            rpd_rem = st.get("rpd_remaining")
            if rpd_rem is not None and rpd_rem <= 0:
                return False
            tpd_rem = st.get("tpd_remaining")
            if tpd_rem is not None and tpd_rem <= 0:
                return False
            if estimated_tokens:
                tpm_rem = st.get("tpm_remaining")
                if tpm_rem is not None and tpm_rem < estimated_tokens:
                    return False
                if tpd_rem is not None and tpd_rem < estimated_tokens:
                    return False
            return True

        fitting = [i for i in order if fits(i)]
        if fitting:
            return fitting
        return order

    def gemini_available(self) -> bool:
        return bool(self.gemini_api_keys)

    def _post_chat_completion(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Outer wrapper (2026-09-19, UK: "LLM wala error provider
        failed [ho to] kabhi fail na ho -- ya available key rotate
        karke dhoondo, ya wait kare 2 sec key cooldown hone ka").

        The actual key-rotation logic lives in
        _post_chat_completion_single_pass() below, unchanged and still
        covered by this fix's own tests plus the 413/400 fail-fast
        tests from the previous pass. This wrapper adds exactly ONE
        thing on top: if that single pass exhausted every key and the
        failures were GENUINELY transient rate-limiting (429s -- a real
        "try again in a moment" signal, not a payload/format problem
        that waiting cannot fix), wait for the cooldown window Groq's
        per-key per-minute limit implies, then make another full pass.

        2026-09-20 (root-cause pass, UK: "coding agent/planning kabhi
        collapse na ho, jab tak available token budget na mil jaye
        wait kare, reserved rahe"): the wait length now comes from the
        REAL `retry-after` header Groq actually sent on this pass's
        failed attempts (self._last_attempts), not a blind fixed
        constant -- honoring the provider's own real "try again in Ns"
        signal instead of guessing. Falls back to the configured
        default only when no provider gave a real value. Up to
        MAX_RATE_LIMIT_RETRIES bounded passes (not just one) so a
        short-lived window (a few seconds) genuinely gets waited out
        instead of the caller collapsing on the first retry too -- but
        still bounded, so a real outage still gives up rather than
        hanging forever.
        """
        for retry_num in range(self.MAX_RATE_LIMIT_RETRIES):
            try:
                result = self._post_chat_completion_single_pass(payload)
                self._record_all_attempts_telemetry(payload, result)
                return result
            except Exception as exc:
                self._record_all_attempts_telemetry(payload, None)
                attempts = list(self._last_attempts or [])
                status_codes = [a.get("status_code") for a in attempts if a.get("status_code")]
                # Only retry when EVERY recorded attempt was a 429 -- if
                # even one was something else (413/400/timeout/5xx), the
                # first pass's own handling for that already did the right
                # thing, and a blanket cooldown wait would not fix it.
                all_rate_limited = bool(status_codes) and all(c == 429 for c in status_codes)
                is_last_pass = retry_num == self.MAX_RATE_LIMIT_RETRIES - 1
                if not all_rate_limited or is_last_pass:
                    # Bounded passes exhausted (or a non-rate-limit
                    # failure) -- this IS a genuine failure, not a
                    # momentary window. Give up honestly.
                    raise
                wait_seconds = self._real_retry_after_seconds(attempts)
                log_event(
                    "llm_bridge",
                    f"all {len(status_codes)} keys rate-limited (429) -- waiting "
                    f"{wait_seconds:.1f}s (pass {retry_num + 1}/{self.MAX_RATE_LIMIT_RETRIES}) "
                    f"for the per-minute window to clear, then trying again "
                    f"(not giving up on a momentary limit)",
                    level="warning",
                )
                time.sleep(wait_seconds)

    @staticmethod
    def _estimate_request_input_tokens(payload: Dict[str, Any]) -> Optional[int]:
        """REAL request-size estimate (2026-09-21, UK: "jitna actual
        token size LLM ko pass hoga usi ke hisaab se token chune
        jayenge"), computed from the ACTUAL messages this request is
        about to send -- not payload['max_tokens'] (that's the OUTPUT
        cap, a completely different number, previously mislabeled as
        the request's "estimated" size here). No real tokenizer is
        available in this sandbox (no network to install tiktoken), so
        this is still a chars/4 estimate, not exact -- but it is now an
        estimate of the actual content being sent, not of an unrelated
        field, and it is what key SELECTION and the telemetry's
        "estimated_tokens" both use from here on."""
        if not isinstance(payload, dict):
            return None
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return None
        total_chars = 0
        for m in messages:
            if isinstance(m, dict):
                content = m.get("content")
                if isinstance(content, str):
                    total_chars += len(content)
        return max(1, total_chars // 4) if total_chars else None

    def _record_all_attempts_telemetry(self, payload: Dict[str, Any],
                                       result: Optional[Dict[str, Any]]) -> None:
        """Feeds this pass's REAL attempt records (self._last_attempts,
        populated by _post_chat_completion_single_pass from actual HTTP
        responses) into _record_key_telemetry, one call per real attempt.
        Only the LAST attempt -- the one that actually returned `result`,
        if any -- gets the real token-usage numbers attached, since only
        that attempt has a response body to read them from."""
        attempts = list(self._last_attempts or [])
        if not attempts:
            return
        hint = self._estimate_request_input_tokens(payload)
        for i, attempt_info in enumerate(attempts):
            is_last = i == len(attempts) - 1
            self._record_key_telemetry(
                attempt_info.get("key_index", 0), attempt_info,
                response_json=result if (is_last and attempt_info.get("success")) else None,
                request_tokens_hint=hint,
            )

    def _real_retry_after_seconds(self, attempts: List[Dict[str, Any]]) -> float:
        """Shortest REAL retry-after value Groq actually returned across
        this pass's failed attempts, capped to a sane ceiling. Never
        fabricated -- falls back to the configured default only when
        no attempt carried a usable header."""
        values: List[float] = []
        for a in attempts:
            raw = a.get("retry_after")
            if raw is None:
                continue
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
        if not values:
            return self._rate_limit_cooldown_seconds
        # Shortest real wait across keys, but never less than the
        # configured floor (avoids a hot-spin loop on a near-zero
        # header) and never more than a sane ceiling (a single pass
        # should never block a turn for an unreasonable amount of time
        # -- callers above this layer decide whether a longer wait is
        # acceptable for their situation).
        return max(self._rate_limit_cooldown_seconds, min(min(values), 20.0))

    def _post_chat_completion_single_pass(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:

        url = f"{self.base_url}/chat/completions"

        total_keys = len(self.api_keys)

        last_error = None

        deadline = (
            time.time()
            + self.MAX_TOTAL_SECONDS
        )

        # Reset per-request attempt history.
        self._last_attempts = []
        self._last_response_headers = {}
        self._last_retry_after = None
        self._last_used_key_index = None

        # PAYLOAD-LEVEL RETRY STATE (2026-09-19) -- tracked OUTSIDE the
        # payload dict itself, never as extra keys inside it (Groq's API
        # would reject an unrecognized field, which is exactly the kind
        # of self-inflicted 400 this whole fix exists to prevent).
        shrunk_once = False
        retried_400_once = False

        # CAPACITY-AWARE KEY ORDER (2026-09-20, root-cause pass -- UK's
        # explicit spec: "max untouched token availability exhaust kare,
        # bas yehi order mein key rotate ho"). Computed ONCE per call from
        # REAL, previously-observed per-key telemetry (see
        # _capacity_ordered_key_indices's docstring for exactly how a key
        # with no data yet, vs a real cooldown, vs real remaining capacity,
        # are each ordered -- never a guess dressed up as a priority).
        estimated_input = self._estimate_request_input_tokens(payload)
        key_order = self._capacity_ordered_key_indices(estimated_input)

        # REAL SELECTION RECORD (2026-09-21) -- published so llm_monitor.py's
        # SELECTION section shows an actual decision (current_request_estimate/
        # eligible/excluded/last_selected), not permanently empty. "Excluded"
        # here only ever lists a key this call's real _capacity_ordered_key_
        # indices() filtering step actually dropped for a stated reason --
        # never guessed.
        all_indices = list(range(total_keys))
        excluded_indices = [i for i in all_indices if i not in key_order]
        self._last_selection = {
            "current_request_estimate": {"input_tokens": estimated_input} if estimated_input else None,
            "eligible_keys": [
                {"provider": "groq", "key_index": i,
                 "utilization_percent": (
                     round(100 * (1 - (self._key_telemetry[i]["tpm_remaining"] / self._key_telemetry[i]["tpm_limit"])), 1)
                     if self._key_telemetry.get(i, {}).get("tpm_remaining") is not None
                     and self._key_telemetry.get(i, {}).get("tpm_limit")
                     else None
                 )}
                for i in key_order
            ],
            "excluded_keys": [
                {"key_index": i, "reason": "insufficient real remaining capacity for this request's estimated size"}
                for i in excluded_indices
            ],
            "selected_provider": "groq" if key_order else None,
            "selected_key_index": key_order[0] if key_order else None,
        }

        for attempt in range(total_keys):

            remaining = (
                deadline - time.time()
            )

            if remaining <= 0.5:
                last_error = (
                    last_error
                    or f"Groq rotation budget "
                       f"({self.MAX_TOTAL_SECONDS}s) exhausted"
                )
                break

            key_index = key_order[attempt] if attempt < len(key_order) else (self._current_index + attempt) % total_keys

            # Keep _current_index advancing too (legacy fallback position
            # for any caller/telemetry that still reads it directly, and
            # so a run with zero telemetry yet -- e.g. process just
            # started -- still round-robins instead of hammering key 0).
            self._current_index = (key_index + 1) % total_keys

            self._last_used_key_index = key_index

            active_key = self.api_keys[key_index]

            key_num = key_index + 1

            headers = {
                "Authorization": f"Bearer {active_key}",
                "Content-Type": "application/json",
            }

            per_call_read_timeout = max(
                1.0,
                min(
                    self.timeout,
                    remaining - 0.5,
                ),
            )

            attempt_info: Dict[str, Any] = {
                "key_index": key_index,
                "key_number": key_num,
                "status_code": None,
                "headers": {},
                "success": False,
                "error": None,
                "retry_after": None,
                "_started_at": time.time(),
            }

            try:

                log_event(
                    "llm_bridge",
                    f"groq key #{key_num}/{total_keys} | "
                    f"model: {self.model}"
                    f"{' | tools' if payload.get('tools') else ''}",
                )

                resp = self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=(
                        2.5,
                        per_call_read_timeout,
                    ),
                )

                response_headers = dict(
                    resp.headers
                )

                self._last_response_headers = (
                    response_headers
                )

                attempt_info["status_code"] = (
                    resp.status_code
                )

                attempt_info["headers"] = (
                    response_headers
                )

                retry_after = (
                    resp.headers.get("retry-after")
                )

                attempt_info["retry_after"] = (
                    retry_after
                )

                self._last_retry_after = (
                    retry_after
                )

                # -----------------------------------------------------------
                # IMPORTANT:
                # Record every actual Groq request attempt.
                # -----------------------------------------------------------

                if resp.status_code in (
                    404,
                    401,
                    403,
                    429,
                ):

                    body = (
                        resp.text.strip()[:200]
                    )

                    log_event(
                        "llm_bridge",
                        f"groq key #{key_num} failed "
                        f"HTTP {resp.status_code}: {body}",
                        level="warning",
                    )

                    last_error = (
                        f"HTTP {resp.status_code} ({body})"
                    )

                    attempt_info["error"] = (
                        last_error
                    )

                    self._last_attempts.append(
                        attempt_info
                    )

                    continue

                # PAYLOAD-LEVEL ERRORS -- FAIL FAST, DON'T ROTATE KEYS
                # (2026-09-19, UK's own monitor trace: 413 Payload Too
                # Large repeated identically across all 10 keys, then
                # separately 400 Bad Request repeated identically
                # across all 10 keys too -- each sequence burning
                # several real seconds of wall-clock time for a
                # guaranteed-repeat failure). 413 and 400 are properties
                # of THIS REQUEST -- a different API key authenticates
                # the exact same bytes, it cannot make an oversized or
                # malformed payload become a valid one. The 404/401/403/
                # 429 tuple above is correctly key-scoped (a bad/rate-
                # limited/unauthorized KEY); this is not.
                #
                # 413 specifically is actionable: shrink the payload
                # (halve max_tokens and the message-trim budget) and
                # retry ONCE more in this same loop -- not per-key, just
                # once -- before giving up. 400 is not safely fixable
                # here (could be a real malformed-request bug); allow
                # at most ONE extra key in case it is genuinely key/
                # plan-specific, then stop -- never all ten.
                if resp.status_code == 413:
                    body = resp.text.strip()[:200]
                    log_event(
                        "llm_bridge",
                        f"groq key #{key_num} got HTTP 413 (payload too large) -- "
                        f"shrinking payload and retrying once, not rotating keys "
                        f"(a different key cannot make the same oversized request fit)",
                        level="warning",
                    )
                    last_error = f"HTTP 413 ({body})"
                    attempt_info["error"] = last_error
                    self._last_attempts.append(attempt_info)

                    if not shrunk_once:
                        shrunk_once = True
                        payload = dict(payload)
                        if isinstance(payload.get("max_tokens"), int):
                            payload["max_tokens"] = max(256, payload["max_tokens"] // 2)
                        msgs = payload.get("messages")
                        if isinstance(msgs, list) and len(msgs) > 2:
                            # Keep the system message (if first) and the
                            # single most recent message; drop everything
                            # else -- the most aggressive trim available,
                            # used only after the normal trim budget
                            # already failed to avoid a 413.
                            system = [m for m in msgs if m.get("role") == "system"][:1]
                            payload["messages"] = system + msgs[-1:]
                        continue
                    # GIVE UP -- deliberately `break`, not `raise`, here.
                    # This whole block sits inside the per-attempt `try`,
                    # and a `raise` would be caught by that try's own
                    # generic `except Exception` below, which logs it and
                    # CONTINUES THE LOOP -- silently defeating the entire
                    # point of this fix (found by this fix's own test:
                    # an earlier version of this code raised here and
                    # still made all 10 calls). `break` exits the loop
                    # directly; the function's normal post-loop
                    # `raise RuntimeError(...last_error...)` then fires
                    # once, with this message.
                    last_error = (
                        f"HTTP 413 ({body}) -- payload too large even after "
                        f"shrinking once; the content itself needs to be "
                        f"generated in smaller chunks, not retried as one "
                        f"request"
                    )
                    break

                if resp.status_code == 400:
                    body = resp.text.strip()[:200]
                    log_event(
                        "llm_bridge",
                        f"groq key #{key_num} got HTTP 400 (bad request) -- "
                        f"this is almost certainly a request-format problem, not "
                        f"a key problem; trying at most one more key before "
                        f"failing fast instead of rotating through all {total_keys}",
                        level="warning",
                    )
                    last_error = f"HTTP 400 ({body})"
                    attempt_info["error"] = last_error
                    self._last_attempts.append(attempt_info)

                    if not retried_400_once:
                        retried_400_once = True
                        continue
                    # GIVE UP -- `break`, not `raise`; see the 413
                    # branch's comment above for exactly why a `raise`
                    # here would be silently swallowed and retried by
                    # this same try block's own except clause.
                    last_error = (
                        f"HTTP 400 ({body}) on two different keys -- a "
                        f"request-format problem that key rotation cannot fix"
                    )
                    break

                resp.raise_for_status()

                data = resp.json()

                attempt_info["success"] = True

                self._last_attempts.append(
                    attempt_info
                )

                return data

            except Exception as exc:

                attempt_info["error"] = str(exc)

                self._last_attempts.append(
                    attempt_info
                )

                log_event(
                    "llm_bridge",
                    f"groq key #{key_num} error: "
                    f"{exc}. trying next key...",
                    level="warning",
                )

                last_error = exc

        raise RuntimeError(
            f"Groq request failed within "
            f"{self.MAX_TOTAL_SECONDS}s budget. "
            f"Last error: {last_error}"
        )

    def generate(
        self,
        system_prompt: str,
        user_input: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_input,
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            payload["response_format"] = response_format

        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        data = self._post_chat_completion(
            payload
        )

        return (
            data["choices"][0]["message"]["content"]
            .strip()
        )

    def generate_with_tools(
        self,
        messages: list,
        tools: list,
        tool_choice: str = "auto",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "tool_choice": tool_choice,
        }

        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        data = self._post_chat_completion(
            payload
        )

        return data["choices"][0]["message"]


class HybridLLMBridge:
    CONNECTIVITY_CHECK_INTERVAL_SECONDS = 15

    CONNECTIVITY_TEST_HOST = "8.8.8.8"
    CONNECTIVITY_TEST_PORT = 53
    CONNECTIVITY_TIMEOUT = 1.5

    RESPONSE_TOKEN_FLOOR = 2000

    def __init__(
        self,
        model_filename: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        n_ctx: int = 2048,
        n_threads: int = 2,
        force_mode: Optional[str] = None,
    ):

        self._model_filename = model_filename
        self._n_ctx = n_ctx
        self._n_threads = n_threads
        self._force_mode = force_mode

        self._groq_engine: Optional[GroqEngine] = None
        self._local_engine: Optional[LlamaCppEngine] = None
        self._slm_engine: Optional[LlamaCppEngine] = None

        # -------------------------------------------------------------------
        # NEW:
        # Provider router.
        #
        # This does NOT replace HybridLLMBridge.
        # HybridLLMBridge remains the public bridge and budget authority.
        # -------------------------------------------------------------------

        self._provider_engine: Optional[
            LLMProviderEngine
        ] = None

        self._last_check_time = 0.0
        self._last_online_result = False

        self.last_error: Optional[str] = None
        self.last_backend = "idle"

        self.is_ready = False

        # Existing cognitive budget state.
        self._budget_max_calls = 2
        self._budget_max_output_tokens = 768
        self._budget_semantic_tokens = 256

        self._turn_calls = 0
        self._coding_worker_calls = 0
        self._turn_reserved_tokens = 0
        self._turn_active = False

        self._max_calls_per_level = 2
        self._level_calls: Dict[str, int] = {}
        self._level_overrides: Dict[str, int] = {}

        self._context_budgeter = CognitiveBudgeter(
            max_context_tokens=n_ctx
        )

        # CLOUD-SIZED budgeter (2026-09-17, see generate_response's
        # comment on why this exists). VALUE HISTORY: this was briefly
        # set to 8192 in an earlier fix this session, unproven against
        # a real Groq call (no network in the build sandbox). UK's very
        # next test showed EVERY one of 10 keys returning "400 Bad
        # Request" -- uniform failure across all keys on the SAME
        # request is the signature of an invalid/oversized payload, not
        # a key or rate-limit problem (confirmed against Groq's own
        # documented error semantics). 8192 was a guess, not a verified
        # safe value for the configured model, and it is the one thing
        # this session changed that affects prompt SIZE. Reverted to
        # 4096 -- still real headroom over the original local-model-
        # sized 2048 that ran safely for months, without the unverified
        # jump. If UK confirms 400s are gone, this can be raised
        # further with an actual test behind it instead of a guess.
        self._cloud_context_budgeter = CognitiveBudgeter(
            max_context_tokens=4096
        )

        self._load_budget_policy()

        self._offline_model_config = {
            "subdir": "Offline_LLM",
            "model_filename": model_filename,
            "n_ctx": n_ctx,
            "n_threads": n_threads,
        }

        self._slm_model_config = {
            "subdir": "SLM",
            "model_filename":
                "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "n_ctx": 2048,
            "n_threads": 2,
        }

        self._load_model_policy()

    def _load_model_policy(self) -> None:

        config_path = os.path.join(
            BASE_DIR,
            "config",
            "models.json",
        )

        try:

            with open(
                config_path,
                "r",
                encoding="utf-8",
            ) as handle:

                models = json.load(handle)

            if isinstance(
                models.get("offline_llm"),
                dict,
            ):

                self._offline_model_config.update(
                    {
                        "subdir":
                            models["offline_llm"].get(
                                "subdir",
                                self._offline_model_config[
                                    "subdir"
                                ],
                            ),

                        "model_filename":
                            models["offline_llm"].get(
                                "model_filename",
                                self._offline_model_config[
                                    "model_filename"
                                ],
                            ),

                        "n_ctx":
                            int(
                                models["offline_llm"].get(
                                    "n_ctx",
                                    self._offline_model_config[
                                        "n_ctx"
                                    ],
                                )
                            ),

                        "n_threads":
                            int(
                                models["offline_llm"].get(
                                    "n_threads",
                                    self._offline_model_config[
                                        "n_threads"
                                    ],
                                )
                            ),
                    }
                )

            if isinstance(
                models.get("slm"),
                dict,
            ):

                self._slm_model_config.update(
                    {
                        "subdir":
                            models["slm"].get(
                                "subdir",
                                self._slm_model_config[
                                    "subdir"
                                ],
                            ),

                        "model_filename":
                            models["slm"].get(
                                "model_filename",
                                self._slm_model_config[
                                    "model_filename"
                                ],
                            ),

                        "n_ctx":
                            int(
                                models["slm"].get(
                                    "n_ctx",
                                    self._slm_model_config[
                                        "n_ctx"
                                    ],
                                )
                            ),

                        "n_threads":
                            int(
                                models["slm"].get(
                                    "n_threads",
                                    self._slm_model_config[
                                        "n_threads"
                                    ],
                                )
                            ),
                    }
                )

        except (
            OSError,
            ValueError,
            TypeError,
            AttributeError,
            KeyError,
        ):
            pass

    def _load_budget_policy(self) -> None:

        config_path = os.path.join(
            BASE_DIR,
            "config",
            "cognition.json",
        )

        try:

            with open(
                config_path,
                "r",
                encoding="utf-8",
            ) as handle:

                llm = json.load(handle).get(
                    "llm",
                    {},
                )

            self._budget_max_calls = max(
                1,
                int(
                    llm.get(
                        "max_calls_per_turn",
                        self._budget_max_calls,
                    )
                ),
            )

            # EXTENDED-TURN CEILING (2026-09-16). A normal chat turn is
            # capped at max_calls_per_turn (9) and that stays. But a
            # multi-step task legitimately needs roughly one call PER
            # STEP, so a 10-step task cannot fit under 9 no matter how
            # the per-level caps are set. This is the separate, higher
            # ceiling that applies ONLY once a turn has started spending
            # at the extended_thinking level -- see _note_level_call.
            self._budget_max_calls_extended = max(
                self._budget_max_calls,
                int(llm.get("max_calls_per_turn_extended", 45)),
            )

            self._budget_max_output_tokens = max(
                1,
                int(
                    llm.get(
                        "max_output_tokens_per_turn",
                        self._budget_max_output_tokens,
                    )
                ),
            )

            self._budget_semantic_tokens = max(
                1,
                int(
                    llm.get(
                        "semantic_fallback_tokens",
                        self._budget_semantic_tokens,
                    )
                ),
            )

            self._max_calls_per_level = max(
                1,
                int(
                    llm.get(
                        "max_calls_per_level",
                        self._max_calls_per_level,
                    )
                ),
            )

            overrides = llm.get(
                "max_calls_per_level_overrides"
            )

            self._level_overrides = (
                {
                    str(k): max(1, int(v))
                    for k, v in overrides.items()
                }
                if isinstance(overrides, dict)
                else {}
            )

        except (
            OSError,
            ValueError,
            TypeError,
            AttributeError,
        ):
            pass

    def begin_turn_budget(self) -> None:

        self._load_budget_policy()

        self._turn_calls = 0
        self._coding_worker_calls = 0
        self._turn_reserved_tokens = 0
        self._turn_active = True
        self._level_calls = {}
        # See budget_status()'s comment on why this exists.
        self._turn_used_extended_ceiling = False

    def budget_status(self) -> Dict[str, Any]:
        # STANDARD THINKING numbers -- ALWAYS the 8-call ceiling, NEVER
        # inflated to 80 just because a coding-worker call happened
        # somewhere in this turn (fixed 2026-09-17; see _reserve_budget's
        # comment on the two-counter split this replaced).
        coding_ceiling = getattr(self, "_budget_max_calls_extended", self._budget_max_calls)
        return {
            "active":
                self._turn_active,

            "calls":
                self._turn_calls,

            "max_calls":
                self._budget_max_calls,

            "reserved_output_tokens":
                self._turn_reserved_tokens,

            "max_output_tokens":
                self._budget_max_output_tokens,

            "remaining_calls":
                max(
                    0,
                    self._budget_max_calls
                    - self._turn_calls,
                ),

            "remaining_output_tokens":
                max(
                    0,
                    self._budget_max_output_tokens
                    - self._turn_reserved_tokens,
                ),

            "max_calls_per_level":
                self._max_calls_per_level,

            "level_calls":
                dict(self._level_calls),

            # CODING WORKER BUDGET -- a genuinely separate counter (see
            # _reserve_budget). Only meaningful once a coding-agent/
            # codebox action has actually made an extended_thinking-level
            # call this turn; callers should treat coding_worker_calls==0
            # as "not used this turn", not "0/80 remaining".
            "coding_worker_calls":
                getattr(self, "_coding_worker_calls", 0),

            "coding_worker_max_calls":
                coding_ceiling,

            "coding_worker_remaining_calls":
                max(0, coding_ceiling - getattr(self, "_coding_worker_calls", 0)),
        }

    def _reserve_budget(
        self,
        requested_tokens: int,
        level: Optional[str] = None,
    ) -> int:

        if not self._turn_active:
            self.begin_turn_budget()

        requested = max(
            1,
            int(requested_tokens),
        )

        # TWO INDEPENDENT COUNTERS (fixed 2026-09-17, UK's explicit spec:
        # "Keep Standard Thinking independent from Coding Worker budget
        # ... Do NOT convert the normal 8-call budget into an 80-call
        # single-turn budget"). Previously both standard chat calls and
        # extended_thinking (coding-worker) calls incremented the SAME
        # self._turn_calls counter, just checked against a bigger
        # ceiling when the level was extended_thinking -- so the moment
        # ANY call in a turn used that level (e.g. a chat turn that
        # invoked run_coding_agent as a tool), budget_status() started
        # reporting max_calls=80 for the WHOLE turn, including the
        # ordinary perception/response calls that have nothing to do
        # with coding. Now extended_thinking calls consume their own
        # separate self._coding_worker_calls counter against
        # _budget_max_calls_extended; self._turn_calls (and therefore
        # the main "calls"/"max_calls" in budget_status()) is reserved
        # for -- and only ever reflects -- Standard Thinking's 8-call
        # ceiling, exactly as the spec requires.
        if level == "extended_thinking":

            coding_ceiling = getattr(self, "_budget_max_calls_extended", self._budget_max_calls)

            if self._coding_worker_calls >= coding_ceiling:

                raise CognitiveBudgetExceeded(
                    f"Coding Worker LLM call budget exceeded: "
                    f"{coding_ceiling} calls per turn"
                )

            self._coding_worker_calls += 1
            self._turn_used_extended_ceiling = True

        else:

            if self._turn_calls >= self._budget_max_calls:

                raise CognitiveBudgetExceeded(
                    f"LLM call budget exceeded: "
                    f"{self._budget_max_calls} calls per turn"
                )

            self._turn_calls += 1

        if (
            level
            and self._level_calls.get(level, 0)
            >= self._level_overrides.get(
                level,
                self._max_calls_per_level,
            )
        ):

            cap = self._level_overrides.get(
                level,
                self._max_calls_per_level,
            )

            raise CognitiveBudgetExceeded(
                f"LLM per-level call budget exceeded: "
                f"'{level}' already used "
                f"{self._level_calls.get(level, 0)}/{cap} "
                f"calls this turn"
            )

        remaining = (
            self._budget_max_output_tokens
            - self._turn_reserved_tokens
        )

        if (
            level
            and level not in (
                "response_generation",
                None,
            )
        ):

            usable = (
                remaining
                - self.RESPONSE_TOKEN_FLOOR
            )

            if usable <= 0 or requested > usable:

                raise CognitiveBudgetExceeded(
                    f"LLM output-token budget exceeded: "
                    f"'{level}' requested {requested} "
                    f"tokens but only "
                    f"{max(0, usable)} are available "
                    f"to preparatory calls "
                    f"(the last "
                    f"{self.RESPONSE_TOKEN_FLOOR} tokens "
                    f"are reserved for the final reply)"
                )

        if remaining <= 0 or requested > remaining:

            raise CognitiveBudgetExceeded(
                f"LLM output-token budget exceeded: "
                f"requested {requested} tokens but only "
                f"{max(0, remaining)} remain of the "
                f"{self._budget_max_output_tokens}-token "
                f"turn budget"
            )

        # NOTE: the call-count increment already happened above (either
        # self._turn_calls or self._coding_worker_calls, depending on
        # level) -- this used to unconditionally increment
        # self._turn_calls AGAIN here, which would have double-counted
        # standard calls and wrongly counted extended_thinking calls
        # against the standard counter too. Only the per-level and
        # token bookkeeping remain here.

        if level:

            self._level_calls[level] = (
                self._level_calls.get(level, 0)
                + 1
            )

        self._turn_reserved_tokens += requested

        return requested

    def verify_offline_ready(self) -> bool:

        try:

            self._get_local()

            self.is_ready = True
            self.last_error = None
            self.last_backend = "local"

            return True

        except Exception as exc:

            self.is_ready = False
            self.last_error = str(exc)

            return False

    def _is_online(self) -> bool:

        if self._force_mode == "online":
            return True

        if self._force_mode == "offline":
            return False

        now = time.time()

        if (
            now - self._last_check_time
            < self.CONNECTIVITY_CHECK_INTERVAL_SECONDS
        ):
            return self._last_online_result

        online = False

        try:

            with socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            ) as sock:

                sock.settimeout(
                    self.CONNECTIVITY_TIMEOUT
                )

                sock.connect(
                    (
                        self.CONNECTIVITY_TEST_HOST,
                        self.CONNECTIVITY_TEST_PORT,
                    )
                )

            online = True

        except OSError:

            online = False

        self._last_check_time = now
        self._last_online_result = online

        return online

    def _get_groq(self) -> GroqEngine:

        if self._groq_engine is None:
            self._groq_engine = GroqEngine()

        return self._groq_engine

    # -----------------------------------------------------------------------
    # LLM PROVIDER QUOTA -> STATE BUS
    # -----------------------------------------------------------------------

    def _publish_llm_provider_quota(self) -> None:
        """Publish the in-process provider quota snapshot to StateBus.

        Read-only telemetry. No network/health-check request is made.
        monitor.py reads this data from the existing IPC snapshot.
        """
        try:
            if (
                self._provider_engine is None
                or get_state_bus is None
            ):
                return

            quota = self._provider_engine.quota_snapshot()

            if not isinstance(quota, dict):
                return

            bus = get_state_bus(create=True)

            if bus is not None:
                bus.update_llm_provider_quota(quota)

        except Exception:
            # Monitoring must never break the LLM path.
            pass

    # -----------------------------------------------------------------------
    # NEW PROVIDER ENGINE LAZY LOADER
    # -----------------------------------------------------------------------

    def _get_provider_engine(self) -> LLMProviderEngine:

        if LLMProviderEngine is None:

            raise ImportError(
                "LLMProviderEngine is unavailable. "
                "Expected: core/orchestration/"
                "llm_provider_engine.py"
            )

        if self._provider_engine is None:

            groq_engine = None

            # Keep the existing GroqEngine instance authoritative.
            # If Groq keys exist, inject the SAME engine into the provider
            # router. No second Groq engine is created.
            if (
                os.getenv("GROQ_API_KEYS")
                or os.getenv("GROQ_API_KEY")
                or os.getenv("GROK_API_KEY")
            ):

                groq_engine = self._get_groq()

            self._provider_engine = LLMProviderEngine(
                groq_engine=groq_engine
            )

            # PUBLISH IMMEDIATELY ON CREATION (fixed 2026-09-16 from UK's
            # report: "provider engine ka render nahi kar raha monitor.py").
            # _publish_llm_provider_quota() was only ever called from inside
            # generate(), so the LLM PROVIDER BALANCE block in monitor.py had
            # nothing to read until the first cloud call completed -- and if
            # the very first call failed for an unrelated reason (e.g. the
            # context-budget bug fixed in optimize_payload above), it stayed
            # empty for the whole session. The keys were configured and the
            # engine was balancing them correctly; only the telemetry was
            # missing, which made a working subsystem look dead.
            self._publish_llm_provider_quota()

        return self._provider_engine

    def _get_local(self) -> LlamaCppEngine:

        if self._local_engine is None:

            cfg = self._offline_model_config

            self._local_engine = LlamaCppEngine(
                model_filename=cfg["model_filename"],
                subdir=cfg["subdir"],
                n_ctx=cfg["n_ctx"],
                n_threads=cfg["n_threads"],
            )

        return self._local_engine

    def get_slm_engine(self) -> LlamaCppEngine:

        if self._slm_engine is None:

            cfg = self._slm_model_config

            self._slm_engine = LlamaCppEngine(
                model_filename=cfg["model_filename"],
                subdir=cfg["subdir"],
                n_ctx=cfg["n_ctx"],
                n_threads=cfg["n_threads"],
            )

        return self._slm_engine

    def generate(
        self,
        system_prompt: str,
        user_input: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        level: Optional[str] = None,
    ) -> str:

        return self.generate_response(
            system_prompt=system_prompt,
            user_input=user_input,
            max_tokens=max_tokens,
            temperature=temperature,
            level=level,
        )

    # -----------------------------------------------------------------------
    # TOOL CALLING REMAINS GROQ-ONLY
    # -----------------------------------------------------------------------

    def _trim_messages_to_budget(self, messages: list, max_tokens: int) -> list:
        """Keeps `messages` under a rough token budget by dropping the
        OLDEST non-system turns first -- system messages and the most
        recent turns are preserved, since those matter most for a
        coherent reply.

        FIXED 2026-09-18 (UK's monitor.py trace: all 10 Groq keys
        failing with '413 Payload Too Large' on the SAME request --
        proof it's a payload-size problem, not a key problem, since
        payload size is a property of the request, identical across
        every key). Root cause: generate_with_tools (this is the path
        EVERY ordinary chat turn's tool-calling goes through) never
        applied ANY size limit to `messages` at all -- generate_response
        has had CognitiveBudgeter/optimize_payload since early in this
        project, but the tool-calling path was never wired to it, so a
        long conversation history (or a large grounding-context block
        appended to one message, see App.tsx's groundingSummary) could
        grow the request past what Groq accepts with nothing to catch
      it before the network call.

        STILL FAILING 2026-09-19 (UK's fresh monitor trace, SAME 413
        pattern, after this fix already shipped): the gap was that this
        function only trimmed by DROPPING WHOLE MESSAGES, oldest first,
        and always kept "at least the single most recent message even
        if it alone is large". If THAT one message -- e.g. a large
        chunk of existing code pasted in for a debug/edit request -- is
        itself what's oversized, dropping older messages around it does
        nothing; the one message that's actually too big still goes out
        whole. Fixed: any single message over its own per-message cap
        now gets its CONTENT truncated (head + tail, with a note in the
        middle), not just kept-or-dropped as a unit.

        Token estimate is chars/4 (no tokenizer available here) --
        deliberately conservative (overestimates on English, roughly
        right on Hinglish) so this errs toward trimming a bit early
        rather than still sending an oversized request.

        TIGHTENED 2026-09-20 (UK's Groq dashboard screenshots: real
        INPUT TOKENS sometimes landing around 6500 despite this
        function's 6000-token budget -- see the generate_with_tools
        call site below). chars/4 is a real underestimate for content
        that isn't plain English prose -- code (lots of short
        punctuation-heavy tokens), Hinglish/Devanagari, and JSON/tool-
        schema text (also sent as part of every tool-calling request,
        not counted here at all since this function only sees
        `messages`) can all tokenize to noticeably MORE than
        len(text)//4. Rather than guess at exact per-content-type
        ratios without a real tokenizer, the safety margin has been
        widened directly: the budget passed in by generate_with_tools
        was lowered (6000 -> 5200) to leave real headroom for both this
        under-count and the tool-schema tokens this function never
        sees, instead of pretending chars/4 is exact.
        """
        def _tokens(text: str) -> int:
            return max(1, len(text or "") // 4)

        def _msg_tokens(m: Dict[str, Any]) -> int:
            content = m.get("content")
            if isinstance(content, str):
                return _tokens(content)
            if isinstance(content, list):
                return sum(_tokens(str(part.get("text", ""))) for part in content if isinstance(part, dict))
            return _tokens(str(content))

        # PER-MESSAGE CAP (2026-09-19 fix). No single message should
        # eat more than a third of the whole budget -- a single pasted
        # file or long code block truncated to head+tail is far more
        # useful to the model than the SAME request failing outright
        # with a 413 and producing nothing at all.
        per_message_cap = max(500, max_tokens // 3)

        def _truncate_content(content: Any, cap_tokens: int) -> Any:
            if not isinstance(content, str):
                return content
            cap_chars = cap_tokens * 4
            if len(content) <= cap_chars:
                return content
            head = cap_chars * 2 // 3
            tail = cap_chars - head
            return (
                content[:head]
                + f"\n\n... [{len(content) - head - tail} characters truncated -- "
                  f"content too long to send whole] ...\n\n"
                + content[-tail:]
            )

        messages = [
            {**m, "content": _truncate_content(m.get("content"), per_message_cap)}
            if _msg_tokens(m) > per_message_cap else m
            for m in messages
        ]

        total = sum(_msg_tokens(m) for m in messages)
        if total <= max_tokens:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        system_tokens = sum(_msg_tokens(m) for m in system_msgs)
        remaining = max(0, max_tokens - system_tokens)

        # Keep the most recent turns first, working backward, until the
        # remaining budget runs out -- this is the sliding-window part.
        kept: list = []
        for m in reversed(other_msgs):
            cost = _msg_tokens(m)
            if cost > remaining and kept:
                # stop once adding another turn would overflow, but
                # always keep at least the single most recent message
                # even if it alone is large -- an empty conversation
                # history is worse than one oversized-but-recent turn
                break
            kept.append(m)
            remaining -= cost
        kept.reverse()

        dropped = len(other_msgs) - len(kept)
        if dropped > 0:
            log_event(
                "llm_bridge",
                f"trimmed {dropped} older message(s) from a tool-calling request to fit the token budget "
                f"(was ~{total} tokens, cap {max_tokens})",
                level="warning",
            )
        return system_msgs + kept

    def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        level: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:

        reserved_tokens = self._reserve_budget(
            max_tokens,
            level=level,
        )

        online = self._is_online()

        have_groq_key = bool(
            os.getenv("GROQ_API_KEYS")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("GROK_API_KEY")
        )

        if not (online and have_groq_key):

            self.last_backend = (
                "tools_unavailable_offline"
            )

            return None

        try:

            # IMPORTANT:
            # Tool calling deliberately stays directly on Groq.
            # It does NOT use Cerebras/Cloudflare provider routing.

            # SIZE-BOUNDED (2026-09-18, see _trim_messages_to_budget's
            # docstring for the full "413 Payload Too Large" story).
            # TIGHTENED 2026-09-20 (UK's Groq dashboard screenshots: real
            # INPUT TOKENS sometimes ~6500 despite this budget) -- 6000
            # was too close to the edge once the chars/4 estimate's real
            # under-count on code/Hinglish/tool-schema content is
            # accounted for. 5200 leaves real headroom for that
            # under-count instead of pretending the estimate is exact.
            bounded_messages = self._trim_messages_to_budget(messages, max_tokens=5200)

            message = self._get_groq().generate_with_tools(
                messages=bounded_messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=reserved_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
            )

            self.last_error = None
            self.is_ready = True
            self.last_backend = "groq_tools"

            return message

        except Exception as exc:

            self.last_error = str(exc)
            self.last_backend = "groq_tools_error"

            log_event(
                "llm_bridge",
                f"groq tool-call failed: {exc}",
                level="error",
            )

            return None

    # -----------------------------------------------------------------------
    # NORMAL LLM GENERATION
    # -----------------------------------------------------------------------
    #
    # Flow:
    #
    #   HybridLLMBridge
    #          |
    #          | reserve budget ONCE
    #          v
    #   CognitiveBudgeter
    #          |
    #          v
    #   LLMProviderEngine
    #          |
    #          +--> Groq ----> GroqEngine's existing key rotation
    #          |
    #          +--> Cerebras -> per-key balancing
    #          |
    #          +--> Cloudflare -> per-key balancing
    #          |
    #          v
    #      result/failover
    #          |
    #          v
    #   Local GGUF final fallback
    #
    # Provider failover NEVER calls _reserve_budget() again.
    # -----------------------------------------------------------------------

    def generate_response(
        self,
        system_prompt: str,
        user_input: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        level: Optional[str] = None,
        **kwargs,
    ) -> str:

        # TOKEN LEDGER PURPOSE TAG (2026-09-21, UK's explicit spec:
        # "kaun sa portion kitna token khaa raha uska individual track").
        # Optional -- every existing caller keeps working unchanged and
        # gets logged as "chat" (token_management.py's own default);
        # callers that DO know why they're calling (run_capability_worker,
        # a coding run, etc.) can pass purpose="..." for a real per-
        # purpose breakdown instead of everything landing in one bucket.
        purpose = kwargs.pop("purpose", None)
        if purpose:
            try:
                self._get_groq()._current_call_purpose = purpose
            except Exception:
                pass

        # ---------------------------------------------------------------
        # EXISTING TURN BUDGET — ONE RESERVATION ONLY
        # ---------------------------------------------------------------

        reserved_tokens = self._reserve_budget(
            max_tokens,
            level=level,
        )

        online = self._is_online()

        # ---------------------------------------------------------------
        # Any configured cloud provider counts as a usable cloud backend.
        #
        # FIXED 2026-09-17 (UK's spec + runtime log: "[LLM unavailable:
        # local fallback is disabled]" firing on almost every coding-
        # agent/codebox call, while ordinary chat mostly worked). This
        # check only ever looked for GROQ_API_KEY (singular). Every
        # actual key-loading path in this codebase -- GroqEngine's own
        # constructor, the 10-key rotation, the RPM/balance work done
        # this session -- reads GROQ_API_KEYS (PLURAL, comma-separated)
        # as the primary variable. With only the plural var set (the
        # documented, intended setup for 10 keys), this flag was False,
        # so the entire cloud branch below was skipped and every call
        # fell through to the local model -- which then hit its own
        # tiny context window and, with local fallback disabled by
        # design, returned the degraded sentinel. Groq was never
        # actually being tried for those calls; nothing about payload
        # size or the provider itself was ever the problem.
        # ---------------------------------------------------------------

        # GROQ-ONLY (2026-09-20, UK: "llm_provider_engine me bas grok
        # engine rahe" -- Cerebras/Cloudflare engines were removed from
        # llm_provider_engine.py entirely this pass). This check used to
        # also treat a bare CEREBRAS_*/CLOUDFLARE_* env var as "a cloud
        # provider is available" -- now misleading, since neither engine
        # exists to actually serve a call anymore; only a real Groq key
        # means cloud is actually reachable.
        have_cloud_provider = bool(
            os.getenv("GROQ_API_KEYS")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("GROK_API_KEY")
        )

        # ---------------------------------------------------------------
        # CONTEXT BUDGETER -- provider-aware (fixed 2026-09-17, same
        # runtime-log evidence). self._context_budgeter is sized for the
        # LOCAL model's tiny n_ctx (often 2048). Previously EVERY call
        # was bounded by it before the cloud/local routing decision even
        # happened, so a cloud-bound call with max_tokens=2000 (codebox's
        # own default) got its prompt clamped down to almost nothing by
        # a window meant for the local model, not because Groq's actual,
        # much larger context was full. Cloud calls now use a separate,
        # realistically-sized budgeter; only calls that are actually
        # going to the local model use the small one.
        # ---------------------------------------------------------------

        active_budgeter = (
            self._cloud_context_budgeter
            if (online and have_cloud_provider)
            else self._context_budgeter
        )

        bounded_system, bounded_user = (
            active_budgeter.optimize_payload(
                system_prompt,
                user_input,
                max_tokens=reserved_tokens,
            )
        )

        # ---------------------------------------------------------------
        # EXISTING LOCAL FALLBACK POLICY — UNCHANGED
        # ---------------------------------------------------------------

        allow_local_fallback = (
            self._force_mode == "offline"
            or os.getenv(
                "JARVIS_ALLOW_LOCAL_FALLBACK",
                "false",
            ).strip().lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )

        heavy_local_opt_in = (
            os.getenv(
                "JARVIS_ENABLE_HEAVY_LOCAL_MODEL",
                "false",
            ).strip().lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )

        allow_local_fallback = (
            allow_local_fallback
            and (
                self._force_mode == "offline"
                or heavy_local_opt_in
            )
        )

        # ---------------------------------------------------------------
        # CLOUD PROVIDER ROUTER
        # ---------------------------------------------------------------

        if online and have_cloud_provider:

            try:

                provider_engine = (
                    self._get_provider_engine()
                )

                result = provider_engine.generate(
                    system_prompt=bounded_system,
                    user_input=bounded_user,
                    max_tokens=reserved_tokens,
                    temperature=temperature,
                    response_format=kwargs.get(
                        "response_format"
                    ),
                    reasoning_effort=kwargs.get(
                        "reasoning_effort"
                    ),
                )

                # Expose the actual live provider/key quota state.
                self._publish_llm_provider_quota()

                self.last_error = None
                self.is_ready = True

                # Provider engine exposes the actual provider that finally
                # produced the response.
                self.last_backend = (
                    getattr(
                        provider_engine,
                        "last_provider",
                        "cloud",
                    )
                    or "cloud"
                )

                return result

            except Exception as exc:

                # Preserve quota/failure telemetry even when every
                # cloud provider attempt fails.
                self._publish_llm_provider_quota()

                self.last_error = str(exc)

                provider_name = "cloud_error"

                if self._provider_engine is not None:

                    provider_name = (
                        getattr(
                            self._provider_engine,
                            "last_provider",
                            None,
                        )
                        or "cloud_error"
                    )

                self.last_backend = provider_name

                log_event(
                    "llm_bridge",
                    f"cloud provider engine failed: {exc}",
                    level="error",
                )

                # IMPORTANT:
                # Provider engine has already attempted its configured
                # providers/keys. We do NOT retry through another
                # _reserve_budget() call here.
                #
                # If local fallback is disabled, return degraded result.
                if not allow_local_fallback:

                    self.is_ready = False

                    return (
                        "[LLM unavailable: cloud providers "
                        "failed; local fallback is disabled]"
                    )

        # ---------------------------------------------------------------
        # FINAL LOCAL FALLBACK
        # ---------------------------------------------------------------

        if not allow_local_fallback:

            self.last_backend = "blocked"
            self.is_ready = False

            self.last_error = (
                self.last_error
                or "No usable online LLM backend"
            )

            return (
                "[LLM unavailable: local fallback "
                "is disabled]"
            )

        try:

            result = self._get_local().generate(
                system_prompt=bounded_system,
                user_input=bounded_user,
                max_tokens=reserved_tokens,
                temperature=temperature,
            )

            self.last_error = None
            self.is_ready = True
            self.last_backend = "local"

            return result

        except Exception as exc:

            self.last_error = str(exc)
            self.last_backend = "local_error"
            self.is_ready = False

            return (
                f"[Model Generation Error: {exc}]"
            )


LlamaCppBridge = HybridLLMBridge


def can_afford_another_llm_call(
    llm_bridge: Any,
    min_calls_remaining_after: int = 1,
) -> bool:

    """
    Shared budget-awareness guard.

    No retry mechanism may greedily spend the whole shared per-turn
    budget on itself.

    Provider-level failover does NOT call this function because provider
    failover is part of ONE logical LLM generation call and does not
    reserve additional cognitive-turn budget.
    """

    budget_status = getattr(
        llm_bridge,
        "budget_status",
        None,
    )

    if not callable(budget_status):
        return True

    try:
        status = budget_status()
    except Exception:
        return True

    remaining_calls = status.get(
        "remaining_calls"
    )

    if remaining_calls is None:
        return True

    return (
        remaining_calls
        > min_calls_remaining_after
    )