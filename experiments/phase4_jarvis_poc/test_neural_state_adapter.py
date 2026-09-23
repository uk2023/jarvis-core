from neural_state_adapter import NeuralStateAdapter


def test_adapter_is_deterministic():
    a = NeuralStateAdapter()
    b = NeuralStateAdapter()

    state_a = a.process(1.0)
    state_b = b.process(1.0)

    assert state_a == state_b


def test_adapter_is_bounded():
    adapter = NeuralStateAdapter()

    result = adapter.process(1.0)

    assert 0.0 <= result["mean_activity"] <= 1.0
    assert 0.0 <= result["max_activity"] <= 1.0
    assert result["active_nodes"] > 0


def test_adapter_accepts_normalized_signal():
    adapter = NeuralStateAdapter()

    result = adapter.process(0.2)

    assert result["input_signal"] == 0.2
