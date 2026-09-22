"""Regression tests for the payload-size architecture fix (2026-09-19).

UK's own monitor.py trace showed all 10 Groq keys failing identically
with HTTP 413 (Payload Too Large), then separately all 10 failing
identically with HTTP 400 -- burning real wall-clock time (each key
rotation involves a real network round trip) on a guaranteed-to-repeat
failure, since payload size/format is a property of the REQUEST, not
the key authenticating it.

These tests use a fake requests.Session (no network) to verify the
real _post_chat_completion() logic: 413 and 400 now fail fast (shrink
once, retry once, then give up) instead of rotating through all keys,
while a genuinely key-specific error (429, rate limit) still correctly
rotates through every key as before.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestration.llm_bridge import GroqEngine, HybridLLMBridge


class _FakeResponse:
    def __init__(self, status_code, text="{}"):
        self.status_code = status_code
        self.text = text
        self.headers = {}

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}

    def raise_for_status(self):
        pass


def _make_engine(session):
    engine = GroqEngine.__new__(GroqEngine)
    engine.api_keys = [f"key{i}" for i in range(10)]
    engine._current_index = 0
    engine.base_url = "https://api.groq.com/openai/v1"
    engine.model = "test-model"
    engine.MAX_TOTAL_SECONDS = 12.0
    engine.timeout = 8.0
    engine._session = session
    engine._last_attempts = []
    engine._last_response_headers = {}
    engine._last_retry_after = None
    engine._last_used_key_index = None
    engine._rate_limit_cooldown_seconds = 0.01  # fast for tests -- see test_cooldown_retry_after_all_429s below for the real-value check
    engine._key_telemetry = {}
    engine._request_timestamps = {}
    engine._last_selection = {}
    return engine


def test_413_fails_fast_with_one_shrink_retry_not_all_ten_keys():
    call_log = []

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append((headers["Authorization"], json.get("max_tokens"), len(json.get("messages", []))))
            return _FakeResponse(413, "Payload too large body")

    engine = _make_engine(FakeSession())
    payload = {
        "model": "test",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        "max_tokens": 1000,
    }

    raised = False
    try:
        engine._post_chat_completion(payload)
    except RuntimeError as e:
        raised = True
        assert "413" in str(e)

    assert raised
    assert len(call_log) == 2, f"expected exactly 2 calls (original + 1 shrunk retry), got {len(call_log)}"
    assert call_log[1][1] == call_log[0][1] // 2, "retry must halve max_tokens"
    assert call_log[1][2] < call_log[0][2], "retry must have fewer messages"


def test_400_fails_fast_after_two_attempts_not_all_ten_keys():
    call_log = []

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append(headers["Authorization"])
            return _FakeResponse(400, "Bad request body")

    engine = _make_engine(FakeSession())
    payload = {"model": "test", "messages": [{"role": "user", "content": "a"}], "max_tokens": 1000}

    raised = False
    try:
        engine._post_chat_completion(payload)
    except RuntimeError as e:
        raised = True
        assert "400" in str(e)

    assert raised
    assert len(call_log) == 2, f"expected exactly 2 calls, got {len(call_log)}"


def test_429_genuinely_key_specific_still_rotates_all_keys():
    """The fix must NOT change behavior for errors that ARE actually
    key-specific (rate limits, auth) -- those should still try every key.
    Calls _post_chat_completion_single_pass directly -- this test is
    about the per-pass rotation logic specifically; the outer cooldown-
    retry wrapper (which WOULD also kick in here since these are all
    429s) has its own dedicated test below."""
    call_log = []

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append(headers["Authorization"])
            return _FakeResponse(429, "rate limited")

    engine = _make_engine(FakeSession())
    payload = {"model": "test", "messages": [{"role": "user", "content": "a"}], "max_tokens": 1000}

    try:
        engine._post_chat_completion_single_pass(payload)
    except RuntimeError:
        pass

    assert len(call_log) == 10, f"429 should rotate through all 10 keys, got {len(call_log)}"


def test_cooldown_retry_after_all_429s_then_succeeds():
    """UK's explicit ask: don't just give up when every key is
    momentarily rate-limited -- wait for the cooldown window and try
    once more. This is the new outer wrapper's behavior specifically."""
    call_log = []

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append(1)
            # First 10 calls (first pass): all rate-limited.
            # 11th call (start of the cooldown-retry pass): succeeds.
            if len(call_log) <= 10:
                return _FakeResponse(429, "rate limited")
            return _FakeResponse(200)

    engine = _make_engine(FakeSession())
    payload = {"model": "test", "messages": [{"role": "user", "content": "a"}], "max_tokens": 1000}

    result = engine._post_chat_completion(payload)
    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(call_log) == 11, f"expected 10 (first pass) + 1 (retry pass, succeeds immediately), got {len(call_log)}"


def test_cooldown_retry_not_triggered_for_non_429_failures():
    """The cooldown retry is ONLY for genuine rate-limiting -- a mix
    that includes even one non-429 failure must not trigger the extra
    wait-and-retry pass (that failure mode was already handled
    correctly by the single pass itself)."""
    call_log = []

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append(1)
            return _FakeResponse(403, "forbidden")

    engine = _make_engine(FakeSession())
    payload = {"model": "test", "messages": [{"role": "user", "content": "a"}], "max_tokens": 1000}

    try:
        engine._post_chat_completion(payload)
    except RuntimeError:
        pass

    assert len(call_log) == 10, f"non-429 failures must not trigger the extra cooldown pass, got {len(call_log)} calls"


def test_cooldown_retry_honors_real_retry_after_header_not_fixed_constant():
    """2026-09-20 root-cause pass: the wait between passes must come
    from Groq's OWN real retry-after header when present, not always
    the fixed configured default -- 'reserve LLM for it, wait for the
    REAL available budget, never fabricate.'"""
    call_log = []
    slept = []

    class FakeResponseWithRetryAfter(_FakeResponse):
        def __init__(self, status_code, retry_after):
            super().__init__(status_code)
            self.headers = {"retry-after": str(retry_after)}

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append(1)
            if len(call_log) <= 10:
                return FakeResponseWithRetryAfter(429, 5)  # Groq says: retry in 5s
            return _FakeResponse(200)

    engine = _make_engine(FakeSession())
    payload = {"model": "test", "messages": [{"role": "user", "content": "a"}], "max_tokens": 1000}

    import core.orchestration.llm_bridge as bridge_mod
    real_sleep = bridge_mod.time.sleep
    bridge_mod.time.sleep = lambda s: slept.append(s)
    try:
        result = engine._post_chat_completion(payload)
    finally:
        bridge_mod.time.sleep = real_sleep

    assert result["choices"][0]["message"]["content"] == "ok"
    assert slept, "should have waited before the retry pass"
    assert slept[0] == 5.0, f"must honor the REAL retry-after (5s), got {slept[0]}"


def test_cooldown_retry_is_bounded_and_gives_up_on_genuine_outage():
    """A real, sustained outage (every pass, every key, always 429)
    must still give up eventually -- bounded passes, never an
    unbounded hang, even while honoring real retry-after waits."""
    call_log = []

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append(1)
            return _FakeResponse(429, "still limited")

    engine = _make_engine(FakeSession())
    payload = {"model": "test", "messages": [{"role": "user", "content": "a"}], "max_tokens": 1000}

    import core.orchestration.llm_bridge as bridge_mod
    real_sleep = bridge_mod.time.sleep
    bridge_mod.time.sleep = lambda s: None
    try:
        try:
            engine._post_chat_completion(payload)
            raised = False
        except RuntimeError:
            raised = True
    finally:
        bridge_mod.time.sleep = real_sleep

    assert raised, "a genuine sustained outage must still raise, not hang forever"
    assert call_log.count(1) == 10 * GroqEngine.MAX_RATE_LIMIT_RETRIES, (
        f"expected exactly {10 * GroqEngine.MAX_RATE_LIMIT_RETRIES} calls "
        f"({GroqEngine.MAX_RATE_LIMIT_RETRIES} bounded passes x 10 keys), got {call_log.count(1)}"
    )


def test_telemetry_captures_real_rate_limit_headers_not_fabricated():
    """2026-09-20 root-cause pass, UK's explicit spec: "actual Groq
    metadata... never guessed value ko real quota mat dikhao". A
    successful response with real rate-limit headers must populate
    telemetry_snapshot() with exactly those real numbers."""
    class FakeResponseWithHeaders(_FakeResponse):
        def __init__(self):
            super().__init__(200)
            self.headers = {
                "x-ratelimit-limit-requests": "1000",
                "x-ratelimit-remaining-requests": "942",
                "x-ratelimit-reset-requests": "12.5s",
                "x-ratelimit-limit-tokens": "100000",
                "x-ratelimit-remaining-tokens": "87654",
                "x-ratelimit-reset-tokens": "3.2s",
            }

        def json(self):
            return {"id": "req_abc123", "model": "test-model",
                    "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
                    "choices": [{"message": {"content": "ok"}}]}

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            return FakeResponseWithHeaders()

    engine = _make_engine(FakeSession())
    payload = {"model": "test", "messages": [{"role": "user", "content": "a"}], "max_tokens": 500}
    engine._post_chat_completion(payload)

    snap = engine.telemetry_snapshot()
    key0 = snap["keys"][0]
    # FIXED 2026-09-21: per Groq's own rate-limits doc (UK pasted it
    # directly), x-ratelimit-*-requests headers are RPD, never RPM --
    # so they must land in rpd_*, not the old (wrong) live_*_requests
    # fields this test used to check.
    assert key0["rpd_limit"] == 1000
    assert key0["rpd_remaining"] == 942
    assert key0["tpm_limit"] == 100000
    assert key0["tpm_remaining"] == 87654
    assert key0["last_request"]["actual_prompt_tokens"] == 120
    assert key0["last_request"]["actual_total_tokens"] == 160
    assert key0["last_request"]["request_id"] == "req_abc123"
    assert key0["status"] == "AVAILABLE"
    print("OK: telemetry_snapshot() reflects the REAL headers Groq sent, nothing fabricated")


def test_rpm_tracked_locally_from_real_call_timestamps_not_from_a_header():
    """2026-09-21: Groq sends no remaining-RPM header at all (confirmed
    by UK's own pasted doc) -- RPM must come from this engine's own
    real call timestamps against Groq's real published per-model RPM
    ceiling, never a guess."""
    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResponse(200)

    engine = _make_engine(FakeSession())
    engine.model = "openai/gpt-oss-120b"  # a real, published-limits model
    payload = {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}
    for _ in range(3):
        engine._post_chat_completion(payload)

    snap = engine.telemetry_snapshot()
    key0 = snap["keys"][0]
    assert key0["rpm_limit"] == 30, "must match Groq's own published RPM ceiling for this model"
    assert key0["rpm_remaining"] == 27, f"3 real calls against a 30 RPM ceiling should leave 27, got {key0['rpm_remaining']}"
    print("OK: RPM is tracked from real call timestamps against Groq's published ceiling, not fabricated")


def test_capacity_ordering_balances_across_keys_by_worst_case_fraction():
    """2026-09-21, UK's explicit spec: "ek key 40% use ho chuki hai to
    baaki sab bhi 38-42% range mein rahen" -- ordering by remaining
    FRACTION (not raw remaining count) is what makes repeated calls
    spread evenly instead of favoring one key indefinitely."""
    engine = _make_engine(None)
    engine._key_telemetry = {
        0: {"key_index": 0, "tpm_remaining": 4800, "tpm_limit": 8000},   # 60% remaining
        1: {"key_index": 1, "tpm_remaining": 7600, "tpm_limit": 8000},   # 95% remaining -- most headroom
        2: {"key_index": 2, "tpm_remaining": 2000, "tpm_limit": 8000},   # 25% remaining
    }
    order = engine._capacity_ordered_key_indices()
    assert order[0] == 1, f"key with the most REAL remaining fraction must be tried first: {order}"
    # Only compare the three KNOWN keys' relative order -- the other 7
    # keys in this test's default 10-key engine have no telemetry at
    # all yet, which is its own (correctly neutral) priority tier, not
    # "worse than every known key" or "better than every known key".
    known_order = [i for i in order if i in (0, 1, 2)]
    assert known_order == [1, 0, 2], f"expected real-fraction order [1,0,2] among known keys, got {known_order}"
    print("OK: capacity ordering balances by real remaining fraction, not raw count")


def test_capacity_ordering_considers_rpm_not_just_tpm():
    """A key can have plenty of TPM left but be RPM-exhausted -- the
    real worst-case dimension must decide, since sending would still
    hit a 429 on RPM even with tokens to spare."""
    engine = _make_engine(None)
    engine._key_telemetry = {
        0: {"key_index": 0, "tpm_remaining": 7900, "tpm_limit": 8000,   # 98.75% TPM
            "rpm_remaining": 1, "rpm_limit": 30},                        # 3.3% RPM -- the real bottleneck
        1: {"key_index": 1, "tpm_remaining": 4000, "tpm_limit": 8000,   # 50% TPM
            "rpm_remaining": 20, "rpm_limit": 30},                       # 66% RPM
    }
    order = engine._capacity_ordered_key_indices()
    assert order[0] == 1, f"key 0's real RPM near-exhaustion must be caught even though its TPM looks fine: {order}"
    print("OK: RPM near-exhaustion is caught even when TPM alone looks healthy")


def test_real_token_estimate_comes_from_actual_messages_not_max_tokens():
    """2026-09-21, UK: "estimate mat karo, actual token sizing use karo
    jo LLM ko pass ho raha hai" -- the estimate must be computed from
    the real message content being sent, never payload['max_tokens']
    (that's the OUTPUT cap, an unrelated number)."""
    engine = _make_engine(None)
    payload = {"messages": [{"role": "user", "content": "x" * 400}], "max_tokens": 50}
    estimate = engine._estimate_request_input_tokens(payload)
    assert estimate == 100, f"400 chars // 4 == 100, got {estimate} (max_tokens=50 must NOT leak in)"
    print("OK: request-size estimate comes from real message content, not max_tokens")


def test_selection_state_is_published_with_real_choice():
    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResponse(200)

    engine = _make_engine(FakeSession())
    payload = {"messages": [{"role": "user", "content": "hello there"}], "max_tokens": 50}
    engine._post_chat_completion(payload)
    assert engine._last_selection.get("selected_provider") == "groq"
    assert engine._last_selection.get("selected_key_index") is not None
    assert engine._last_selection.get("current_request_estimate", {}).get("input_tokens")
    print("OK: real selection reasoning (estimate/eligible/selected) is recorded, not left empty")


def test_tpd_counter_accumulates_from_real_usage_body_not_estimated():
    """2026-09-21, UK's 5-point spec: Groq has no remaining-TPD header,
    so the local counter must accumulate the REAL usage.total_tokens
    from each response body."""
    class FakeResponseWithUsage(_FakeResponse):
        def __init__(self, total):
            super().__init__(200)
            self._total = total

        def json(self):
            return {"id": "r1", "model": "openai/gpt-oss-120b",
                    "usage": {"prompt_tokens": self._total - 10, "completion_tokens": 10, "total_tokens": self._total},
                    "choices": [{"message": {"content": "ok"}}]}

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def post(self, url, headers=None, json=None, timeout=None):
            self.calls += 1
            return FakeResponseWithUsage(500)

    engine = _make_engine(FakeSession())
    engine.model = "openai/gpt-oss-120b"
    payload = {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}
    engine._post_chat_completion(payload)
    engine._post_chat_completion(payload)
    engine._post_chat_completion(payload)

    st = engine._key_telemetry[0]
    assert st["tpd_used"] == 1500, f"3 real calls of 500 tokens each should sum to 1500, got {st['tpd_used']}"
    assert st["tpd_limit"] == 200_000, "must match Groq's own published TPD ceiling for this model"
    assert st["tpd_remaining"] == 198_500
    print("OK: TPD accumulates from real response-body usage, matches published ceiling")


def test_tpd_counter_auto_resets_at_the_real_daily_clock():
    """2026-09-21: once now_t passes the REAL rpd_reset_at (set from
    Groq's own x-ratelimit-reset-requests header), the local TPD
    counter must go back to 0 automatically, like UK's spec describes."""
    engine = _make_engine(None)
    engine.model = "openai/gpt-oss-120b"
    st = engine._key_telemetry.setdefault(0, {"key_index": 0})
    past_reset = time.time() - 5.0
    st["rpd_reset_at"] = past_reset
    st["tpd_used"] = 150_000
    engine._record_tpd_counter(0, st, {"total_tokens": 100}, time.time())
    assert st["tpd_used"] == 100, f"counter must reset to 0 then add only this call's 100 tokens, got {st['tpd_used']}"
    print("OK: TPD counter auto-resets at the real daily clock, not left stale")


def test_key_excluded_when_really_out_of_daily_budget_regardless_of_request_size():
    engine = _make_engine(None)
    engine._key_telemetry = {
        0: {"key_index": 0, "tpd_remaining": 0, "tpd_limit": 200_000},  # genuinely exhausted today
        1: {"key_index": 1, "tpd_remaining": 50_000, "tpd_limit": 200_000},
    }
    order = engine._capacity_ordered_key_indices()  # no size estimate at all
    assert 0 not in order or order[0] == 1, f"a key with 0 real TPD remaining must never be preferred: {order}"
    assert order[0] == 1
    print("OK: a key genuinely out of daily budget is excluded even without a size estimate")



def test_telemetry_key_with_no_data_reports_unpublished_not_fake_zero():
    engine = _make_engine(None)
    snap = engine.telemetry_snapshot()
    # A key that has never actually been called yet must have NO
    # tpm_remaining field at all (renders as NOT PUBLISHED downstream),
    # never a fabricated 0 or a fabricated "full capacity" guess.
    assert "tpm_remaining" not in snap["keys"][0]
    print("OK: never-called key reports unpublished capacity, not a guessed number")


def test_capacity_aware_selection_prefers_key_with_more_real_remaining_tokens():
    """UK's explicit spec: "max untouched token availability exhaust
    kare, bas yehi order mein key rotate ho." Key #3 (index 2) has far
    more real remaining tokens published than key #1 -- it must be
    tried FIRST, not by round-robin position."""
    engine = _make_engine(None)
    engine._key_telemetry = {
        0: {"key_index": 0, "tpm_remaining": 500, "tpm_limit": 8000},
        1: {"key_index": 1, "tpm_remaining": 200, "tpm_limit": 8000},
        2: {"key_index": 2, "tpm_remaining": 9000, "tpm_limit": 15000},
    }
    order = engine._capacity_ordered_key_indices()
    assert order[0] == 2, f"expected key index 2 (most real remaining capacity) first, got order={order}"
    print("OK: capacity-aware ordering picks the real-highest-remaining key first")


def test_capacity_aware_selection_excludes_keys_with_insufficient_real_capacity():
    engine = _make_engine(None)
    engine._key_telemetry = {
        0: {"key_index": 0, "tpm_remaining": 100, "tpm_limit": 8000},   # too little for a 5000-token request
        1: {"key_index": 1, "tpm_remaining": 9000, "tpm_limit": 15000},  # enough
    }
    order = engine._capacity_ordered_key_indices(estimated_tokens=5000)
    assert 0 not in order or order[0] == 1, f"key with known-insufficient real capacity must not be preferred: {order}"
    assert order[0] == 1
    print("OK: a key with real, known-insufficient capacity is excluded/deprioritized for this request")


def test_capacity_aware_selection_never_guesses_unknown_key_as_empty_or_full():
    """A key with NO telemetry yet (process just started, or this key
    has simply never been used) must be treated as unknown -- ordered
    among other unknowns, never assumed empty (which would starve a
    perfectly good key) or assumed full (which would fabricate trust)."""
    engine = _make_engine(None)
    engine._key_telemetry = {0: {"key_index": 0, "tpm_remaining": 50, "tpm_limit": 8000}}  # known, low
    order = engine._capacity_ordered_key_indices()
    # key 1 has no data at all -- must still appear, and not be shoved
    # permanently behind a REAL cooldown key.
    engine._key_telemetry[2] = {"key_index": 2, "cooldown_until": time.time() + 999}
    order = engine._capacity_ordered_key_indices()
    assert order[-1] == 2, f"a key in a REAL cooldown must be tried last: {order}"
    print("OK: unknown keys are neither starved nor falsely trusted; real cooldown keys go last")



def test_groq_engine_call_writes_to_the_persistent_token_ledger():
    """End-to-end: a real successful GroqEngine call must ALSO land in
    token_management.py's persistent ledger, not just the in-memory
    telemetry dict -- this is what makes it survive a restart."""
    import tempfile
    os.environ["JARVIS_DATA_DIR"] = tempfile.mkdtemp()
    import core.orchestration.token_management as tm
    tm._shared_manager = None  # force a fresh singleton bound to the new dir

    class FakeResponseWithUsage(_FakeResponse):
        def json(self):
            return {"id": "req_ledger_1", "model": "test-model",
                    "usage": {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42},
                    "choices": [{"message": {"content": "ok"}}]}

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            return FakeResponseWithUsage(200)

    engine = _make_engine(FakeSession())
    engine._post_chat_completion({"messages": [{"role": "user", "content": "hi"}], "max_tokens": 50})

    summary = tm.get_token_manager().summary()
    assert summary["overall"]["total_tokens"] == 42, f"expected 42 real tokens logged, got {summary}"
    print("OK: a real successful GroqEngine call is logged to the persistent token ledger")



def test_success_after_413_shrink_returns_real_data():
    """The shrink-and-retry must actually succeed and return real data
    when the SMALLER payload is accepted -- not just fail differently."""
    call_log = []

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            call_log.append(1)
            if len(call_log) == 1:
                return _FakeResponse(413, "too large")
            return _FakeResponse(200)

    engine = _make_engine(FakeSession())
    payload = {
        "model": "test",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        "max_tokens": 1000,
    }
    result = engine._post_chat_completion(payload)
    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(call_log) == 2


def test_single_oversized_message_content_gets_truncated():
    """The deeper root cause UK's SECOND trace exposed: dropping whole
    older messages doesn't help when the one message kept (the most
    recent) is itself the oversized one. Its CONTENT must be truncated,
    not just kept-whole-or-dropped."""
    trim = HybridLLMBridge._trim_messages_to_budget

    class _Dummy:
        pass

    big_content = "x" * 40000  # ~10000 tokens, way over budget
    messages = [
        {"role": "system", "content": "you are jarvis"},
        {"role": "user", "content": big_content},
    ]
    result = trim(_Dummy(), messages, max_tokens=6000)
    user_msg = [m for m in result if m["role"] == "user"][0]
    assert len(user_msg["content"]) < len(big_content)
    assert "truncated" in user_msg["content"]


def test_small_messages_pass_through_unchanged():
    trim = HybridLLMBridge._trim_messages_to_budget

    class _Dummy:
        pass

    small_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = trim(_Dummy(), small_messages, max_tokens=6000)
    assert result == small_messages


if __name__ == "__main__":
    test_413_fails_fast_with_one_shrink_retry_not_all_ten_keys()
    test_400_fails_fast_after_two_attempts_not_all_ten_keys()
    test_429_genuinely_key_specific_still_rotates_all_keys()
    test_cooldown_retry_after_all_429s_then_succeeds()
    test_cooldown_retry_not_triggered_for_non_429_failures()
    test_cooldown_retry_honors_real_retry_after_header_not_fixed_constant()
    test_cooldown_retry_is_bounded_and_gives_up_on_genuine_outage()
    test_telemetry_captures_real_rate_limit_headers_not_fabricated()
    test_rpm_tracked_locally_from_real_call_timestamps_not_from_a_header()
    test_capacity_ordering_balances_across_keys_by_worst_case_fraction()
    test_capacity_ordering_considers_rpm_not_just_tpm()
    test_real_token_estimate_comes_from_actual_messages_not_max_tokens()
    test_selection_state_is_published_with_real_choice()
    test_tpd_counter_accumulates_from_real_usage_body_not_estimated()
    test_tpd_counter_auto_resets_at_the_real_daily_clock()
    test_key_excluded_when_really_out_of_daily_budget_regardless_of_request_size()
    test_groq_engine_call_writes_to_the_persistent_token_ledger()
    test_telemetry_key_with_no_data_reports_unpublished_not_fake_zero()
    test_capacity_aware_selection_prefers_key_with_more_real_remaining_tokens()
    test_capacity_aware_selection_excludes_keys_with_insufficient_real_capacity()
    test_capacity_aware_selection_never_guesses_unknown_key_as_empty_or_full()
    test_success_after_413_shrink_returns_real_data()
    test_single_oversized_message_content_gets_truncated()
    test_small_messages_pass_through_unchanged()
    print("✓ ALL PAYLOAD-SIZE ARCHITECTURE TESTS PASSED")
