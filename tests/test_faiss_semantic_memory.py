import sys
from core.memory.semantic_memory import Knowledge, SemanticMemory


import pytest


@pytest.fixture
def memory(tmp_path):
    """Provides a isolated SemanticMemory instance using temporary disk files."""
    db_file = str(tmp_path / "test_memory.db")
    faiss_file = str(tmp_path / "test_faiss.index")
    mem = SemanticMemory(
        db_path=db_file, faiss_index_path=faiss_file, max_knowledge=5
    )
    yield mem
    mem.clear()


# =============================================================
# 1. CORE CRUD OPERATIONS (remember, get, forget)
# =============================================================


def test_remember_creates_new_record(memory):
    item = memory.remember(
        subject="Python",
        predicate="is_a",
        value="programming language",
        confidence=0.9,
        importance=0.8,
        tags=["coding", "tech"],
    )

    assert isinstance(item, Knowledge)
    assert item.subject == "python"  # Normalized
    assert item.predicate == "is_a"
    assert item.value == "programming language"
    assert item.confidence == 0.9
    assert "coding" in item.tags
    assert memory.count == 1


def test_remember_reinforces_existing(memory):
    item1 = memory.remember("Python", "is_a", "programming language", confidence=0.5)
    item2 = memory.remember("Python", "is_a", "programming language", confidence=0.9)

    assert item1.knowledge_id == item2.knowledge_id
    assert item2.evidence_count == 2
    assert item2.confidence > 0.5  # Confidence merged
    assert memory.count == 1


def test_get_retrieves_item(memory):
    item = memory.remember("JARVIS", "is", "AI assistant")
    retrieved = memory.get(item.knowledge_id)

    assert retrieved is not None
    assert retrieved.knowledge_id == item.knowledge_id
    assert retrieved.subject == "jarvis"


def test_forget_deletes_everywhere(memory):
    item = memory.remember("Earth", "orbits", "Sun")
    k_id = item.knowledge_id

    # Verify exists
    assert memory.get(k_id) is not None
    assert len(memory.get_graph_relations("earth")) == 1

    # Delete
    deleted = memory.forget(k_id)

    assert deleted is True
    assert memory.get(k_id) is None
    assert memory.count == 0
    assert len(memory.get_graph_relations("earth")) == 0
    assert memory.semantic_search("Earth", top_k=1) == []


# =============================================================
# 2. SEARCH & RETRIEVAL (find, search, semantic_search, graph)
# =============================================================


def test_find_by_wildcard(memory):
    memory.remember("cat", "is_a", "feline")
    memory.remember("cat", "likes", "fish")

    all_cat = memory.find("cat")
    assert len(all_cat) == 2

    specific = memory.find("cat", predicate="likes")
    assert len(specific) == 1
    assert specific[0].value == "fish"


def test_find_by_subject_predicate_and_tag(memory):
    memory.remember("dog", "is_a", "canine", tags=["pet", "animal"])
    memory.remember("cat", "is_a", "feline", tags=["pet"])

    by_sub = memory.find_by_subject("dog")
    assert len(by_sub) == 1

    by_pred = memory.find_by_predicate("is_a")
    assert len(by_pred) == 2

    by_tag = memory.find_by_tag("animal")
    assert len(by_tag) == 1
    assert by_tag[0].subject == "dog"


def test_lexical_search(memory):
    memory.remember("quantum computing", "uses", "qubits")
    results = memory.search("qubits")

    assert len(results) == 1
    assert results[0].subject == "quantum computing"


def test_semantic_search_faiss(memory):
    memory.remember("apple", "is_a", "delicious red fruit")
    memory.remember("boeing 747", "is_a", "commercial jet aircraft")

    results = memory.semantic_search("orchard produce", top_k=1)
    assert len(results) == 1
    assert results[0].subject == "apple"


def test_get_graph_relations(memory):
    memory.remember("France", "capital_is", "Paris")
    relations = memory.get_graph_relations("France")

    assert len(relations) == 1
    assert relations[0]["target"] == "paris"
    assert relations[0]["predicate"] == "capital_is"


# =============================================================
# 3. CONFIDENCE & STATE MODIFIERS
# =============================================================


def test_confidence_modifiers(memory):
  item = memory.remember("hypothesis", "is", "untested", confidence=0.5)
  k_id = item.knowledge_id

  memory.update_confidence(k_id, 0.7)
  assert memory.get(k_id).confidence == pytest.approx(0.7)

  memory.reinforce(k_id, confidence_delta=0.1)
  assert memory.get(k_id).confidence == pytest.approx(0.8)

  memory.weaken(k_id, confidence_delta=0.3)
  assert memory.get(k_id).confidence == pytest.approx(0.5)



# =============================================================
# 4. CAPACITY, PRUNING & SNAPSHOTS
# =============================================================


def test_pruning_on_max_capacity(memory):
    # Max knowledge is set to 5 in fixture
    for i in range(6):
        memory.remember(f"item_{i}", "has_index", i, importance=i / 10.0)

    # Oldest/lowest importance item should be pruned
    assert memory.count == 5
    assert memory.find_by_subject("item_0") == []


def test_snapshot_and_restore(memory):
    memory.remember("Alpha", "connects_to", "Beta")
    memory.remember("Gamma", "connects_to", "Delta")

    snap = memory.snapshot()
    assert snap["count"] == 2

    memory.clear()
    assert memory.count == 0

    memory.restore(snap)
    assert memory.count == 2
    assert len(memory.find("alpha")) == 1
