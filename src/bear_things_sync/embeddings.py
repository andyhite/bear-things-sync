"""Embedding generation and similarity matching for todo deduplication."""

import os
from functools import lru_cache
from typing import Optional

# Disable tokenizers parallelism to avoid fork warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """
    Load and cache the embedding model in memory.

    Returns:
        Cached SentenceTransformer model
    """
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def generate_embedding(text: str) -> list[float]:
    """
    Generate embedding vector for text.

    Args:
        text: Text to embed

    Returns:
        384-dimensional embedding vector
    """
    model = get_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def calculate_similarity(embedding1: list[float], embedding2: list[float]) -> float:
    """
    Calculate cosine similarity between two embeddings.

    Args:
        embedding1: First embedding vector
        embedding2: Second embedding vector

    Returns:
        Similarity score between 0 and 1 (1 = identical)
    """
    return float(cosine_similarity([embedding1], [embedding2])[0][0])


def find_most_similar(
    target_text: str, candidates: list[dict], threshold: float = 0.85
) -> Optional[tuple[str, float]]:
    """
    Find the most similar candidate above threshold.

    Args:
        target_text: Text to match against
        candidates: List of dicts with keys: id, text, embedding
        threshold: Minimum similarity score (0-1)

    Returns:
        Tuple of (candidate_id, similarity_score) or None if no match above threshold
    """
    if not candidates:
        return None

    target_embedding = generate_embedding(target_text)

    best_match = None
    best_score = threshold

    for candidate in candidates:
        score = calculate_similarity(target_embedding, candidate["embedding"])
        if score > best_score:
            best_score = score
            best_match = candidate["id"]

    return (best_match, best_score) if best_match else None
