from core.organism.bootstrap import create_jarvis


def test_memory_episodic_persistence():
    jarvis = create_jarvis()
    memory = jarvis.get_organ("memory")

    episode = memory.remember_experience(
        event_type="PYTEST_EPISODIC",
        context={
            "message": "pytest episodic test"
        },
        importance=0.9,
        tags=["pytest"],
    )

    assert episode is not None
    assert episode.event_type == "PYTEST_EPISODIC"

    jarvis.stop()

    # Recreate JARVIS to verify SQLite persistence.
    jarvis2 = create_jarvis()
    memory2 = jarvis2.get_organ("memory")

    results = memory2.find_experiences(
        event_type="PYTEST_EPISODIC",
        limit=10,
    )

    assert len(results) >= 1
    assert results[-1].context["message"] == (
        "pytest episodic test"
    )

    jarvis2.stop()


def test_memory_semantic_persistence():
    jarvis = create_jarvis()
    memory = jarvis.get_organ("memory")

    knowledge = memory.remember_knowledge(
        subject="pytest",
        predicate="is",
        value="testing framework",
        confidence=0.95,
        importance=0.8,
        tags=["pytest"],
    )

    assert knowledge is not None
    assert knowledge.subject == "pytest"

    jarvis.stop()

    # Recreate JARVIS to verify SQLite persistence.
    jarvis2 = create_jarvis()
    memory2 = jarvis2.get_organ("memory")

    results = memory2.get_knowledge(
        "pytest"
    )

    assert len(results) >= 1
    assert results[-1].value == "testing framework"

    jarvis2.stop()