"""Tests for embedding generation and similarity matching."""

import numpy as np


def test_generate_embedding(mocker):
    """Test embedding generation with mocked model."""
    from bear_things_sync.embeddings import generate_embedding

    # Mock the SentenceTransformer model
    mock_model = mocker.MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mocker.patch("bear_things_sync.embeddings.get_model", return_value=mock_model)

    embedding = generate_embedding("test todo")

    assert len(embedding) == 3
    assert embedding == [0.1, 0.2, 0.3]
    mock_model.encode.assert_called_once_with("test todo", convert_to_numpy=True)


def test_calculate_similarity(mocker):
    """Test similarity calculation."""
    from bear_things_sync.embeddings import calculate_similarity

    # Mock cosine_similarity
    mocker.patch(
        "bear_things_sync.embeddings.cosine_similarity",
        return_value=np.array([[0.92]]),
    )

    embedding1 = [0.9, 0.1, 0.0]
    embedding2 = [0.85, 0.15, 0.0]

    similarity = calculate_similarity(embedding1, embedding2)

    assert similarity == 0.92


def test_find_most_similar_above_threshold(mocker):
    """Test finding most similar candidate above threshold."""
    from bear_things_sync.embeddings import find_most_similar

    # Mock generate_embedding to return target embedding
    mocker.patch(
        "bear_things_sync.embeddings.generate_embedding",
        return_value=[0.95, 0.05, 0.0],
    )

    # Mock cosine_similarity to return controlled values
    # First call: 0.92 (A), second call: 0.45 (B)
    mock_sim = mocker.patch("bear_things_sync.embeddings.cosine_similarity")
    mock_sim.side_effect = [np.array([[0.92]]), np.array([[0.45]])]

    candidates = [
        {"id": "A", "text": "Review slides", "embedding": [0.9, 0.1, 0.0]},
        {"id": "B", "text": "Different task", "embedding": [0.1, 0.9, 0.0]},
    ]

    match = find_most_similar("Review the slides", candidates, threshold=0.85)

    assert match is not None
    assert match[0] == "A"  # ID
    assert match[1] == 0.92  # Similarity score


def test_find_most_similar_below_threshold(mocker):
    """Test no match when all candidates below threshold."""
    from bear_things_sync.embeddings import find_most_similar

    # Mock generate_embedding
    mocker.patch(
        "bear_things_sync.embeddings.generate_embedding",
        return_value=[0.5, 0.5, 0.0],
    )

    # Mock cosine_similarity to return low scores
    mock_sim = mocker.patch("bear_things_sync.embeddings.cosine_similarity")
    mock_sim.side_effect = [np.array([[0.70]]), np.array([[0.65]])]

    candidates = [
        {"id": "A", "text": "Review slides", "embedding": [0.9, 0.1, 0.0]},
        {"id": "B", "text": "Different task", "embedding": [0.1, 0.9, 0.0]},
    ]

    match = find_most_similar("Completely different todo", candidates, threshold=0.85)

    assert match is None


def test_find_most_similar_empty_candidates(mocker):
    """Test with no candidates."""
    from bear_things_sync.embeddings import find_most_similar

    # Mock generate_embedding (shouldn't be called)
    mock_gen = mocker.patch("bear_things_sync.embeddings.generate_embedding")

    match = find_most_similar("Some todo", [], threshold=0.85)

    assert match is None
    mock_gen.assert_not_called()


def test_find_most_similar_picks_highest(mocker):
    """Test that it picks the highest scoring candidate."""
    from bear_things_sync.embeddings import find_most_similar

    # Mock generate_embedding
    mocker.patch(
        "bear_things_sync.embeddings.generate_embedding",
        return_value=[0.9, 0.1, 0.0],
    )

    # Mock cosine_similarity to return different scores
    mock_sim = mocker.patch("bear_things_sync.embeddings.cosine_similarity")
    mock_sim.side_effect = [
        np.array([[0.88]]),  # A
        np.array([[0.95]]),  # B (highest)
        np.array([[0.90]]),  # C
    ]

    candidates = [
        {"id": "A", "text": "Review slides", "embedding": [0.88, 0.12, 0.0]},
        {"id": "B", "text": "Review presentation", "embedding": [0.92, 0.08, 0.0]},
        {"id": "C", "text": "Check slides", "embedding": [0.90, 0.10, 0.0]},
    ]

    match = find_most_similar("Review the slides", candidates, threshold=0.85)

    assert match is not None
    assert match[0] == "B"  # Should pick B (highest score)
    assert match[1] == 0.95


def test_model_caching(mocker):
    """Test that model is cached and only loaded once."""
    from bear_things_sync.embeddings import generate_embedding, get_model

    # Clear any existing cache
    get_model.cache_clear()

    # Mock SentenceTransformer
    mock_transformer_class = mocker.patch("bear_things_sync.embeddings.SentenceTransformer")
    mock_model = mocker.MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_transformer_class.return_value = mock_model

    # Call generate_embedding multiple times
    generate_embedding("test 1")
    generate_embedding("test 2")
    generate_embedding("test 3")

    # SentenceTransformer should only be instantiated once (cached)
    assert mock_transformer_class.call_count == 1
    # But encode should be called 3 times
    assert mock_model.encode.call_count == 3
