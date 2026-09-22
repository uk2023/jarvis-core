# -*- coding: utf-8 -*-
"""
Shared helpers for turning the REAL brain.last_turn_trace into the
exact JSON shapes the web frontend expects (see web_frontend/src/types.ts
-- TurnTrace, ChatMessage.traceLog).

Why this file exists: /api/chat (routes_frontend_v6.py) and the /ws
handler (routes_ws.py) each used to build their OWN "trace_log" summary
by reading field names that do not exist anywhere on the real trace
object cli.py's execute_cognitive_query() produces (things like
trace["vector_matches"], trace["memory_signal"], trace["learning_queue"]
were never set by core/orchestration/brain.py -- see its _trace()
method). The result was a trace panel that always showed 0 matches / no
facts, no matter what the pipeline actually did that turn.

One shared module now reads the real trace exactly once, so the REST
path and the websocket path can never drift into two different,
partially-fabricated shapes again -- and if the real trace's shape ever
changes upstream in core/, there is exactly one place to update.
"""
import json
import time
from typing import Any, Dict, Optional


def _default_json(value: Any) -> Any:
    """Fallback for anything json.dumps can't serialize natively --
    chiefly Knowledge dataclass instances that show up inside
    perception/semantic_evidence (SemanticMemory hands back live
    Knowledge objects, not plain dicts). Prefers a real
    to_dict()/vars() representation over a bare str() so the actual
    subject/predicate/value survive in the JSON instead of collapsing
    into an opaque repr string."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return value.to_dict()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {k: v for k, v in vars(value).items() if not k.startswith("_")}
        except Exception:
            pass
    return str(value)


def json_safe(value: Any) -> Any:
    """Round-trip a value through json.dumps/loads with the
    Knowledge-aware default= above, guaranteeing the result is plain
    dicts/lists/primitives. Needed because FastAPI's JSONResponse and a
    websocket's send_json() both use the stdlib json encoder with NO
    default= -- unlike backend's own DB-storage path (turn_trace_to_json
    below), a non-dict domain object anywhere in the trace (e.g. a
    Knowledge instance under perception.semantic_evidence.exact) would
    otherwise crash the whole response with 'Object of type Knowledge
    is not JSON serializable'."""
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, default=_default_json))
    except Exception:
        return None


def real_turn_trace(brain: Any) -> Optional[Dict[str, Any]]:
    """Return brain.last_turn_trace exactly as the cognitive pipeline
    produced it -- the SAME dict cli.py's execute_cognitive_query() and
    deep_inspector.py's render_query_trace() read (see
    core/orchestration/brain.py's _trace() and blueprint_brain.py's
    added contract_validation_trace/llm_budget) -- made JSON-safe (see
    json_safe() above) so every caller (JSONResponse, websocket
    broadcast, DB storage) can hand it straight to a JSON encoder
    without re-discovering the same Knowledge-object crash separately.
    Never invents a field that isn't actually on the object; returns
    None if brain/trace aren't available yet rather than a fabricated
    placeholder.

    Also attaches two genuinely-real supplementary blocks the raw trace
    object does NOT carry on its own -- indexing (memory/knowledge/graph
    retrieval counts) and learning_queue (background queue status) --
    read from brain.last_context and brain.status() respectively, the
    exact same two extra reads cli.py's render_workflow_panel() does for
    its stage 2 (INDEXING) and stage 5 (LEARNING) lines. Without this,
    the web Trace Inspector's INDEXING/LEARNING panels would always show
    "-" since core/orchestration never puts these numbers on
    last_turn_trace itself.
    """
    trace = getattr(brain, "last_turn_trace", None) if brain is not None else None
    if not isinstance(trace, dict):
        return None
    trace = dict(trace)

    context = getattr(brain, "last_context", None) if brain is not None else None
    if isinstance(context, dict):
        trace.setdefault("indexing", {
            "memory": len(context.get("recent_experiences") or []),
            "knowledge": len(context.get("relevant_knowledge") or []),
            "graph": len(context.get("graph_relations") or []),
        })

    status_fn = getattr(brain, "status", None) if brain is not None else None
    if callable(status_fn):
        try:
            queue_status = _safe_dict(status_fn()).get("async_learning_queue")
        except Exception:
            queue_status = None
        if isinstance(queue_status, dict):
            trace.setdefault("learning_queue", dict(queue_status))

    # TOOL-CALL TRACE (2026-09-17, UK's evidence: codebox/coding-agent
    # steps rendered live but vanished on refresh, and never showed up
    # in cli.py's /tool_trace either). brain.last_tool_call_trace is a
    # SEPARATE attribute from last_turn_trace -- set by
    # tool_registry.run_tool_loop, never folded into the trace this
    # function returns, so neither the persisted trace_log nor the
    # websocket broadcast ever carried it. Folding it in here means
    # every caller of real_turn_trace() (WS broadcast, DB save,
    # /api/history) gets it for free, from the one place, instead of
    # three separate call sites re-reading brain.last_tool_call_trace
    # and inevitably drifting out of sync with each other.
    tool_trace = getattr(brain, "last_tool_call_trace", None) if brain is not None else None
    if isinstance(tool_trace, list):
        trace.setdefault("tool_calls", tool_trace)

    return json_safe(trace)


def turn_trace_to_json(trace: Optional[Dict[str, Any]]) -> Optional[str]:
    """JSON-encode a real trace dict for storage in chat_messages.trace_log.
    default=str guards against any incidental non-JSON-safe value in the
    trace (e.g. a stray object) without ever crashing the save."""
    if not trace:
        return None
    try:
        return json.dumps(trace, default=str)
    except Exception:
        return None


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def turn_trace_summary(trace: Optional[Dict[str, Any]], brain: Any = None) -> Optional[Dict[str, Any]]:
    """Compact summary for the inline per-message "Cognitive Trace"
    widget (web_frontend/src/components/NeuralChat.tsx). Every field
    here is read from the SAME real trace/context data the full Trace
    Inspector uses (see TraceTreeViewer.tsx) -- just condensed for a
    chat bubble. This mirrors exactly what cli.py's render_workflow_panel
    shows for stages 1/2/3/4, not a second guess at what those numbers
    might be.
    """
    if not trace:
        return None

    perception = _safe_dict(trace.get("perception"))
    route = _safe_dict(trace.get("cognitive_route"))
    decision = _safe_dict(trace.get("brain_decision"))
    timings = _safe_dict(trace.get("timings"))
    semantic = _safe_dict(perception.get("semantic_understanding"))

    context = _safe_dict(getattr(brain, "last_context", None)) if brain is not None else {}

    return {
        "traceId": f"trc-{int(time.time() * 1000)}",
        "latencySeconds": float(timings.get("total", 0.0) or 0.0),
        "mode": decision.get("mode") or route.get("mode") or "native",
        "status": decision.get("status") or trace.get("action_response", {}).get("status") or "unknown",
        "memoryMatches": len(context.get("recent_experiences") or []),
        "knowledgeMatches": len(context.get("relevant_knowledge") or []),
        "graphRelations": len(context.get("graph_relations") or []),
        "semanticRelations": semantic.get("relations") or [],
        "llmAvailable": bool(trace.get("llm_available")),
        "pipelineSuccess": bool(trace.get("pipeline_success")),
    }


def derive_thinking_steps(trace: Optional[Dict[str, Any]], brain: Any = None) -> list:
    """The Claude-style step list web_frontend/src/components/ThinkingSteps.tsx
    renders (stage heading + content), for THIS turn -- built from
    trace["tool_calls"] (see real_turn_trace() above, which folds
    brain.last_tool_call_trace in). Never invents a step: if no coding
    tool ran this turn, returns [].

    Two sources, because the two coding tools carry their step data
    differently:
      - run_coding_task -> codebox.py's Step.as_dict() list is already
        sitting in the tool result under "steps" (kind/detail/output/ok).
      - run_coding_agent -> the tool RESULT is deliberately lean (see
        companion_tools._coding_agent_result's own docstring: it exists
        so the MODEL can't over-claim from a bloated result). The rich
        per-step data lives on brain._last_coding_task.observations
        instead, read here directly -- this function runs synchronously
        right after the tool call, in the same request, so that
        in-memory task is still the right one.
    """
    steps: list = []
    for call in (trace or {}).get("tool_calls") or []:
        name = call.get("name")
        result = _safe_dict(call.get("result"))

        if name == "run_coding_task":
            for s in (result.get("steps") or []):
                if not isinstance(s, dict):
                    continue
                content = (s.get("output") or s.get("detail") or "").strip()
                steps.append({
                    "stage": str(s.get("kind", "step")),
                    "content": content[:2000],
                    "duration_ms": round(float(s.get("duration", 0.0)) * 1000, 1),
                    "ok": s.get("ok"),
                })

        elif name == "run_coding_agent":
            task = getattr(brain, "_last_coding_task", None) if brain is not None else None
            if task is None or getattr(task, "objective", None) != (call.get("arguments") or {}).get("objective"):
                continue  # not THIS call's task (e.g. a duplicate-suppressed retry)
            for obs in getattr(task, "observations", None) or []:
                tool_call = getattr(obs, "tool_call", None)
                obs_result = getattr(obs, "result", None)
                if tool_call is not None:
                    content = f"{tool_call.tool_name}({tool_call.arguments})"
                    if obs_result is not None:
                        tail = obs_result.output if obs_result.ok else (obs_result.skip_reason or obs_result.output)
                        if tail:
                            content += f" -> {tail}"
                else:
                    content = getattr(obs, "note", "") or ""
                steps.append({
                    "stage": str(getattr(obs, "phase", "step")),
                    "content": content[:2000],
                    "ok": (obs_result.ok if obs_result is not None else None),
                })
    return steps


def extracted_fact_from_trace(trace: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Real "did this turn write a new fact" signal -- reuses the exact
    semantic_understanding.relations data cli.py's render_workflow_panel
    prints as its knowledge_line (stage 6), instead of a separate
    trace["memory_signal"] field that the real trace never sets."""
    if not trace:
        return None
    semantic = _safe_dict(_safe_dict(trace.get("perception")).get("semantic_understanding"))
    relations = semantic.get("relations") or []
    if not relations or not isinstance(relations[0], dict):
        return None
    first = relations[0]
    return {
        "subject": first.get("subject"),
        "predicate": first.get("predicate"),
        "value": first.get("value"),
        "confidence": semantic.get("confidence"),
    }
