# -*- coding: utf-8 -*-
"""Deep diagnostics for the already-running JARVIS instance.

This module deliberately does NOT boot a second organism or LLM. It consumes
Brain.last_turn_trace produced by the normal cognitive pipeline and performs
only the lightweight SQLite commit audit.
"""
import os
import sqlite3
import time
from rich.panel import Panel
from rich.tree import Tree


def _db_path(base_dir):
    candidates = (
        os.path.join(base_dir, "database", "knowledge_graph.db"),
        os.path.join(base_dir, "database", "jarvis.db"),
    )
    return next((p for p in candidates if os.path.exists(p)), None)


def _latest_rows(base_dir, limit=2):
    path = _db_path(base_dir)
    if not path:
        return []
    try:
        with sqlite3.connect(path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            table = "knowledge" if "knowledge" in tables else (tables[0] if tables else None)
            if not table:
                return []
            # Schema varies between DB revisions; inspect available columns.
            cur.execute(f"PRAGMA table_info({table})")
            cols = {r[1] for r in cur.fetchall()}
            required = {"subject", "predicate", "value"}
            if not required.issubset(cols):
                return []
            created = ", created_at" if "created_at" in cols else ""
            cur.execute(f"SELECT subject, predicate, value{created} FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,))
            return cur.fetchall()
    except Exception:
        return []


def run_inspection(jarvis, query, console, executor=None):
    """Run one normal cognitive turn and render a forensic-style trace.

    `executor` should normally be cli.execute_cognitive_query. When supplied,
    it guarantees that inspection uses exactly the same pipeline as CLI/web.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    before = _latest_rows(base_dir)
    tree = Tree(f"[bold magenta]🔬 TRACE MAP: '{query}'[/bold magenta]")

    # Stage 1: ingestion is performed by the normal executor.
    s1 = tree.add("[bold yellow]Stage 1: Event Ingestion (EventBus)[/bold yellow]")
    s1.add("Status: [green]PENDING → NORMAL COGNITIVE PIPELINE[/green]")

    started = time.time()
    reply = ""
    error = None
    try:
        if executor is not None:
            reply = executor(jarvis, query, source="deep_inspector")
        else:
            brain = jarvis.get_organ("brain")
            identity = {
                "name": "JARVIS",
                "creator": "UK",
                "nature": "Modular Cognitive Organism",
                "instruction": "Respond accurately in Hinglish directly as JARVIS. User is UK, your creator.",
            }
            jarvis.receive_event("USER_INPUT", {"text": query}, source="deep_inspector")
            reply = brain.think_and_respond(query, identity_profile=identity, source="deep_inspector")
    except Exception as exc:
        error = exc
        reply = f"[Error: {exc}]"

    elapsed = time.time() - started
    brain = jarvis.get_organ("brain") if hasattr(jarvis, "get_organ") else None
    trace = getattr(brain, "last_turn_trace", {}) or {}

    s1.children = []
    s1.add("Status: [green]SUCCESS[/green] | Event entered normal pipeline.") if not error else s1.add(f"Status: [red]ERROR[/red] | {error}")

    # Stage 2: consume the trace — no second build_context call.
    mem = trace.get("memory", {}) or {}
    s2 = tree.add("[bold blue]Stage 2: Semantic Memory & Knowledge Retrieval[/bold blue]")
    s2.add(f"FAISS Vector Frames Retrieved: [cyan]{mem.get('recent_experiences', 0)}[/cyan]")
    s2.add(f"SQLite/Knowledge Facts: [cyan]{mem.get('relevant_knowledge', 0)}[/cyan]")
    s2.add(f"NetworkX Graph Relations: [cyan]{mem.get('graph_relations', 0)}[/cyan]")
    matches = trace.get("vector_matches", []) or []
    if matches:
        top = matches[0]
        s2.add(f"Top Match → {top.get('subject')} | {top.get('predicate')} | {top.get('value')} | sim={top.get('similarity')}")

    # Stage 3
    s3 = tree.add("[bold cyan]Stage 3: LLM Synthesis & Neural Inference[/bold cyan]")
    s3.add(f"Inference Latency: [green]{trace.get('timings', {}).get('llm', elapsed):.3f} s[/green]")
    s3.add(f"Pipeline Total: [dim]{trace.get('timings', {}).get('total', elapsed):.3f} s[/dim]")

    # Stage 4
    qs = trace.get("learning_queue", {}) or {}
    if not qs and brain is not None and hasattr(brain, "status"):
        try:
            qs = brain.status().get("async_learning_queue", {}) or {}
        except Exception:
            qs = {}
    s4 = tree.add("[bold green]Stage 4: Asynchronous Learning Queue & Background Worker[/bold green]")
    s4.add(f"Background Daemon: [bold cyan]{'ACTIVE' if qs.get('alive') else 'INACTIVE'}[/bold cyan]")
    s4.add(f"Pending: [yellow]{qs.get('pending', 0)}[/yellow] | Processed: [green]{qs.get('processed', 0)}[/green] | Failed: [red]{qs.get('failed', 0)}[/red]")

    # Stage 5
    time.sleep(0.15)
    after = _latest_rows(base_dir)
    s5 = tree.add("[bold magenta]Stage 5: SQLite Database Commit Audit[/bold magenta]")
    if after != before:
        s5.add("[bold green]✔ NEW TRIPLES COMMITTED TO DATABASE DETECTED![/bold green]")
        for row in after:
            s5.add(f"└─ Subject: {row[0]} | Predicate: {row[1]} | Value: {row[2]}")
    else:
        s5.add("[dim]No new SPO triples committed in this turn.[/dim]")

    console.print(Panel(tree, title="[bold white]Deep Inspector — Single-Pass Trace[/bold white]", border_style="cyan"))
    console.print(Panel(f"[white]{reply}[/white]", title="[bold green]JARVIS Response[/bold green]", border_style="green"))
    return reply
