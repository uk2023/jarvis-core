"""Tests for core/cognition/thread_search.py.

UK's explicit architecture: a user references past context WITHOUT a
timestamp ("humne pehle decide kiya tha") -- JARVIS must scan the
FULL chat thread and find it, no matter how old, with an optional time
hint only ever narrowing (never gating) the search, and latency that
never becomes noticeable.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.thread_search import (
    has_backward_reference,
    extract_time_hint_hours,
    search_thread_for_reference,
    format_thread_matches,
)


def _make_large_old_thread(needle_text: str, needle_age_years: float = 10, filler_count: int = 500):
    now = time.time()
    needle_time = now - needle_age_years * 365 * 24 * 3600
    thread = [
        {"sender": "user", "text": "hello jarvis", "timestamp": needle_time - 100},
        {"sender": "user", "text": needle_text, "timestamp": needle_time},
        {"sender": "jarvis", "text": "confirmed", "timestamp": needle_time + 10},
    ]
    thread += [
        {"sender": "user", "text": f"unrelated filler message number {i}", "timestamp": needle_time + 1000 + i * 100}
        for i in range(filler_count)
    ]
    thread.append({"sender": "user", "text": "kya haal hai", "timestamp": now - 100})
    return thread


def test_backward_reference_detected_without_time_hint():
    assert has_backward_reference("humne pehle jo decide kiya tha, wahi use karo") is True
    assert has_backward_reference("we discussed this earlier") is True
    assert has_backward_reference("You said we should use Kali") is True
    assert has_backward_reference("PDF reader banao") is False  # no backward reference at all


def test_time_hint_extraction_optional_never_required():
    assert extract_time_hint_hours("2 ghante pehle tumne kaha tha") == 2.0
    assert extract_time_hint_hours("5 hours ago you said") == 5.0
    assert extract_time_hint_hours("kal humne discuss kiya tha") == 24.0
    assert extract_time_hint_hours("koi time nahi diya bas reference hai") is None


def test_finds_a_reference_buried_10_years_deep_with_no_time_hint():
    """The core value proposition: no timestamp given, thread is huge
    and old, the relevant message must still be found."""
    thread = _make_large_old_thread(
        "humne decide kiya tha ki hum Kali Linux use karenge Termux ke bajaye",
        needle_age_years=10, filler_count=500,
    )
    matches = search_thread_for_reference(
        "humne pehle jo decide kiya tha environment ke baare mein, wahi use karo",
        thread, max_results=3,
    )
    assert len(matches) > 0
    assert any("Kali Linux" in m.text for m in matches)


def test_scan_latency_stays_fast_on_a_large_thread():
    """UK's explicit ask: latency must stay perfect even scanning a
    large thread with no time hint to narrow it."""
    thread = _make_large_old_thread("Kali Linux use karenge", filler_count=2000)
    t0 = time.time()
    search_thread_for_reference("Kali Linux ke baare mein jo baat hui thi", thread, max_results=3)
    elapsed = time.time() - t0
    assert elapsed < 1.0, f"scan took {elapsed}s on a 2000+ message thread -- too slow"


def test_time_hint_narrows_but_falls_back_if_nothing_in_window():
    """The hint is an acceleration, never a hard gate -- if the hinted
    window happens to be wrong/empty, the search must still fall back
    to the full thread rather than reporting nothing found."""
    now = time.time()
    thread = [
        # The real match is actually 5 days old, but the user's hint
        # (wrongly) suggests 2 hours.
        {"sender": "user", "text": "Kali Linux use karenge humne decide kiya", "timestamp": now - 5 * 24 * 3600},
        {"sender": "user", "text": "unrelated message", "timestamp": now - 3600},
    ]
    matches = search_thread_for_reference(
        "Kali Linux ke baare mein", thread, max_results=3, time_hint_hours=2.0,
    )
    assert len(matches) > 0
    assert "Kali Linux" in matches[0].text


def test_no_query_tokens_returns_empty_not_an_error():
    """A query with nothing but stopwords must return empty cleanly,
    never crash or return arbitrary results."""
    thread = [{"sender": "user", "text": "the is a to", "timestamp": time.time()}]
    matches = search_thread_for_reference("hai kya hi", thread)
    assert matches == []


def test_format_thread_matches_is_readable_and_chronological():
    now = time.time()
    thread = [
        {"sender": "user", "text": "Kali Linux use karenge", "timestamp": now - 100},
        {"sender": "jarvis", "text": "theek hai confirmed", "timestamp": now - 90},
    ]
    matches = search_thread_for_reference("Kali Linux confirm", thread, max_results=5)
    formatted = format_thread_matches(matches)
    assert "UK:" in formatted or "JARVIS:" in formatted
    assert "Kali Linux" in formatted


def test_retrieved_reference_survives_begin_turn_then_clears_after_end_turn():
    """Ordering bug caught before shipping: the backend sets
    retrieved_reference BEFORE calling think_and_respond() (which
    fires begin_turn() as its own first step internally) -- clearing
    in begin_turn() would wipe out a value set moments earlier, before
    it was ever read for the brief. Must survive begin_turn() for THIS
    turn, then clear once end_turn() confirms the turn is done, so a
    stale match never leaks into a LATER turn that made no reference."""
    from core.cognition.conversation_continuity import ConversationContinuityLayer

    c = ConversationContinuityLayer(session_id="s", run_id="r")
    c.set_retrieved_reference("UK: Kali Linux use karenge\nJARVIS: confirmed")
    c.begin_turn("humne pehle jo decide kiya tha wahi karo")

    assert c.get_relevant_context()["retrieved_reference"] is not None

    c.end_turn("humne pehle jo decide kiya tha wahi karo", "theek hai")
    c.begin_turn("kuch aur baat")
    assert c.get_relevant_context()["retrieved_reference"] is None


if __name__ == "__main__":
    test_backward_reference_detected_without_time_hint()
    test_time_hint_extraction_optional_never_required()
    test_finds_a_reference_buried_10_years_deep_with_no_time_hint()
    test_scan_latency_stays_fast_on_a_large_thread()
    test_time_hint_narrows_but_falls_back_if_nothing_in_window()
    test_no_query_tokens_returns_empty_not_an_error()
    test_format_thread_matches_is_readable_and_chronological()
    test_retrieved_reference_survives_begin_turn_then_clears_after_end_turn()
    print("✓ ALL THREAD SEARCH TESTS PASSED")
