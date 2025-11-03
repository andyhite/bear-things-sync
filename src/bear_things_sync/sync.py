"""Main sync logic for Bear to Things 3."""

from .bear import extract_todos, get_notes_with_todos
from .config import THINGS_SYNC_TAG
from .things import complete_todo, create_todo, get_projects
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


def sync() -> None:
    """
    Main sync function.

    - Syncs new incomplete todos from Bear to Things 3
    - Marks todos as complete in Things 3 if completed in Bear
    """
    log("Starting Bear to Things sync...")

    state = load_state()

    # Add state version if not present (for future migrations)
    if "_version" not in state:
        state["_version"] = 2  # Version 2: dict-based synced_todos

    # Migrate to version 3: content-based todo IDs (instead of line-based)
    if state.get("_version", 2) < 3:
        log("Migrating state format to v3 (content-based todo IDs)...", "WARNING")
        _migrate_to_v3(state)
        state["_version"] = 3

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

            # Create in Things 3
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

            things_id = create_todo(
                title=todo_title, notes=todo_notes, tags=todo_tags, project=target_project
            )

            if things_id:
                state[note_id]["synced_todos"][todo_id] = {
                    "things_id": things_id,
                    "completed": False,
                    "text": todo["text"],  # Store text for fuzzy matching
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
