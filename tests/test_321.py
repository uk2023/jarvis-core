# ==============================================================================
#  JARVIS SEMANTIC MEMORY SYSTEM - PRODUCTION DIAGNOSTIC SUITE (TEST 321)
# ==============================================================================

import os
os.environ["ORT_LOGGING_LEVEL"] = "3"  # Mute ONNX Runtime warnings

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

from core.memory.semantic_memory import SemanticMemory

console = Console(theme=Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green"
}))

def run_tests():
    db_path = "test_jarvis.db"
    faiss_path = "test_jarvis_faiss.index"

    # Ensure clean state before running test
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(faiss_path):
        os.remove(faiss_path)

    console.print(Panel.fit(
        "[bold cyan]ENGINE INITIALIZATION[/bold cyan]\nLoading ONNX Embedder & FAISS Vector Store",
        title="[bold white]JARVIS CORE[/bold white]",
        border_style="cyan"
    ))

    memory = SemanticMemory(
        db_path=db_path,
        faiss_index_path=faiss_path,
        model_path="all-MiniLM-L6-v2.onnx",
        tokenizer_path="tokenizer.json",
    )

    # -------------------------------------------------------------------------
    # 1. SEEDING MEMORY (Simulated Extracted Facts)
    # -------------------------------------------------------------------------
    memory.remember(subject="user", predicate="uses_recording_mic", value="KZ EDC Pro in-ear monitors", confidence=0.9)
    memory.remember(subject="user", predicate="uses_dac_cable", value="Audiocular C18 USB Type-C DAC", confidence=0.9)
    memory.remember(subject="user", predicate="completed_degree", value="B.Tech in Information Technology", confidence=1.0)
    memory.remember(subject="user", predicate="qualified_exam", value="Central Teacher Eligibility Test (CTET)", confidence=1.0)

    # -------------------------------------------------------------------------
    # TEST 1: NOISE REJECTION (Casual Input Filtering)
    # -------------------------------------------------------------------------
    casual_query = "Hi, kaise ho?"
    casual_facts = memory.semantic_search(casual_query, similarity_threshold=0.15)
    
    t1_panel = f"[bold white]Query:[/bold white] '{casual_query}'\n[bold white]Triggered Facts:[/bold white] {len(casual_facts)}"
    if len(casual_facts) == 0:
        console.print(Panel(t1_panel, title="[bold green]TEST 1: NOISE REJECTION [PASSED][/bold green]", border_style="green"))
    else:
        console.print(Panel(t1_panel, title="[bold red]TEST 1: NOISE REJECTION [FAILED][/bold red]", border_style="red"))
    assert len(casual_facts) == 0, "Noise query triggered unwanted facts!"

    # -------------------------------------------------------------------------
    # TEST 2: HARDWARE PRECISION MATCH (Hinglish Calibrated Threshold = 0.15)
    # -------------------------------------------------------------------------
    hardware_query = "Mera mic aur DAC setup kya hai?"
    hw_facts = memory.semantic_search(hardware_query, similarity_threshold=0.15)

    hw_table = Table(title="Hardware Query Vector Retrieval Results", show_header=True, header_style="bold yellow")
    hw_table.add_column("Predicate", style="cyan")
    hw_table.add_column("Retrieved Value", style="green")

    for f in hw_facts:
        hw_table.add_row(f.predicate, f.value)

    console.print(hw_table)
    
    t2_panel = f"[bold white]Query:[/bold white] '{hardware_query}'\n[bold white]Triggered Vector Facts:[/bold white] {len(hw_facts)}"
    if len(hw_facts) >= 2:
        console.print(Panel(t2_panel, title="[bold green]TEST 2: HARDWARE PRECISION MATCH [PASSED][/bold green]", border_style="green"))
    else:
        console.print(Panel(t2_panel, title="[bold red]TEST 2: HARDWARE PRECISION MATCH [FAILED][/bold red]", border_style="red"))
    
    assert len(hw_facts) >= 2, f"Expected >= 2 facts, but retrieved {len(hw_facts)}"

    # -------------------------------------------------------------------------
    # TEST 3: CONTEXT RETRIEVAL (LLM Pipeline Context Builder)
    # -------------------------------------------------------------------------
    context_out = memory.get_trimmed_context(hardware_query, subject="user", similarity_threshold=0.15)
    
    t3_panel = f"[bold white]Generated Context for LLM:[/bold white]\n{context_out}"
    console.print(Panel(t3_panel, title="[bold green]TEST 3: LLM CONTEXT PIPELINE [PASSED][/bold green]", border_style="green"))
    assert len(context_out) > 0, "Context output is empty!"

    # Cleanup temporary test indexes
    memory.clear()
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(faiss_path):
        os.remove(faiss_path)

    console.print(Panel.fit(
        "[bold green]ALL VECTOR MEMORY TESTS PASSED SUCCESSFULLY![/bold green]",
        border_style="bold green"
    ))

if __name__ == "__main__":
    run_tests()