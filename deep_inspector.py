# -*- coding: utf-8 -*-
"""JARVIS deep runtime inspector.

Renders one real Brain turn and the validator events actually observed during
that turn. It never performs retrieval or cognition itself.
"""
import os
import sys
import sqlite3
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.organism.bootstrap import start_jarvis, stop_jarvis
from core.orchestration.llm_bridge import LlamaCppBridge

console = Console()


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _short(value: Any, limit: int = 900) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _contract_state(brain: Any, name: str) -> tuple[str, dict]:
    contracts = _d(getattr(brain, "last_contracts", None))
    payload = contracts.get(name)
    events = _items(getattr(brain, "last_runtime_contract_trace", None))
    event = next((e for e in reversed(events) if _d(e).get("schema") == name), None)
    status = _d(event).get("status") if event else None
    if status == "PASS" and isinstance(payload, dict):
        return "PASS", payload
    if status == "FAIL":
        return "FAIL", payload if isinstance(payload, dict) else {}
    if isinstance(payload, dict):
        return "OBSERVED", payload
    return "NOT OBSERVED", {}


def _boundary(tree: Tree, brain: Any, output_name: str, input_name: str, label: str):
    node = tree.add(f"[bold]{label}[/bold]")
    out_status, out_payload = _contract_state(brain, output_name)
    in_status, in_payload = _contract_state(brain, input_name)
    node.add(f"{output_name}: {out_status}")
    if out_payload:
        node.add(f"output: {_short(out_payload)}")
    node.add(f"{input_name}: {in_status}")
    if in_payload:
        node.add(f"input: {_short(in_payload)}")
    return node


def _runtime_contract_trace(brain: Any, trace: dict, response: Any) -> dict:
    router = _d(getattr(brain, "last_router_output", None))
    decision = _d(getattr(brain, "last_brain_decision", None))
    perception = _d(getattr(brain, "last_perception", None))
    semantic = _d(perception.get("semantic_understanding"))
    provenance = _d(semantic.get("provenance"))
    route = router.get("route") or _d(getattr(brain, "last_cognitive_decision", None)).get("mode")
    execution = decision.get("mode")
    fallback_allowed = router.get("fallback_allowed")
    consistency = "PASS"
    reason = "Router route and Brain execution are aligned."
    if route and execution and route != execution and fallback_allowed is False:
        consistency = "FAIL"
        reason = f"Router selected '{route}' but Brain executed '{execution}' while fallback is forbidden."
    elif route and execution and route != execution:
        consistency = "REVIEW"
        reason = f"Router selected '{route}' and Brain executed '{execution}'; router permits fallback."

    validation_events = _items(getattr(brain, "last_runtime_contract_trace", None))
    return {
        "contracts": dict(getattr(brain, "last_contracts", {}) or {}),
        "validation_events": validation_events,
        "semantic_provenance": {
            "source": provenance.get("source", "unknown"),
            "fallback_used": provenance.get("source") == "llm_fallback",
        },
        "route_consistency": {
            "router_route": route,
            "brain_execution": execution,
            "fallback_allowed": fallback_allowed,
            "status": consistency,
            "reason": reason,
        },
        "learning_state": {
            "experience_input": getattr(brain, "last_experience_input", None),
            "experience_output": getattr(brain, "last_experience_output", None),
            "learning_input": getattr(brain, "last_learning_input", None),
            "learning_output": getattr(brain, "last_learning_output", None),
            "self_evaluation_input": getattr(brain, "last_self_evaluation_input", None),
            "self_evaluation_output": getattr(brain, "last_self_evaluation_output", None),
            "memory_input": getattr(brain, "last_memory_input", None),
            "memory_output": getattr(brain, "last_memory_output", None),
        },
        "response": response,
        "trace_source": trace.get("source"),
        "llm_budget": _d(trace.get("llm_budget")),
    }


def render_query_trace(brain, trace=None, *, source="cli", query=None, response=None):
    """Render one real turn, live validator events, provenance and authority."""
    trace = _d(trace) or _d(getattr(brain, "last_turn_trace", None))
    query = query if query is not None else trace.get("query", trace.get("user_input", ""))
    response = response if response is not None else trace.get("response_preview", trace.get("response", ""))
    runtime = _runtime_contract_trace(brain, trace, response)

    tree = Tree(f"[bold cyan]JARVIS DEEP RUNTIME TRACE[/bold cyan] [dim](source={source})[/dim]")
    root = tree.add("[bold blue]TURN[/bold blue]")
    root.add(f"query: {_short(query)}")
    root.add(f"pipeline_success: {trace.get('pipeline_success', False)}")
    root.add(f"trace_timestamp: {trace.get('timestamp', 'unknown')}")

    stages = tree.add("[bold cyan]LAYER → LAYER CONTRACT EXECUTION[/bold cyan]")
    _boundary(stages, brain, "perception.output", "semantic_understanding.input", "Perception → Semantic Understanding")
    _boundary(stages, brain, "semantic_understanding.output", "cognition.input", "Semantic Understanding → Cognition")
    _boundary(stages, brain, "cognition.output", "cognitive_router.input", "Cognition → Cognitive Router")
    _boundary(stages, brain, "cognitive_router.output", "brain.input", "Cognitive Router → Brain")
    _boundary(stages, brain, "brain.output", "experience.input", "Brain → Experience")
    _boundary(stages, brain, "experience.output", "learning.input", "Experience → Learning")
    _boundary(stages, brain, "learning.output", "self_evaluation.input", "Learning → Self-Evaluation")
    _boundary(stages, brain, "self_evaluation.output", "evolution.input", "Self-Evaluation → Evolution")
    _boundary(stages, brain, "evolution.output", "memory.evolution.input", "Evolution → Memory")
    _boundary(stages, brain, "memory.evolution.output", "cognition.input", "Memory → Next Cycle Context")

    audit = tree.add("[bold cyan]CENTRAL VALIDATOR AUDIT[/bold cyan]")
    audit.add(f"events_observed: {len(runtime['validation_events'])}")
    for event in runtime["validation_events"]:
        audit.add(f"{event.get('schema')}: {event.get('status')}")

    sem = tree.add("[bold magenta]SEMANTIC PROVENANCE[/bold magenta]")
    sem.add(f"source: {runtime['semantic_provenance']['source']}")
    sem.add(f"llm_fallback_used: {runtime['semantic_provenance']['fallback_used']}")
    semantic = _d(getattr(brain, "last_perception", None)).get("semantic_understanding")
    sem.add(f"semantic_result_present: {isinstance(semantic, dict) and bool(semantic)}")

    route = tree.add("[bold magenta]ROUTER → BRAIN EXECUTION AUTHORITY[/bold magenta]")
    rc = runtime["route_consistency"]
    route.add(f"router_route: {rc['router_route']}")
    route.add(f"brain_execution: {rc['brain_execution']}")
    route.add(f"fallback_allowed: {rc['fallback_allowed']}")
    route.add(f"status: {rc['status']}")
    route.add(f"reason: {_short(rc['reason'], 1400)}")

    budget = tree.add("[bold yellow]LLM BUDGET[/bold yellow]")
    for key, value in runtime["llm_budget"].items():
        budget.add(f"{key}: {value}")

    learning = tree.add("[bold yellow]EXPERIENCE → LEARNING → SELF-EVALUATION → EVOLUTION → MEMORY[/bold yellow]")
    for key, value in runtime["learning_state"].items():
        learning.add(f"{key}: {_short(value)}")

    retrieval = tree.add("[bold blue]RETRIEVAL EVIDENCE[/bold blue]")
    context = _d(trace.get("memory_context"))
    for key in ("recent_experiences", "relevant_knowledge", "graph_relations"):
        retrieval.add(f"{key}: {len(_items(context.get(key)))}")
    retrieval.add(f"vector_matches: {len(_items(trace.get('vector_matches')))}")
    retrieval.add(f"graph_edges: {len(_items(trace.get('graph_edges')))}")
    retrieval.add(f"typos_corrected: {_short(trace.get('typos_corrected', []))}")

    action = tree.add("[bold green]FINAL RESPONSE[/bold green]")
    action.add(_short(response, 1800))

    metrics = tree.add("[bold white]REAL TURN METRICS[/bold white]")
    for key, value in _d(trace.get("timings")).items():
        metrics.add(f"{key}: {value}")
    metrics.add(f"total_turns: {getattr(brain, 'total_turns', 'unknown')}")
    metrics.add(f"total_latency_seconds: {getattr(brain, 'total_latency_seconds', 'unknown')}")
    metrics.add(f"total_tokens_estimate: {getattr(brain, 'total_tokens_estimate', 'unknown')}")

    console.print(Panel(tree, title="[bold white]DEEP INSPECTION[/bold white]", border_style="cyan"))


def search_sqlite_knowledge(query_text, db_path="database/knowledge_graph.db"):
    if not os.path.exists(db_path):
        db_path = "database/jarvis.db"
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        keywords = [x for x in query_text.split() if len(x) > 2]
        if not keywords:
            conn.close(); return []
        cond = " OR ".join(["subject LIKE ? OR predicate LIKE ? OR value LIKE ?" for _ in keywords])
        params = [p for x in keywords for p in (f"%{x}%", f"%{x}%", f"%{x}%")]
        cur.execute(f"SELECT subject, predicate, value FROM knowledge WHERE {cond} LIMIT 5", params)
        rows = cur.fetchall(); conn.close(); return rows
    except Exception:
        return []


def get_latest_knowledge_rows(db_path="database/knowledge_graph.db", limit=2):
    if not os.path.exists(db_path):
        db_path = "database/jarvis.db"
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path); cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [x[0] for x in cur.fetchall()]
        table = "knowledge" if "knowledge" in tables else (tables[0] if tables else None)
        if not table:
            conn.close(); return []
        cur.execute(f"SELECT subject, predicate, value, created_at FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,))
        rows = cur.fetchall(); conn.close(); return rows
    except Exception:
        return []


def run_inspector():
    console.print(Panel.fit("[bold cyan]JARVIS LIVE CONTINUOUS PIPELINE INSPECTOR[/bold cyan]", border_style="cyan"))
    jarvis = None
    try:
        jarvis = start_jarvis(heartbeat_interval=2.0, idle_threshold=10.0)
        brain = jarvis.get_organ("brain")
        if not brain:
            console.print("[bold red]Brain organ missing.[/bold red]"); return
        if getattr(brain, "_learning_queue", None):
            try: brain._learning_queue.start()
            except Exception: pass
        if not getattr(brain, "llm", None):
            try:
                brain.llm = LlamaCppBridge()  # model choice is LOCKED in config/models.json
            except Exception: pass
        while True:
            query = console.input("[bold cyan]UK (Inspect) > [/bold cyan]").strip()
            if query.lower() in {"exit", "quit", "q"}: break
            if not query: continue
            reply = brain.think_and_respond(query, identity_profile={"name":"JARVIS","creator":"UK","nature":"Modular Cognitive Organism"}, source="deep_inspector")
            render_query_trace(brain, getattr(brain, "last_turn_trace", None), source="deep_inspector", query=query, response=reply)
    finally:
        try: stop_jarvis(jarvis)
        except Exception: pass


if __name__ == "__main__":
    run_inspector()
