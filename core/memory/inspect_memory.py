import os
import sqlite3
from typing import Dict, List, Optional, Set

import networkx as nx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

try:
    import faiss
except ImportError:
    faiss = None

console = Console()

# SINGLE SOURCE OF TRUTH, ANCHORED TO THE PROJECT ROOT -- NOT a
# relative path. A relative "database/jarvis.db" resolves differently
# depending on the CURRENT WORKING DIRECTORY the script happens to be
# invoked from: correct when run from the project root (cli.py's
# normal case), but silently wrong (or pointing at a path that doesn't
# exist at all) if this file is ever run directly from inside a
# subdirectory (e.g. `cd database && python3 inspect_memory.py`,
# which was tried directly). Anchoring to this file's own location
# makes the resolved path identical no matter where the process's
# cwd happens to be.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_PROJECT_ROOT, "database", "jarvis.db")
FAISS_PATH = os.path.join(_PROJECT_ROOT, "database", "jarvis_faiss.index")


def load_db_data() -> List[Dict]:
    """SQLite database se saari knowledge entries load karta hai."""
    if not os.path.exists(DB_PATH):
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT knowledge_id, subject, predicate, value, confidence, importance, evidence_count, faiss_id, updated_at 
            FROM knowledge 
            ORDER BY importance DESC, updated_at DESC
        """
        )
        rows = [dict(r) for r in cursor.fetchall()]
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    return rows


def get_faiss_stats() -> Dict[str, str]:
    """FAISS index file verify karta hai."""
    if not os.path.exists(FAISS_PATH):
        return {"status": "Not Found", "vectors": "0", "dimension": "N/A"}

    if faiss is None:
        return {"status": "FAISS Module Missing", "vectors": "Unknown", "dimension": "N/A"}

    try:
        index = faiss.read_index(FAISS_PATH)
        return {
            "status": "Online (Synced)",
            "vectors": str(index.ntotal),
            "dimension": str(index.d),
        }
    except Exception as e:
        return {"status": f"Corrupt ({str(e)})", "vectors": "0", "dimension": "N/A"}


def build_recursive_tree(
    graph: nx.DiGraph,
    current_node: str,
    tree_branch: Tree,
    visited: Set[str],
    max_depth: int = 5,
    current_depth: int = 0,
):
    """NetworkX Graph nodes ko infinite/deep multi-hop depth tak visual recursive tree banata hai."""
    if current_depth >= max_depth:
        return

    visited.add(current_node)

    for neighbor in graph.successors(current_node):
        edge_data = graph.edges[current_node, neighbor]
        predicate = edge_data.get("predicate", "linked")
        confidence = edge_data.get("confidence", 1.0)

        label = (
            f"[dim cyan]({predicate})[/dim cyan] ➔ "
            f"[bold bright_white]{neighbor}[/bold bright_white] "
            f"[dim yellow](conf: {confidence:.2f})[/dim yellow]"
        )

        sub_branch = tree_branch.add(label)

        if neighbor not in visited:
            build_recursive_tree(
                graph, neighbor, sub_branch, visited.copy(), max_depth, current_depth + 1
            )


def render_dashboard():
    records = load_db_data()
    faiss_info = get_faiss_stats()

    # 1. HEADER TITLE
    console.print()
    console.print(
        Panel.fit(
            f"[bold white on blue] 🧠 JARVIS AUTONOMOUS MEMORY DIAGNOSTICS & GRAPH ENGINE [/bold white on blue]\n"
            f"[dim cyan]Active Source of Truth: {os.path.abspath(DB_PATH)}[/dim cyan]",
            border_style="cyan",
        )
    )

    # 2. METRICS TABLE
    stats_table = Table(title="📊 System Overview & Health", show_header=True, header_style="bold magenta")
    stats_table.add_column("System Metric", style="cyan")
    stats_table.add_column("Value / Details", style="green")

    db_size = f"{os.path.getsize(DB_PATH) / 1024:.2f} KB" if os.path.exists(DB_PATH) else "0 KB"
    faiss_size = f"{os.path.getsize(FAISS_PATH) / 1024:.2f} KB" if os.path.exists(FAISS_PATH) else "0 KB"

    stats_table.add_row("Primary Database Path (`jarvis.db`)", DB_PATH)
    stats_table.add_row("SQLite File Storage Size", db_size)
    stats_table.add_row("Total DB Records (Knowledge Triples)", str(len(records)))
    stats_table.add_row("FAISS Vector Index Health", faiss_info["status"])
    stats_table.add_row("Vector DB Embedding Count", faiss_info["vectors"])
    stats_table.add_row("Vector Dimension Model Size", faiss_info["dimension"])
    stats_table.add_row("FAISS Index File Storage Size", faiss_size)

    console.print(stats_table)
    console.print()

    if not records:
        console.print(f"[bold red]❌ Database (`{DB_PATH}`) me koi memory record nahi mila![/bold red]")
        return

    # 3. KNOWLEDGE TABLE VISUALIZER
    kn_table = Table(title="📁 Knowledge Records Detail", show_lines=True, header_style="bold yellow")
    kn_table.add_column("FAISS ID", justify="center", style="dim white")
    kn_table.add_column("Subject Node", style="bold green")
    kn_table.add_column("Predicate Relation", style="bold cyan")
    kn_table.add_column("Value / Object Node", style="bold bright_white")
    kn_table.add_column("Conf.", justify="center", style="yellow")
    kn_table.add_column("Ev. Count", justify="center", style="magenta")

    # Build NetworkX Graph simultaneously
    G = nx.DiGraph()

    for r in records:
        sub = str(r["subject"]).strip()
        pred = str(r["predicate"]).strip()
        val = str(r["value"]).strip()
        conf = float(r["confidence"])

        kn_table.add_row(
            str(r.get("faiss_id", "N/A")),
            sub,
            pred,
            val,
            f"{conf:.2f}",
            str(r.get("evidence_count", 1)),
        )

        G.add_edge(sub, val, predicate=pred, confidence=conf)

    console.print(kn_table)
    console.print()

    # 4. DEEP MULTI-HOP GRAPH TREE VISUALIZER
    tree = Tree("[bold bright_green]🕸️ Relational Knowledge Graph (Node Chains)[/bold bright_green]")

    # Find Root Nodes (in_degree == 0)
    root_nodes = [n for n, d in G.in_degree() if d == 0]
    if not root_nodes:
        root_nodes = list(G.nodes())[:10]

    for root in root_nodes:
        root_branch = tree.add(f"[bold gold1]● {root}[/bold gold1]")
        build_recursive_tree(G, root, root_branch, visited=set())

    console.print(
        Panel(
            tree,
            border_style="green",
            title=f"Multi-Hop Node Memory Trace (Nodes: {G.number_of_nodes()} | Edges: {G.number_of_edges()})",
        )
    )


if __name__ == "__main__":
    render_dashboard()
