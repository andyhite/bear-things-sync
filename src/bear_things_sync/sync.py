"""Main sync logic for Bear to Things 3."""

import time
from datetime import datetime, timedelta
from typing import Optional

from .bear import complete_todo_in_note, extract_todos, get_notes_with_todos
from .config import (
    BIDIRECTIONAL_SYNC,
    EMBEDDING_CACHE_MAX_AGE_DAYS,
    SIMILARITY_THRESHOLD,
    SYNC_COOLDOWN,
    THINGS_SYNC_TAG,
)
from .things import (
    complete_todo,
    create_todo,
    get_incomplete_todos,
    get_projects,
    update_todo_notes,
)
from .things_db import get_completed_things_todos
from .utils import (
    cleanup_state,
    find_todo_by_fuzzy_match,
    generate_todo_id,
    load_state,
    log,
    pascal_to_title_case,
    pluralize,
    save_state,
    send_notification,
)

try:
    from .embeddings import find_most_similar, generate_embedding

    EMBEDDINGS_AVAILABLE = True
except Exception as e:
    EMBEDDINGS_AVAILABLE = False
    log(f"Embeddings not available, deduplication disabled: {e}", "WARNING")


def _migrate_to_v3(state: dict) -> None:
    """
    Migrate state from v2 (line-based IDs) to v3 (content-based IDs).

    This migration cannot preserve exact mappings since we don't have the
    original todo text. New syncs will use content-based IDs going forward.
    Old synced todos will remain tracked but may create duplicates if the
    same todo appears at different line numbers.

    Args:
        state: The state dict to migrate (modified in place)
    """
    migrated_notes = 0
    for note_id in list(state.keys()):
        # Skip metadata keys
        if note_id.startswith("_"):
            continue

        # Check if this note has synced_todos
        if "synced_todos" in state[note_id]:
            synced_todos = state[note_id]["synced_todos"]

            # Handle v1 format (list) - convert to dict first
            if isinstance(synced_todos, list):
                state[note_id]["synced_todos"] = {
                    tid: {
                        "things_id": None,
                        "completed": False,
                        "text": f"[migrated from v1: {tid}]",
                    }
                    for tid in synced_todos
                }
                synced_todos = state[note_id]["synced_todos"]
                migrated_notes += 1
            # Handle v2 format (dict with line-based IDs)
            elif isinstance(synced_todos, dict):
                has_line_based_ids = any(
                    ":" in todo_id and todo_id.split(":")[-1].isdigit() for todo_id in synced_todos
                )

                if has_line_based_ids:
                    # Add text field if missing (for fuzzy matching in future)
                    for todo_id, todo_state in synced_todos.items():
                        if "text" not in todo_state:
                            # We can't recover the original text, just mark it
                            todo_state["text"] = f"[migrated from v2: {todo_id}]"
                    migrated_notes += 1

    if migrated_notes > 0:
        log(
            f"Migrated {migrated_notes} notes to v3 format. New syncs will use content-based IDs.",
            "WARNING",
        )


def _migrate_to_v4(state: dict) -> None:
    """
    Migrate state from v3 to v4 (add embedding cache).

    Args:
        state: The state dict to migrate (modified in place)
    """
    # Add embedding cache if not present
    if "_embedding_cache" not in state:
        state["_embedding_cache"] = {}
        log("Added embedding cache to state", "INFO")

    # Add merged_with field to existing synced todos if missing
    migrated_count = 0
    for note_id in list(state.keys()):
        if note_id.startswith("_"):
            continue

        if "synced_todos" in state[note_id]:
            synced_todos = state[note_id]["synced_todos"]
            if isinstance(synced_todos, dict):
                for _todo_id, todo_state in synced_todos.items():
                    if "merged_with" not in todo_state:
                        todo_state["merged_with"] = None
                        migrated_count += 1

    if migrated_count > 0:
        log(f"Added merged_with field to {migrated_count} existing todos", "INFO")


def _cleanup_embedding_cache(state: dict) -> int:
    """
    Remove stale embeddings from cache (not seen in EMBEDDING_CACHE_MAX_AGE_DAYS days).

    Args:
        state: State dict containing embedding cache

    Returns:
        Number of cache entries removed
    """
    if "_embedding_cache" not in state:
        return 0

    cache = state["_embedding_cache"]
    cutoff_date = datetime.now() - timedelta(days=EMBEDDING_CACHE_MAX_AGE_DAYS)
    removed_count = 0

    for cache_key in list(cache.keys()):
        cached_entry = cache[cache_key]
        last_seen_str = cached_entry.get("last_seen")

        if not last_seen_str:
            # No last_seen timestamp, remove it
            del cache[cache_key]
            removed_count += 1
            continue

        try:
            last_seen = datetime.fromisoformat(last_seen_str)
            if last_seen < cutoff_date:
                del cache[cache_key]
                removed_count += 1
        except (ValueError, TypeError):
            # Invalid timestamp, remove it
            del cache[cache_key]
            removed_count += 1

    return removed_count


def _try_find_duplicate(
    todo_text: str, target_project: Optional[str], state: dict
) -> Optional[tuple[str, float]]:
    """
    Try to find a duplicate todo in Things using embeddings.

    Args:
        todo_text: Text of the todo to check
        target_project: Project name to scope search (None = all todos)
        state: State dict for caching embeddings

    Returns:
        Tuple of (things_id, similarity_score) or None if no match/error
    """
    if not EMBEDDINGS_AVAILABLE:
        return None

    try:
        # Query Things for incomplete todos
        things_todos = get_incomplete_todos(project=target_project)
        if not things_todos:
            return None

        # Build candidates with cached embeddings
        candidates = []
        for things_todo in things_todos:
            cache_key = things_todo["id"]
            cached = state.get("_embedding_cache", {}).get(cache_key)

            # Use cached embedding if valid
            if cached and cached.get("text") == things_todo["name"]:
                embedding = cached["embedding"]
            else:
                # Generate and cache new embedding
                embedding = generate_embedding(things_todo["name"])
                state.setdefault("_embedding_cache", {})[cache_key] = {
                    "text": things_todo["name"],
                    "embedding": embedding,
                    "last_seen": datetime.now().isoformat(),
                    "project": things_todo.get("project"),
                }

            candidates.append(
                {
                    "id": things_todo["id"],
                    "text": things_todo["name"],
                    "embedding": embedding,
                }
            )

        # Find most similar todo above threshold
        return find_most_similar(todo_text, candidates, threshold=SIMILARITY_THRESHOLD)

    except Exception as e:
        log(f"Deduplication failed, falling back to normal sync: {e}", "WARNING")
        return None


def _migrate_to_v5(state: dict) -> None:
    """
    Migrate state from v4 to v5 (add bi-directional sync tracking).

    Adds global and per-todo timestamp/source tracking for cooldown logic.

    Args:
        state: The state dict to migrate (modified in place)
    """
    # Add global tracking fields
    if "_last_sync_time" not in state:
        state["_last_sync_time"] = 0

    if "_last_sync_source" not in state:
        state["_last_sync_source"] = "bear"

    # Add per-todo tracking fields
    migrated_todos = 0
    for note_id in list(state.keys()):
        if note_id.startswith("_"):
            continue

        if "synced_todos" in state[note_id]:
            for _todo_id, todo_state in state[note_id]["synced_todos"].items():
                if "last_modified_time" not in todo_state:
                    todo_state["last_modified_time"] = 0
                    todo_state["last_modified_source"] = "bear"
                    migrated_todos += 1

    if migrated_todos > 0:
        log(f"Migrated {migrated_todos} todos to v5 format with bi-directional sync tracking")


def should_skip_sync(state: dict, source: str) -> bool:
    """
    Check if we should skip this sync to avoid circular updates.

    Args:
        state: Current state dict
        source: Which app triggered the sync ('bear' or 'things')

    Returns:
        True if sync should be skipped, False otherwise
    """
    last_sync_time = state.get("_last_sync_time", 0)
    last_sync_source = state.get("_last_sync_source")
    time_since_last = time.time() - last_sync_time

    # Skip if we just synced from the opposite source
    # (i.e., we probably triggered this change)
    if time_since_last < SYNC_COOLDOWN:
        opposite_source = "things" if source == "bear" else "bear"
        if last_sync_source == opposite_source:
            return True

    return False


def _sync_from_things(state: dict) -> None:
    """
    Handle Things 3 → Bear sync (completions only).

    Args:
        state: Current state dict
    """
    log("Syncing completions from Things 3 to Bear...")

    # Get current Bear notes to access note content
    notes = get_notes_with_todos()
    notes_by_id = {note["id"]: note for note in notes}

    # Collect all synced Things IDs from state
    all_things_ids = []
    note_todos_map = {}  # Map things_id -> (note_id, todo_id, todo_text)

    for note_id, note_data in state.items():
        if note_id.startswith("_"):
            continue

        if "synced_todos" in note_data:
            for todo_id, todo_state in note_data["synced_todos"].items():
                things_id = todo_state.get("things_id")
                if things_id and not todo_state.get("completed", False):
                    all_things_ids.append(things_id)
                    note_todos_map[things_id] = (note_id, todo_id, todo_state.get("text", ""))

    if not all_things_ids:
        log("No synced incomplete todos to check")
        return

    # Query Things 3 for completed todos
    completed_ids = get_completed_things_todos(all_things_ids)

    if not completed_ids:
        log("No todos completed in Things 3")
        return

    # Mark corresponding todos complete in Bear
    completed_count = 0
    for things_id in completed_ids:
        if things_id in note_todos_map:
            note_id, todo_id, todo_text = note_todos_map[things_id]

            # Get note content
            if note_id not in notes_by_id:
                log(f"WARNING: Note {note_id} not found in Bear database", "WARNING")
                continue

            note_content = notes_by_id[note_id]["content"]

            # Mark complete in Bear via x-callback-url
            if complete_todo_in_note(note_id, todo_text, note_content):
                # Update state
                state[note_id]["synced_todos"][todo_id]["completed"] = True
                state[note_id]["synced_todos"][todo_id]["last_modified_time"] = time.time()
                state[note_id]["synced_todos"][todo_id]["last_modified_source"] = "things"
                completed_count += 1
                log(f"✓ Completed in Bear: '{todo_text}'")
            else:
                log(f"✗ Failed to complete in Bear: '{todo_text}'")

    if completed_count > 0:
        summary = f"Completed {pluralize(completed_count, 'todo')} in Bear from Things 3"
        log(summary)
        send_notification("Bear Things Sync", summary, sound=False)


def sync(source: str = "bear") -> None:
    """
    Main sync function with bi-directional support.

    Args:
        source: Which app triggered the sync ('bear' or 'things')

    Behavior based on source:
    - 'bear': Syncs new incomplete todos from Bear to Things 3, marks completed in Things
    - 'things': Marks todos complete in Bear if completed in Things 3
    """
    log(f"Starting sync (triggered by {source.title()})...")

    state = load_state()

    # Add state version if not present (for future migrations)
    if "_version" not in state:
        state["_version"] = 2  # Version 2: dict-based synced_todos

    # Migrate to version 3: content-based todo IDs (instead of line-based)
    if state.get("_version", 2) < 3:
        log("Migrating state format to v3 (content-based todo IDs)...", "WARNING")
        _migrate_to_v3(state)
        state["_version"] = 3

    # Migrate to version 4: add embedding cache and merged_with field
    if state.get("_version", 3) < 4:
        log("Migrating state format to v4 (embedding cache)...", "INFO")
        _migrate_to_v4(state)
        state["_version"] = 4

    # Migrate to version 5: add bi-directional sync tracking
    if state.get("_version", 4) < 5:
        log("Migrating state format to v5 (bi-directional sync)...", "INFO")
        _migrate_to_v5(state)
        state["_version"] = 5

    # Check cooldown to prevent circular syncs
    if BIDIRECTIONAL_SYNC and should_skip_sync(state, source):
        log(f"Skipping sync (cooldown period after {state.get('_last_sync_source')} sync)")
        return

    # Handle Things 3 → Bear sync (completions only)
    if source == "things" and BIDIRECTIONAL_SYNC:
        _sync_from_things(state)
        # Update sync timestamp
        state["_last_sync_time"] = time.time()
        state["_last_sync_source"] = "things"
        save_state(state)
        return

    # Handle Bear → Things 3 sync (default behavior)

    notes = get_notes_with_todos()

    if not notes:
        log("No notes with todos found")
        return

    # Get Things 3 projects for matching
    things_projects = get_projects()
    if things_projects:
        log(f"Found {len(things_projects)} Things projects for tag matching")
    else:
        # Things 3 not available - check if it's running
        from .things import is_things_available

        if not is_things_available():
            error_msg = (
                "Things 3 is not running. Todos will not be synced until Things 3 is launched."
            )
            log(f"WARNING: {error_msg}", "WARNING")
            log("The daemon will automatically retry on the next Bear database change.", "WARNING")
            # Send notification to user
            send_notification("Bear Things Sync", error_msg, sound=False)
            return

    synced_count = 0
    completed_count = 0

    # Collect current note IDs for cleanup
    current_note_ids = {note["id"] for note in notes}

    for note in notes:
        note_id = note["id"]
        note_title = note["title"]

        # Initialize state for this note if needed
        if note_id not in state:
            state[note_id] = {
                "title": note_title,
                "synced_todos": {},  # Dict mapping todo_id to {'things_id': ..., 'completed': ...}
            }

        # Note: v1->v2 migration is now handled in _migrate_to_v3() called above
        # No need for per-note migration here anymore

        todos = extract_todos(note["content"])

        # Build a map of current todos by their content-based ID
        current_todos = {}
        for todo in todos:
            todo_id = generate_todo_id(note_id, todo["text"])
            current_todos[todo_id] = todo

        # Check existing synced todos for completion status changes
        for todo_id, todo_state in list(state[note_id]["synced_todos"].items()):
            current_todo = None

            # Try exact ID match first
            if todo_id in current_todos:
                current_todo = current_todos[todo_id]
            # Try fuzzy match if exact ID not found (handles text edits)
            elif "text" in todo_state:
                fuzzy_id = find_todo_by_fuzzy_match(
                    todo_state["text"], state[note_id]["synced_todos"], note_id
                )
                if fuzzy_id and fuzzy_id in current_todos:
                    current_todo = current_todos[fuzzy_id]
                    # Update to new ID if text was modified
                    if fuzzy_id != todo_id:
                        log(f"Todo text changed, updating ID: {todo_id} -> {fuzzy_id}", "WARNING")
                        state[note_id]["synced_todos"][fuzzy_id] = todo_state
                        del state[note_id]["synced_todos"][todo_id]
                        todo_id = fuzzy_id

            if (
                current_todo
                and current_todo["completed"]
                and not todo_state.get("completed", False)
            ):
                # If todo is now completed in Bear but not marked complete in our state
                things_id = todo_state.get("things_id")
                if things_id:
                    if complete_todo(things_id):
                        state[note_id]["synced_todos"][todo_id]["completed"] = True
                        completed_count += 1
                        log(f"✓ Completed: '{current_todo['text']}' in '{note_title}'")
                    else:
                        log(f"✗ Failed to complete: '{current_todo['text']}' in '{note_title}'")

        # Sync new incomplete todos
        for todo in todos:
            # Only sync incomplete todos
            if todo["completed"]:
                continue

            # Create unique ID for this todo (content-based)
            todo_id = generate_todo_id(note_id, todo["text"])

            # Skip if already synced
            if todo_id in state[note_id]["synced_todos"]:
                continue

            # Check if this todo was already synced with slightly different text (fuzzy match)
            fuzzy_id = find_todo_by_fuzzy_match(
                todo["text"], state[note_id]["synced_todos"], note_id
            )
            if fuzzy_id:
                log(f"Todo already synced with ID: {fuzzy_id}, skipping", "WARNING")
                continue

            # Prepare todo details
            todo_title = todo["text"]
            todo_notes = (
                f"From Bear note: {note_title}\nbear://x-callback-url/open-note?id={note_id}"
            )

            # Get Bear note tags and convert PascalCase to Title Case
            bear_tags_raw = note.get("tags", [])
            bear_tags = [pascal_to_title_case(tag) for tag in bear_tags_raw]

            # Check if any Bear tag matches a Things project (case-insensitive)
            target_project = None
            matched_tag = None
            for tag in bear_tags:
                if tag.lower() in things_projects:
                    target_project = things_projects[tag.lower()]
                    matched_tag = tag
                    break

            # Build tags list: exclude the matched project tag to avoid redundancy
            remaining_tags = [tag for tag in bear_tags if tag != matched_tag]
            todo_tags = [THINGS_SYNC_TAG] + remaining_tags

            # Try to find duplicate using embeddings
            duplicate = _try_find_duplicate(todo_title, target_project, state)

            if duplicate:
                # Found duplicate - update existing todo instead of creating new
                existing_things_id, similarity = duplicate
                merge_note = (
                    f"\n\n---\n"
                    f"Merged with todo from Bear note: {note_title}\n"
                    f"(Similarity: {similarity:.2%})\n"
                    f"bear://x-callback-url/open-note?id={note_id}"
                )

                if update_todo_notes(existing_things_id, merge_note):
                    # Track as merged in state
                    state[note_id]["synced_todos"][todo_id] = {
                        "things_id": existing_things_id,
                        "completed": False,
                        "text": todo["text"],
                        "merged_with": existing_things_id,
                    }
                    synced_count += 1
                    project_info = f" in {target_project}" if target_project else ""
                    log(
                        f"↔ Merged: '{todo_title}' with existing todo{project_info} "
                        f"(similarity: {similarity:.2%})"
                    )
                else:
                    # Update failed, fall through to create new todo
                    log("Failed to merge todo, creating new instead", "WARNING")
                    duplicate = None

            if not duplicate:
                # No duplicate found or merge failed - create new todo
                things_id = create_todo(
                    title=todo_title, notes=todo_notes, tags=todo_tags, project=target_project
                )

                if things_id:
                    state[note_id]["synced_todos"][todo_id] = {
                        "things_id": things_id,
                        "completed": False,
                        "text": todo["text"],
                        "merged_with": None,
                    }
                    synced_count += 1
                    project_info = f" → {target_project}" if target_project else ""
                    log(f"✓ Synced: '{todo_title}' from '{note_title}'{project_info}")
                else:
                    log(f"✗ Failed to sync: '{todo_title}' from '{note_title}'")

    # Clean up state entries for deleted notes
    state, removed_count = cleanup_state(state, current_note_ids)
    if removed_count > 0:
        log(f"Cleaned up {pluralize(removed_count, 'deleted note')} from state")

    # Clean up stale embedding cache entries
    cache_removed = _cleanup_embedding_cache(state)
    if cache_removed > 0:
        log(f"Cleaned up {pluralize(cache_removed, 'stale embedding')} from cache")

    # Update sync timestamp for Bear sync
    state["_last_sync_time"] = time.time()
    state["_last_sync_source"] = "bear"

    save_state(state)

    # Build summary message
    summary_parts = []
    if synced_count > 0:
        summary_parts.append(f"{pluralize(synced_count, 'new todo')} synced")
    if completed_count > 0:
        summary_parts.append(f"{pluralize(completed_count, 'todo')} completed")
    if not summary_parts:
        summary_parts.append("no changes")

    summary = f"Sync complete: {', '.join(summary_parts)}"
    log(summary)

    # Send notification for completed sync if there were changes
    if synced_count > 0 or completed_count > 0:
        send_notification("Bear Things Sync", summary, sound=False)
