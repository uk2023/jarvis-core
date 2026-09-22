# test_memory.py
from core.memory.semantic_memory import SemanticMemory

print("Initializing SemanticMemory...")
mem = SemanticMemory()

print("Testing remember()...")
mem.remember(
    subject="jarvis",
    predicate="uses_memory_store",
    value="faiss with onnx runtime for low ram",
)

print("Testing hybrid_search()...")
results = mem.hybrid_search("What vector database does Jarvis use?")

for r in results:
  print(f"[FOUND] Subject: {r.subject} | Predicate: {r.predicate} | Value: {r.value}")
