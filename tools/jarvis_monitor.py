#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time

from textual.app import App, ComposeResult
from textual.containers import Container, Grid
from textual.widgets import Digits, Footer, Header, Static

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(ROOT, "runtime", "jarvis_health.json")


def load_health_data(path: str) -> dict | None:
    """Safely retrieve the JSON health payload from disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


class MetricCard(Static):
    """Component wrapper for discrete telemetry sections."""
    pass


class JarvisHealthDashboard(App):
    """Terminal Application for real-time JARVIS status visualization."""

    CSS = """
    Screen {
        background: #0f172a;
        color: #f8fafc;
    }

    Header {
        background: #1e293b;
        color: #38bdf8;
    }

    Footer {
        background: #1e293b;
    }

    #main-grid {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1 2;
        padding: 1 2;
    }

    MetricCard {
        background: #1e293b;
        border: solid #334155;
        border-title-color: #38bdf8;
        padding: 1 2;
        height: 100%;
    }

    .metric-title {
        color: #94a3b8;
        text-style: bold;
    }

    .metric-value-primary {
        color: #4ade80;
        text-style: bold;
    }

    .metric-value-secondary {
        color: #f43f5e;
        text-style: bold;
    }

    .metric-value-neutral {
        color: #f59e0b;
        text-style: bold;
    }

    .status-banner {
        text-align: center;
        background: #334155;
        color: #e2e8f0;
        padding: 0 1;
        margin-bottom: 1;
    }

    Digits {
        color: #38bdf8;
    }
    """

    BINDINGS = [("q", "quit", "Quit Dashboard")]

    def __init__(self, file_path: str, poll_interval: float):
        super().__init__()
        self.file_path = file_path
        self.poll_interval = poll_interval

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(f"Target: [bold yellow]{self.file_path}[/bold yellow]", id="banner", classes="status-banner")
        
        with Container(id="main-grid"):
            with MetricCard(id="process-card"):
                yield Static("[bold]SYSTEM PROCESS MEMORY & CPU[/bold]\n", classes="metric-title")
                yield Static("Initializing metrics...", id="process-metrics")
            
            with MetricCard(id="heartbeat-card"):
                yield Static("[bold]HEARTBEAT & SYSTEM IDLE[/bold]\n", classes="metric-title")
                yield Static("Initializing metrics...", id="heartbeat-metrics")

            with MetricCard(id="llm-card"):
                yield Static("[bold]LLM INFERENCE ENGINE[/bold]\n", classes="metric-title")
                yield Static("Initializing metrics...", id="llm-metrics")

            with MetricCard(id="snapshot-card"):
                yield Static("[bold]TELEMETRY SNAPSHOT AGE[/bold]\n", classes="metric-title")
                yield Digits("0.0s", id="age-digits")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize background polling loop."""
        self.title = "JARVIS Operational Health Infrastructure"
        self.set_interval(self.poll_interval, self.update_dashboard)

    def update_dashboard(self) -> None:
        """Poll dataset and update user interface components dynamically."""
        data = load_health_data(self.file_path)

        process_widget = self.query_one("#process-metrics", Static)
        heartbeat_widget = self.query_one("#heartbeat-metrics", Static)
        llm_widget = self.query_one("#llm-metrics", Static)
        age_digits = self.query_one("#age-digits", Digits)

        if not data:
            process_widget.update("[yellow][WAIT] Reading health snapshot...[/yellow]")
            heartbeat_widget.update("[yellow][WAIT] Reading health snapshot...[/yellow]")
            llm_widget.update("[yellow][WAIT] Reading health snapshot...[/yellow]")
            age_digits.update("--")
            return

        # Snapshot Age Calculation
        snapshot_ts = float(data.get("timestamp", time.time()))
        age = max(0.0, time.time() - snapshot_ts)
        age_digits.update(f"{age:.1f}s")

        # Process Metrics
        p = data.get("process", {})
        rss = p.get("max_rss_mb", "?")
        user_cpu = p.get("user_cpu_seconds", "?")
        sys_cpu = p.get("system_cpu_seconds", "?")
        threads = p.get("threads", "?")

        process_text = (
            f"[bold cyan]Max RSS Memory:[/bold cyan] {rss} MB\n"
            f"[bold cyan]User CPU Time:[/bold cyan]  {user_cpu}s\n"
            f"[bold cyan]System CPU Time:[/bold cyan] {sys_cpu}s\n"
            f"[bold cyan]Active Threads:[/bold cyan]  {threads}"
        )
        process_widget.update(process_text)

        # Heartbeat Metrics
        hb = data.get("heartbeat", {})
        running = hb.get("running", False)
        idle = hb.get("is_idle", False)
        beats = hb.get("beat_count", "?")

        status_str = "[green]● ONLINE[/green]" if running else "[red]○ OFFLINE[/red]"
        idle_str = "[yellow]IDLE[/yellow]" if idle else "[bold green]PROCESSING[/bold green]"

        heartbeat_text = (
            f"[bold cyan]Daemon Status:[/bold cyan] {status_str}\n"
            f"[bold cyan]System State:[/bold cyan]  {idle_str}\n"
            f"[bold cyan]Total Beats:[/bold cyan]   {beats}"
        )
        heartbeat_widget.update(heartbeat_text)

        # LLM Engine Metrics
        llm = data.get("llm", {})
        backend = llm.get("backend", "Unknown")
        loaded = llm.get("local_loaded", False)
        loaded_str = "[green]Loaded[/green]" if loaded else "[red]Unloaded[/red]"

        llm_text = (
            f"[bold cyan]Active Backend:[/bold cyan] {backend}\n"
            f"[bold cyan]Model Status:[/bold cyan]   {loaded_str}"
        )
        llm_widget.update(llm_text)


def main():
    file_path = os.getenv("JARVIS_HEALTH_FILE", DEFAULT_FILE)
    poll_interval = max(0.5, float(os.getenv("JARVIS_MONITOR_INTERVAL", "1.0")))

    app = JarvisHealthDashboard(file_path=file_path, poll_interval=poll_interval)
    app.run()


if __name__ == "__main__":
    main()
