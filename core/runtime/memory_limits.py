from __future__ import annotations

"""KEEPING JARVIS SMALL ENOUGH TO SURVIVE ON A PHONE.

THE CRASH, FROM UK'S OWN SAMPLES
================================
His resource log settles the question that guessing could not:

    uptime  676s   RSS  172 MB   device free 1158 MB
                        [14.4 second sampling gap -- process stalled]
    uptime  690s   RSS 1897 MB   device free  789 MB   <-- killed here

JARVIS's steady state is ~170 MB. There is no leak. What kills it is a
TRANSIENT ~1.7 GB allocation, on a device that only had 789 MB free at
that moment. Android's low-memory killer sends SIGKILL, which runs no
Python handler -- which is exactly why no crash JSON was ever written.
The absence of the crash file was itself evidence: a caught exception
would have left one.

The same spike appears at startup (2152 MB at uptime 0.1s, down to
170 MB by 99s). Same cause, survived only because more memory happened
to be free at boot.

WHERE 1.7 GB COMES FROM
=======================
Two ONNX sessions, and neither was constrained:

  * onnx_embedder.py created InferenceSession with NO SessionOptions at
    all -- default thread count (one arena per core) and the CPU memory
    arena enabled, which pre-allocates aggressively rather than growing
    on demand.
  * semantic_memory.py capped threads but left the arena on and used
    ORT_ENABLE_ALL, which materialises a fully optimised graph in
    memory during load.

On a desktop that is fine. On a phone with ~1 GB free it is fatal, and
the cost is paid for a model whose weights are only ~45 MB.

WHAT THIS FILE DOES
===================
  1. low_memory_session_options() -- one place defining the settings,
     used by both sessions. Arena off, single thread, basic
     optimisation. Slower per call; the difference between slower and
     dead.
  2. memory_guard() -- checks free device memory BEFORE a known-heavy
     operation and refuses when there is not enough headroom. A refused
     embedding is recoverable. A SIGKILL is not.
"""

import os
from typing import Any, Optional

from .log import log_event

# Refuse heavy allocations below this much free device memory.
# UK's device died with 789 MB free during a ~1.7 GB spike; 600 MB is
# below every steady-state reading in his log, so this should never
# fire in normal use and always fire before a repeat of that spike.
MIN_FREE_MB_FOR_HEAVY = 600.0


def available_mb() -> float:
    """Free device memory. Returns a large number if unknowable, so an
    unreadable /proc never blocks normal operation."""
    try:
        with open("/proc/meminfo", "r") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    try:
        import psutil  # type: ignore
        return psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        return float("inf")


def memory_guard(operation: str, required_mb: float = MIN_FREE_MB_FOR_HEAVY) -> bool:
    """True if there is room to do something expensive.

    Callers must handle False by degrading, not by pushing on. The whole
    point is that the alternative to a degraded turn is a dead process.
    """
    free = available_mb()
    if free >= required_mb:
        return True
    log_event(
        "memory",
        f"refusing '{operation}': only {free:.0f}MB free, need {required_mb:.0f}MB. "
        "Degrading rather than risking an OOM kill.",
        level="warning",
    )
    return False


def low_memory_session_options(ort_module: Any) -> Any:
    """ONNX settings tuned for a phone, in one place.

    enable_cpu_mem_arena=False is the important one. The arena
    pre-allocates a large pool up front; without it ORT allocates as it
    goes, which is slower per inference and dramatically smaller at
    peak. For a 45 MB model answering a handful of queries a second,
    that is the right trade.
    """
    options = ort_module.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort_module.ExecutionMode.ORT_SEQUENTIAL
    # BASIC, not ENABLE_ALL: full optimisation builds a second graph in
    # memory at load time, which is part of the startup spike.
    options.graph_optimization_level = ort_module.GraphOptimizationLevel.ORT_ENABLE_BASIC
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    try:
        options.add_session_config_entry("session.use_env_allocators", "0")
    except Exception:
        pass
    return options


def apply_process_limits() -> None:
    """Environment caps that must be set BEFORE onnxruntime is imported.

    ORT reads these at import time, so calling this after the import has
    no effect -- it belongs at the very top of the entry point.
    """
    for key, value in (
        ("OMP_NUM_THREADS", "1"),
        ("OPENBLAS_NUM_THREADS", "1"),
        ("MKL_NUM_THREADS", "1"),
        ("NUMEXPR_NUM_THREADS", "1"),
        ("ORT_DISABLE_ALL_OPTIMIZATION", "0"),
    ):
        os.environ.setdefault(key, value)
