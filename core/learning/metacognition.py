from __future__ import annotations

"""Metacognitive calibration (UK's #5 recall/learning/memory proposal).

Memory psychology distinguishes a memory's raw confidence from its
CALIBRATION -- whether that confidence has historically been
trustworthy ("feeling of knowing" accuracy). This module answers that
for JARVIS honestly, using data that already exists: every time a
semantic fact's value changes, SemanticMemory.remember() already
records the REPLACED value together with the confidence it had at
the time, in Knowledge.history (see semantic_memory.py). A fact that
gets contradicted while it was stored at HIGH confidence is exactly
"confidently wrong" -- this module is a read-only scan over that
already-recorded history, not new tracking machinery.
"""

import time
from typing import Any, Dict, List

HIGH_CONFIDENCE_THRESHOLD = 0.75


def calibration_report(memory_manager: Any, limit: int = 500) -> Dict[str, Any]:
    semantic = getattr(memory_manager, "semantic", memory_manager)
    if semantic is None or not hasattr(semantic, "list_all"):
        return {"available": False}

    total_contradictions = 0
    overconfident_contradictions = 0
    examples: List[Dict[str, Any]] = []

    try:
        items = semantic.list_all(limit=limit)
    except Exception:
        return {"available": False}

    for item in items:
        for entry in (getattr(item, "history", None) or []):
            total_contradictions += 1
            prior_confidence = float(entry.get("confidence", 0.0) or 0.0)
            if prior_confidence >= HIGH_CONFIDENCE_THRESHOLD:
                overconfident_contradictions += 1
                if len(examples) < 5:
                    examples.append({
                        "subject": item.subject,
                        "predicate": item.predicate,
                        "old_value": entry.get("value"),
                        "current_value": item.value,
                        "confidence_at_the_time": round(prior_confidence, 2),
                    })

    calibration_score = (
        round(1.0 - (overconfident_contradictions / total_contradictions), 3)
        if total_contradictions else None
    )

    return {
        "available": True,
        "total_contradictions": total_contradictions,
        "overconfident_contradictions": overconfident_contradictions,
        "calibration_score": calibration_score,
        "examples": examples,
        "generated_at": time.time(),
    }
