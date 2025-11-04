# Embedding-Based Todo Deduplication Design

**Date:** 2025-11-03
**Status:** Approved

## Overview

Add semantic similarity matching to detect and merge duplicate todos when syncing from Bear to Things 3. This prevents creating new todos when semantically similar incomplete todos already exist in Things.

## Problem

Current system uses content-based IDs (hash of todo text) for deduplication. This catches exact duplicates but misses semantically similar todos:
- "Review project slides" vs "Go through presentation deck"
- "Finish report" vs "Complete documentation"
- Manual todos in Things that match Bear todos

Users end up with multiple similar todos across their Things projects.

## Solution

Use sentence embeddings to detect semantic similarity and merge with existing incomplete Things todos instead of creating duplicates.

## Architecture

### Data Flow

1. Bear note changes → `fswatch` triggers sync
2. Extract todos from Bear notes
3. Generate content-based ID (existing behavior)
4. Check if ID exists in state → skip if found (existing behavior)
5. **NEW:** Generate embedding for todo text
6. **NEW:** Query Things 3 for incomplete todos (project-scoped)
7. **NEW:** Generate embeddings for existing Things todos (with caching)
8. **NEW:** Find closest match above 0.85 threshold
9. **NEW:** If duplicate found → update existing todo with merge note
10. **NEW:** If no duplicate → create new todo

### Project-Scoped Search

When Bear tags match a Things project, only search within that project for duplicates. This reduces false positives by respecting project boundaries.

Example:
- Bear todo: "Review slides" with tag `#Work`
- Search only incomplete todos in Things "Work" project
- Won't match "Review slides" in "Personal" project

## Data Structures

### State Format (v4)

```python
{
  "_version": 4,
  "_embedding_cache": {
    "things_id_ABC123": {
      "text": "Review project slides",
      "embedding": [0.123, 0.456, ...],  # 384-dim vector
      "last_seen": "2025-11-03T10:30:00",
      "project": "Work"
    }
  },
  "note_id_123": {
    "title": "Note Title",
    "synced_todos": {
      "content_hash_abc": {
        "things_id": "ABC123",
        "completed": false,
        "text": "Review project slides",
        "merged_with": null
      },
      "content_hash_def": {
        "things_id": "XYZ789",
        "completed": false,
        "text": "Go through presentation deck",
        "merged_with": "XYZ789",
        "merge_note": "Merged with existing todo (similarity: 92%)"
      }
    }
  }
}
```

### Configuration

```python
# config.py additions
SIMILARITY_THRESHOLD = 0.85  # Moderate: catches semantically similar
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_CACHE_MAX_AGE_DAYS = 7
```

## Implementation Details

### Embedding Module (`embeddings.py`)

**Model:** `sentence-transformers/all-MiniLM-L6-v2`
- Size: ~80MB
- Speed: ~50ms per embedding on M1 Mac
- Quality: Good for short text similarity
- Cached in memory after first load

**Key Functions:**

```python
def get_model() -> SentenceTransformer:
    """Load and cache model in memory."""

def generate_embedding(text: str) -> list[float]:
    """Generate 384-dim embedding vector."""

def calculate_similarity(embedding1, embedding2) -> float:
    """Cosine similarity (0-1 range)."""

def find_most_similar(
    target_text: str,
    candidates: list[dict],
    threshold: float = 0.85
) -> Optional[tuple[str, float]]:
    """Find closest match above threshold."""
```

### Things 3 Integration (`things.py`)

**New Functions:**

```python
def get_incomplete_todos(project: Optional[str] = None) -> list[dict]:
    """
    Query Things 3 for incomplete todos.

    Args:
        project: Filter by project name (None = all)

    Returns:
        [{"id": "ABC", "name": "Review slides", "project": "Work"}, ...]
    """

def update_todo_notes(things_id: str, additional_note: str) -> bool:
    """Append text to existing todo's notes."""
```

**AppleScript Examples:**

```applescript
# Project-scoped query
tell application "Things3"
    set targetProject to first project whose name is "Work"
    set todoList to {}
    repeat with aTodo in to dos of targetProject
        if status of aTodo is open then
            set end of todoList to {id:(id of aTodo), name:(name of aTodo)}
        end if
    end repeat
    return todoList
end tell

# Update notes
tell application "Things3"
    set theTodo to to do id "ABC123"
    set notes of theTodo to (notes of theTodo) & "\\n\\nMerged note here"
end tell
```

### Sync Logic Updates (`sync.py`)

**Duplicate Detection Flow:**

```python
# 1. Determine search scope based on Bear tags
target_project = None
if bear_tag_matches_things_project:
    target_project = matched_project_name

# 2. Query Things (project-scoped)
things_todos = get_incomplete_todos(project=target_project)

# 3. Build candidates with cached embeddings
candidates = []
for things_todo in things_todos:
    cache_key = things_todo["id"]
    cached = state.get("_embedding_cache", {}).get(cache_key)

    if cached and cached["text"] == things_todo["name"]:
        embedding = cached["embedding"]
    else:
        embedding = generate_embedding(things_todo["name"])
        # Cache for future syncs
        state.setdefault("_embedding_cache", {})[cache_key] = {
            "text": things_todo["name"],
            "embedding": embedding,
            "last_seen": datetime.now().isoformat(),
            "project": things_todo.get("project")
        }

    candidates.append({
        "id": things_todo["id"],
        "text": things_todo["name"],
        "embedding": embedding
    })

# 4. Find best match
match = find_most_similar(todo["text"], candidates, threshold=0.85)

if match:
    things_id, similarity = match
    # Update existing todo
    merge_note = f"\n\n---\nMerged with todo from Bear note: {note_title}\n(Similarity: {similarity:.2%})"
    update_todo_notes(things_id, merge_note)

    # Track as merged in state
    state[note_id]["synced_todos"][todo_id] = {
        "things_id": things_id,
        "completed": False,
        "text": todo["text"],
        "merged_with": things_id,
        "merge_note": f"Merged (similarity: {similarity:.2%})"
    }
else:
    # No duplicate, create new todo (existing logic)
    things_id = create_todo(...)
```

**Cache Maintenance:**

- Remove embeddings not seen in 7+ days
- Run during each sync to prevent state bloat
- User can delete cache to force rebuild

## Error Handling

### Graceful Degradation

All embedding operations wrapped in try/except. On any error, fall back to existing behavior (content-based ID only, no semantic deduplication).

```python
def try_find_duplicate(...) -> Optional[tuple[str, float]]:
    try:
        # Embedding logic...
    except Exception as e:
        log(f"Deduplication failed, falling back: {e}", "WARNING")
        return None
```

### Specific Cases

**Model download fails (first run, no internet):**
- Log: "Embedding model not available, skipping deduplication"
- Continue sync without deduplication

**Things query fails:**
- Use existing retry logic with backoff
- If all retries fail, skip deduplication

**Cache corruption:**
- Clear `_embedding_cache` and rebuild
- Log warning, continue

**Update notes fails:**
- Retry with existing backoff
- If all retries fail, create new todo instead (user merges manually)

### First-Run Experience

Model downloads on first sync (~80MB, 10-30 seconds):
- Show: "Downloading embedding model for deduplication..."
- Cache in `~/.cache/torch/sentence_transformers/`
- Only happens once

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    "sentence-transformers>=2.2.0",
    "scikit-learn>=1.3.0",  # For cosine_similarity
]
```

This breaks the "stdlib-only production" constraint but adds significant value.

## Testing Strategy

### Unit Tests (Fast, Mocked)

```python
# tests/test_embeddings.py
def test_generate_embedding():
    """Mock sentence_transformers model"""

def test_find_most_similar_above_threshold():
    """Test similarity matching with controlled scores"""

def test_find_most_similar_below_threshold():
    """Test no match when all scores < 0.85"""
```

### Integration Tests

```python
# tests/test_things.py
def test_get_incomplete_todos(mocker):
    """Mock AppleScript to return incomplete todos"""

def test_get_incomplete_todos_project_scoped(mocker):
    """Test project filtering"""

def test_update_todo_notes(mocker):
    """Mock AppleScript for updating notes"""
```

### Sync Tests (End-to-End)

```python
# tests/test_sync.py
def test_sync_with_duplicate_found(mocker):
    """Test merging with existing Things todo"""
    # Should update, not create

def test_sync_with_no_duplicate(mocker):
    """Test creating new todo when no match"""

def test_sync_with_embedding_failure(mocker):
    """Test fallback when embeddings fail"""

def test_sync_with_project_scope(mocker):
    """Test project-scoped duplicate search"""
```

### Manual Testing Checklist

- [ ] First run downloads model successfully
- [ ] Duplicate detection works across projects
- [ ] Project-scoped search limits false positives
- [ ] Cache persists between syncs
- [ ] Merge notes appear in Things
- [ ] Fallback works when embeddings fail
- [ ] Performance: sync completes in <5s with 50 todos

## Performance Considerations

**Per-sync overhead:**
- Query Things: ~200ms (AppleScript)
- Generate embeddings for new todos: ~50ms each
- Cached embeddings: no overhead
- Similarity comparison: <1ms per candidate

**Example:**
- 10 new Bear todos
- 50 existing Things todos (40 cached, 10 new)
- Total: ~1.2s overhead (acceptable)

**Memory:**
- Model: ~80MB (loaded once)
- Embeddings: ~1.5KB per todo
- 1000 todos cached: ~1.5MB

## Migration

State v3 → v4:
1. Add `_embedding_cache` dict
2. Add `merged_with` and `merge_note` fields to todos
3. Existing todos continue working (no breaking changes)

## Future Improvements

- Configurable threshold in config file
- Dashboard showing merge statistics
- Manual "force merge" command for specific todos
- Cross-project duplicate detection (opt-in)
- Alternative embedding models for different use cases

## Success Metrics

- Fewer duplicate todos in Things
- User reports less manual cleanup needed
- Sync performance remains acceptable (<5s)
- No increase in sync failures
