"""Tests for the grounding-check over-hedging fix (2026-09-19).

UK's real chat logs: nearly every technical discussion got hedged with
"mujhe confirm nahi hai" because ordinary library/format/tool names
(MuPDF, Tesseract, PyMuPDF, PDF, OCR, CLI) weren't in the response
brief's own vocabulary (personal/conversational facts, never a
technical encyclopedia). check_response_grounding()'s own docstring
says its job is catching an INVENTED name/place/figure -- general
technical knowledge is not that, and must not be flagged as if it
were.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestration.response_brief import check_response_grounding

_EMPTY_BRIEF = {
    "user_message": "",
    "persona": {"name": "JARVIS", "creator": "UK"},
    "known_facts": [], "known_relations": [], "recent_context": [], "user_rules": [],
}


def test_mupdf_tesseract_not_flagged():
    """UK's exact real response that got hedged."""
    response = "MuPDF khud se OCR nahi karta. OCR ke liye Tesseract-OCR jaise external script ki zarurat hoti hai."
    result = check_response_grounding(response, _EMPTY_BRIEF)
    assert result.flagged_unsupported == [], result.flagged_unsupported


def test_pymupdf_pdf_not_flagged():
    response = "PyMuPDF (fitz) fast rendering ke liye achha hai, PDF text aur image extraction dono karta hai."
    result = check_response_grounding(response, _EMPTY_BRIEF)
    assert result.flagged_unsupported == [], result.flagged_unsupported


def test_uncurated_all_caps_acronym_also_exempt():
    """The general ALL-CAPS-acronym rule must catch acronyms not in
    the curated _COMMON_TECH_WORDS list too -- new libraries/formats
    keep coming up in real technical discussion."""
    response = "Termux PRoot ARM64 environment mein ye chalega, CPU aur RAM dono support karta hai."
    result = check_response_grounding(response, _EMPTY_BRIEF)
    assert "ARM64" not in result.flagged_unsupported
    assert "CPU" not in result.flagged_unsupported
    assert "RAM" not in result.flagged_unsupported


def test_genuine_personal_fabrication_still_flagged():
    """The fix must be narrow -- a genuinely invented personal
    name/place must still be caught, exactly as before."""
    response = "Aapka dost Rakesh ne kaha tha ki aap Mumbai mein rehte hain."
    result = check_response_grounding(response, _EMPTY_BRIEF)
    assert "Rakesh" in result.flagged_unsupported
    assert "Mumbai" in result.flagged_unsupported


def test_mixed_response_flags_only_the_genuinely_unsupported_part():
    """A response combining legitimate technical vocabulary AND a
    fabricated personal claim must flag ONLY the fabricated part."""
    response = "PaddleOCR use kar sakte hain. Waise aapke colleague Suresh ne bhi yehi suggest kiya tha."
    result = check_response_grounding(response, _EMPTY_BRIEF)
    assert "Suresh" in result.flagged_unsupported
    assert "PaddleOCR" not in result.flagged_unsupported


if __name__ == "__main__":
    test_mupdf_tesseract_not_flagged()
    test_pymupdf_pdf_not_flagged()
    test_uncurated_all_caps_acronym_also_exempt()
    test_genuine_personal_fabrication_still_flagged()
    test_mixed_response_flags_only_the_genuinely_unsupported_part()
    print("✓ ALL GROUNDING-CHECK OVER-HEDGING FIX TESTS PASSED")
