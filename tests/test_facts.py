# test_facts.py
from core.memory.semantic_memory import SemanticMemory

mem = SemanticMemory()

# 1. Fact Input / Insertion
print("--- SAVING FACTS ---")
mem.remember(
    subject="user",
    predicate="prefers_editor",
    value="MT Manager and VS Code",
)
mem.remember(
    subject="user", predicate="audio_setup", value="KZ EDC Pro with DAC"
)
mem.remember(
    subject="project", predicate="running_on", value="Termux PRoot ARM64"
)
print("Facts saved successfully!\n")

# 2. Hybrid Search Test Queries
queries = [
    "Which code editors do I use?",
    "Tell me about my earphone setup",
    "Where is this project hosted?",
]

print("--- TESTING RECALL ---")
for q in queries:
  results = mem.hybrid_search(q, limit=1)
  if results:
    r = results[0]
    print(f"Query: '{q}'")
    print(f"➜ Matched Fact: {r.subject} -> {r.predicate} -> {r.value}\n")
  else:
    print(f"Query: '{q}' ➜ No match found\n")
