import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

try:
    from core.memory.semantic_memory import SemanticMemory
except ImportError as e:
    Console().print(f"[bold red]❌ Import Error: {e}[/bold red]")
    sys.exit(1)

console = Console()


def run_test():
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]🧪 JARVIS MEMORY DEDUPLICATION & SYNC TEST[/bold cyan]",
            border_style="bright_blue",
        )
    )

    memory = SemanticMemory()
    # SemanticMemory ka dynamic DB path extract kar rahe hain (always synced)
    db_path = getattr(memory, "db_path", "database/jarvis.db")

    # Step 1: Initial Test Insert
    console.print(
        "\n[bold yellow]Step 1: Initial test record insert ho raha hai...[/bold yellow]"
    )
    memory.remember(
        subject="test_user", predicate="favorite_lang", value="Python"
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*), subject, predicate, value FROM knowledge WHERE subject='test_user'"
    )
    row_count_1, sub_1, pred_1, val_1 = cursor.fetchone()
    conn.close()

    console.print(
        f"Rows in DB: [green]{row_count_1}[/green] | Data: [white]{sub_1} -> {pred_1} -> {val_1}[/white]"
    )

    # Step 2: Re-insert with Updated Value
    console.print(
        "\n[bold yellow]Step 2: Same Subject + Predicate ko updated value ('Rust') se re-insert kar rahe hain...[/bold yellow]"
    )
    memory.remember(
        subject="test_user", predicate="favorite_lang", value="Rust"
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*), subject, predicate, value FROM knowledge WHERE subject='test_user'"
    )
    row_count_2, sub_2, pred_2, val_2 = cursor.fetchone()

    # Cleanup Test Data
    cursor.execute("DELETE FROM knowledge WHERE subject='test_user'")
    conn.commit()
    conn.close()

    # Result Verification
    table = Table(
        title="Deduplication Test Results",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Check Condition", style="cyan")
    table.add_column("Expected Outcome", style="green")
    table.add_column("Actual Result", style="yellow")
    table.add_column("Status", style="bold green")

    dedup_success = row_count_2 == 1
    update_success = val_2 == "Rust"

    table.add_row(
        "Row Count (No Duplicates)",
        "1 Row",
        f"{row_count_2} Row(s)",
        "✅ PASS" if dedup_success else "❌ FAIL (Duplicate Created)",
    )
    table.add_row(
        "In-Place Update",
        "Rust",
        f"{val_2}",
        "✅ PASS" if update_success else "❌ FAIL (Old Value Retained)",
    )

    console.print(table)

    if dedup_success and update_success:
        console.print(
            "\n[bold green]🎉 TEST PASSED: Database clean sync ho chuka hai aur duplicates ban na bilkul band ho gaye hain![/bold green]"
        )


if __name__ == "__main__":
    run_test()
