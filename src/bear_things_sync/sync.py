"""Main sync logic for Bear to Things 3."""

import time
from datetime import datetime, timedelta

from .bear import (
    complete_todo_in_note,
    extract_todos,
    get_notes_with_todos,
    uncomplete_todo_in_note,
)
from .config import settings
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
    Remove stale embeddings from cache (not seen in settings.embedding_cache_max_age_days days).

    Args:
        state: State dict containing embedding cache

    Returns:
        Number of cache entries removed
    """
    if "_embedding_cache" not in state:
        return 0

    cache = state["_embedding_cache"]
    cutoff_date = datetime.now() - timedelta(days=settings.embedding_cache_max_age_days)
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
    todo_text: str, target_project: str | None, state: dict
) -> tuple[str, float] | None:
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
        return find_most_similar(todo_text, candidates, threshold=settings.similarity_threshold)

    except Exception as e:
        log(f"Deduplication failed, falling back to normal sync: {e}", "WARNING")
        return None


def _migrate_to_v5(state: dict) -> None:
    """
    Migrate state from v4 to v5 (add bi-directional sync tracking).

    Adds per-todo timestamp/source tracking for ping-pong prevention.

    Args:
        state: The state dict to migrate (modified in place)
    """
    # Add global tracking fields for backward compatibility (no longer used)
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


def _sync_from_things(state: dict) -> None:
    """
    Handle Things 3 → Bear sync (completions and un-completions).

    Args:
        state: Current state dict
    """
    log("Syncing completions from Things 3 to Bear...")

    # Get current Bear notes to access note content
    notes = get_notes_with_todos()
    notes_by_id = {note["id"]: note for note in notes}

    # Collect all synced Things IDs from state (both completed and incomplete)
    incomplete_things_ids = []
    completed_things_ids = []
    incomplete_todos_map = {}  # Map things_id -> (note_id, todo_id, todo_text)
    completed_todos_map = {}  # Map things_id -> (note_id, todo_id, todo_text)

    for note_id, note_data in state.items():
        if note_id.startswith("_"):
            continue

        if "synced_todos" in note_data:
            for todo_id, todo_state in note_data["synced_todos"].items():
                things_id = todo_state.get("things_id")
                if not things_id:
                    continue

                if todo_state.get("completed", False):
                    # Track completed todos to detect un-completion
                    completed_things_ids.append(things_id)
                    completed_todos_map[things_id] = (note_id, todo_id, todo_state.get("text", ""))
                else:
                    # Track incomplete todos to detect completion
                    incomplete_things_ids.append(things_id)
                    incomplete_todos_map[things_id] = (note_id, todo_id, todo_state.get("text", ""))

    if not incomplete_things_ids and not completed_things_ids:
        log("No synced todos to check")
        return

    # Query Things 3 for which todos are currently completed
    all_things_ids = incomplete_things_ids + completed_things_ids
    currently_completed_ids = get_completed_things_todos(all_things_ids)

    # Handle newly completed todos (incomplete in Bear, completed in Things)
    newly_completed_ids = [tid for tid in incomplete_things_ids if tid in currently_completed_ids]
    completed_count = 0
    for things_id in newly_completed_ids:
        note_id, todo_id, todo_text = incomplete_todos_map[things_id]

        # Check for ping-pong: skip if Bear just completed this todo
        todo_state = state[note_id]["synced_todos"][todo_id]
        last_modified_source = todo_state.get("last_modified_source")
        last_modified_time = todo_state.get("last_modified_time", 0)
        time_since_last = time.time() - last_modified_time

        if last_modified_source == "bear" and time_since_last < 5:
            log(
                f"Skipping completion sync for '{todo_text}' "
                f"(just completed by Bear {time_since_last:.1f}s ago)"
            )
            continue

        # Get note content
        if note_id not in notes_by_id:
            log(f"WARNING: Note {note_id} not found in Bear database", "WARNING")
            continue

        note_content = notes_by_id[note_id]["content"]

        # Mark complete in Bear via x-callback-url
        success, updated_content = complete_todo_in_note(note_id, todo_text, note_content)
        if success:
            # Update in-memory content for next todo in same note
            notes_by_id[note_id]["content"] = updated_content
            # Update state
            state[note_id]["synced_todos"][todo_id]["completed"] = True
            state[note_id]["synced_todos"][todo_id]["last_modified_time"] = time.time()
            state[note_id]["synced_todos"][todo_id]["last_modified_source"] = "things"
            completed_count += 1
            log(f"✓ Completed in Bear: '{todo_text}'")
        else:
            log(f"✗ Failed to complete in Bear: '{todo_text}'")

    # Handle newly uncompleted todos (completed in Bear, incomplete in Things)
    newly_uncompleted_ids = [
        tid for tid in completed_things_ids if tid not in currently_completed_ids
    ]
    uncompleted_count = 0
    for things_id in newly_uncompleted_ids:
        note_id, todo_id, todo_text = completed_todos_map[things_id]

        # Check for ping-pong: skip if Bear just uncompleted this todo
        # (Note: currently Bear→Things doesn't sync un-completions, so this is future-proofing)
        todo_state = state[note_id]["synced_todos"][todo_id]
        last_modified_source = todo_state.get("last_modified_source")
        last_modified_time = todo_state.get("last_modified_time", 0)
        time_since_last = time.time() - last_modified_time

        if last_modified_source == "bear" and time_since_last < 5:
            log(
                f"Skipping un-completion sync for '{todo_text}' "
                f"(just uncompleted by Bear {time_since_last:.1f}s ago)"
            )
            continue

        # Get note content
        if note_id not in notes_by_id:
            log(f"WARNING: Note {note_id} not found in Bear database", "WARNING")
            continue

        note_content = notes_by_id[note_id]["content"]

        # Mark incomplete in Bear via x-callback-url
        success, updated_content = uncomplete_todo_in_note(note_id, todo_text, note_content)
        if success:
            # Update in-memory content for next todo in same note
            notes_by_id[note_id]["content"] = updated_content
            # Update state
            state[note_id]["synced_todos"][todo_id]["completed"] = False
            state[note_id]["synced_todos"][todo_id]["last_modified_time"] = time.time()
            state[note_id]["synced_todos"][todo_id]["last_modified_source"] = "things"
            uncompleted_count += 1
            log(f"✓ Uncompleted in Bear: '{todo_text}'")
        else:
            log(f"✗ Failed to uncomplete in Bear: '{todo_text}'")

    # Log summary
    if completed_count > 0 or uncompleted_count > 0:
        parts = []
        if completed_count > 0:
            parts.append(f"completed {pluralize(completed_count, 'todo')}")
        if uncompleted_count > 0:
            parts.append(f"uncompleted {pluralize(uncompleted_count, 'todo')}")
        summary = f"{' and '.join(parts).capitalize()} in Bear from Things 3"
        log(summary)
        send_notification("Bear Things Sync", summary, sound=False)
    else:
        log("No completion changes detected in Things 3")


def execute(source: str = "bear") -> None:
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

    # Handle Things 3 → Bear sync (completions only)
    if source == "things" and settings.bidirectional_sync:
        _sync_from_things(state)
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
                # Check for ping-pong: skip if Things just completed this todo
                last_modified_source = todo_state.get("last_modified_source")
                last_modified_time = todo_state.get("last_modified_time", 0)
                time_since_last = time.time() - last_modified_time

                if last_modified_source == "things" and time_since_last < 5:
                    log(
                        f"Skipping completion sync for '{current_todo['text']}' "
                        f"(just completed by Things {time_since_last:.1f}s ago)"
                    )
                    continue

                # If todo is now completed in Bear but not marked complete in our state
                things_id = todo_state.get("things_id")
                if things_id:
                    if complete_todo(things_id):
                        state[note_id]["synced_todos"][todo_id]["completed"] = True
                        state[note_id]["synced_todos"][todo_id]["last_modified_time"] = time.time()
                        state[note_id]["synced_todos"][todo_id]["last_modified_source"] = "bear"
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
            todo_tags = [settings.sync_tag] + remaining_tags

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
