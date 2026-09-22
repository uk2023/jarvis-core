"""Tests, 2026-09-20 pass: llm_provider_engine.py is Groq-only (UK's
explicit, repeated instruction: "bas grok engine rahe"), and
_generate_groq prefers GroqEngine's own REAL per-key remaining-token
telemetry over the older RPM-window estimate when both exist.

Run directly: python3 tests/test_provider_engine_groq_only.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.orchestration.llm_provider_engine as mod
from core.orchestration.llm_provider_engine import LLMProviderEngine


def test_cerebras_cloudflare_classes_do_not_exist():
    assert not hasattr(mod, "CerebrasEngine")
    assert not hasattr(mod, "CloudflareEngine")
    print("OK: CerebrasEngine/CloudflareEngine classes removed entirely")


def test_engine_has_no_cerebras_cloudflare_methods():
    assert not hasattr(LLMProviderEngine, "_generate_cerebras")
    assert not hasattr(LLMProviderEngine, "_generate_cloudflare")
    print("OK: _generate_cerebras/_generate_cloudflare methods removed")


class _FakeGroqEngine:
    def __init__(self):
        self.api_keys = ["k1", "k2", "k3"]
        self._current_index = 0
        self._last_attempts = []
        self._key_telemetry = {
            0: {"key_index": 0, "tpm_remaining": 500},
            1: {"key_index": 1, "tpm_remaining": 200},
            2: {"key_index": 2, "tpm_remaining": 9000},
        }
        self.generate_calls = []

    def _capacity_ordered_key_indices(self, estimated_tokens=None):
        # Mirrors llm_bridge.GroqEngine's real logic: highest real
        # remaining first.
        return sorted(self._key_telemetry, key=lambda i: -self._key_telemetry[i]["tpm_remaining"])

    def generate(self, **kwargs):
        self.generate_calls.append(self._current_index)
        return "ok"


def test_generate_only_considers_groq_and_uses_real_capacity_order():
    fake_groq = _FakeGroqEngine()
    engine = LLMProviderEngine(groq_engine=fake_groq)
    result = engine.generate("sys", "hi")
    assert result == "ok"
    assert engine.last_provider == "groq"
    # key index 2 has the most REAL remaining tokens (9000) -- must be
    # the one GroqEngine was told to prefer.
    assert fake_groq._current_index == 2, f"expected real-capacity key 2 preferred, got {fake_groq._current_index}"
    print("OK: generate() is groq-only and prefers the REAL highest-remaining-capacity key")


def test_generate_raises_cleanly_with_no_providers_configured():
    engine = LLMProviderEngine(groq_engine=None)
    try:
        engine.generate("sys", "hi")
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    print("OK: no configured provider raises cleanly, no silent fallback to a removed provider")


if __name__ == "__main__":
    test_cerebras_cloudflare_classes_do_not_exist()
    test_engine_has_no_cerebras_cloudflare_methods()
    test_generate_only_considers_groq_and_uses_real_capacity_order()
    test_generate_raises_cleanly_with_no_providers_configured()
    print("\nAll provider-engine Groq-only tests passed.")
