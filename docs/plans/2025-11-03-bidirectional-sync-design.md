# Bi-Directional Completion Sync Design

**Date:** 2025-11-03
**Status:** Approved Design
**Goal:** Enable bi-directional syncing so that completing a Bear-sourced todo in Things 3 also marks it complete in Bear.

## Overview

The current system provides one-way sync from Bear to Things 3:
- New incomplete todos in Bear → Created in Things 3
- Completed todos in Bear → Marked complete in Things 3

This design adds the reverse flow:
- Completed todos in Things 3 → Marked complete in Bear

## Architecture & Data Flow

### Current Architecture
- A single watcher (fswatch) monitors Bear's SQLite database
- On Bear changes → sync runs → checks for new/completed todos
- One-way flow: Bear → Things 3

### New Architecture
- **Dual watchers**: Monitor both Bear and Things 3 databases
- **Sync orchestrator**: Routes sync logic based on which database changed
- **Two-way flow**: Bear ↔ Things 3

### Data Flow

**Bear Database Change:**
```
Bear DB Change → fswatch → sync(source='bear')
  ↓
  1. Check for new incomplete todos → Create in Things 3
  2. Check for Bear completions → Complete in Things 3
  3. Skip Things 3 → Bear updates (avoid circular sync)
```

**Things 3 Database Change:**
```
Things 3 DB Change → fswatch → sync(source='things')
  ↓
  1. Check for Things 3 completions → Complete in Bear (via AppleScript)
  2. Skip Bear → Things 3 updates (avoid circular sync)
  3. Respect cooldown period (skip if we just synced)
```

### Key Components

- `watch_bear.sh` → Rename to `watch_sync.sh`, launch two fswatch processes
- `sync.py` → Add `source` parameter, split into `sync_from_bear()` and `sync_from_things()`
- `things.py` → Add `get_completed_things_todos()` to query completion status from database
- `bear.py` → Add `complete_todo_in_note()` using AppleScript
- State → Add `last_sync_time` and `last_sync_source` for cooldown tracking

## State Management & Cooldown

### Extended State Schema (v4)

Current v3 state:
```python
{
  "_version": 3,
  "note_id_123": {
    "title": "Note Title",
    "synced_todos": {
      "note_id_123:hash": {
        "things_id": "ABC123",
        "completed": false,
        "text": "Todo text"
      }
    }
  }
}
```

New v4 state adds timestamp tracking:
```python
{
  "_version": 4,
  "_last_sync_time": 1234567890.123,  # Unix timestamp
  "_last_sync_source": "bear",  # or "things"
  "note_id_123": {
    "title": "Note Title",
    "synced_todos": {
      "note_id_123:hash": {
        "things_id": "ABC123",
        "completed": false,
        "text": "Todo text",
        "last_modified_time": 1234567890.123,  # When this todo was last synced
        "last_modified_source": "bear"  # Which app made the last change
      }
    }
  }
}
```

### Cooldown Logic

The cooldown prevents circular updates where our sync triggers another sync:

```python
SYNC_COOLDOWN = 5  # seconds

def should_skip_sync(state, source):
    """Check if we should skip this sync to avoid circular updates."""
    last_sync_time = state.get("_last_sync_time", 0)
    last_sync_source = state.get("_last_sync_source", None)
    time_since_last = time.time() - last_sync_time

    # Skip if we just synced from the opposite source
    # (we probably triggered this change)
    if time_since_last < SYNC_COOLDOWN:
        opposite_source = "things" if source == "bear" else "bear"
        if last_sync_source == opposite_source:
            return True

    return False
```

### Per-Todo Tracking

Each todo tracks its own modification time and source. This enables:
1. Detection of which app last modified a specific todo
2. Per-todo cooldown rather than global cooldown
3. Correct handling of simultaneous edits to different todos

## Things 3 Database Monitoring

### Database Location

Things 3 stores data in SQLite at:
```
~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*.db
```

We will:
1. Auto-detect database path (glob pattern for wildcard)
2. Open in read-only mode to prevent corruption
3. Handle lock contention with retry logic (same as Bear)

### Detecting Completed Todos

Query Things 3 to find which synced todos we have completed:

```python
def get_completed_things_todos(synced_todo_ids: list[str]) -> set[str]:
    """
    Query Things 3 database for completion status of synced todos.

    Args:
        synced_todo_ids: List of Things 3 IDs we're tracking

    Returns:
        Set of Things 3 IDs that are now completed
    """
    # Query Things 3 database for todos by ID
    # Check their status (need to discover status field/values)
    # Return set of completed IDs
```

### Schema Discovery

Similar to Bear's schema validation:
1. Inspect Things 3 database schema
2. Find table and columns for todos and completion status
3. Add validation to detect if Things 3 updates break compatibility
4. Cache validation results

### Sync Flow from Things 3

```python
def sync_from_things(state):
    """Handle Things 3 → Bear sync (completions only)."""
    # 1. Check cooldown
    if should_skip_sync(state, source='things'):
        return

    # 2. Collect all synced Things IDs from state
    all_things_ids = collect_synced_things_ids(state)

    # 3. Query Things 3 for completion status
    completed_ids = get_completed_things_todos(all_things_ids)

    # 4. For each completed ID:
    #    - Find corresponding Bear note and todo text
    #    - Mark complete in Bear via AppleScript
    #    - Update state

    # 5. Update global sync timestamp
    state["_last_sync_time"] = time.time()
    state["_last_sync_source"] = "things"
```

## Completing Todos in Bear via AppleScript

### Bear AppleScript Capabilities

Bear provides AppleScript commands to modify notes. Process:
1. Fetch note content by ID
2. Find specific todo line by text matching
3. Replace `- [ ]` with `- [x]` (or `* [ ]` with `* [x]`)
4. Update note content

### Implementation

```python
# In bear.py

def complete_todo_in_note(note_id: str, todo_text: str) -> bool:
    """
    Mark a todo as complete in a Bear note using AppleScript.

    Args:
        note_id: Bear note unique identifier
        todo_text: The todo text to find and mark complete

    Returns:
        True if successful, False otherwise
    """
    # 1. Fetch current note content via AppleScript
    # 2. Parse content line-by-line to find matching todo
    # 3. Replace [ ] with [x] for that specific line
    # 4. Update note content via AppleScript
    # 5. Handle fuzzy matching (in case todo text changed slightly)
```

### AppleScript Commands

```applescript
-- Get note content
tell application "Bear"
    set noteContent to text of note id "NOTE-ID-HERE"
end tell

-- Update note content
tell application "Bear"
    set text of note id "NOTE-ID-HERE" to "NEW CONTENT HERE"
end tell
```

### Challenges & Solutions

1. **Finding exact todo**: Use fuzzy matching (similar to `find_todo_by_fuzzy_match()`) since text may have changed
2. **Multiple identical todos**: Match by first uncompleted occurrence
3. **AppleScript reliability**: Apply same retry decorator as Things 3 operations
4. **Bear availability**: Check if Bear runs before attempting updates

### Safety Measures

- Modify the specific todo line only; preserve all other content
- Validate note content before and after to ensure no corruption
- Log all modifications for debugging
- Use atomic updates (fetch → modify → update in single operation)

## Dual Watcher & Orchestration

### Current Watcher

```bash
#!/bin/bash
fswatch -0 "$BEAR_DB_PATH" | while read -d "" event; do
    bear-things-sync
done
```

### New Dual Watcher

```bash
#!/bin/bash
# watch_sync.sh

# Launch two fswatch processes in background
fswatch -0 "$BEAR_DB_PATH" | while read -d "" event; do
    bear-things-sync --source bear
done &

fswatch -0 "$THINGS_DB_PATH" | while read -d "" event; do
    bear-things-sync --source things
done &

# Wait for both background processes
wait
```

### CLI Changes

```python
# In __main__.py or cli.py

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--source',
        choices=['bear', 'things'],
        default='bear',
        help='Which app triggered this sync'
    )
    args = parser.parse_args()

    sync(source=args.source)
```

### Sync Orchestration

```python
def sync(source: str = 'bear'):
    """
    Main sync entry point.

    Args:
        source: Which app triggered the sync ('bear' or 'things')
    """
    log(f"Starting sync triggered by {source.title()}...")

    state = load_state()
    migrate_state_if_needed(state)  # Handle v3 → v4 migration

    # Check cooldown
    if should_skip_sync(state, source):
        log(f"Skipping sync (cooldown period after {state['_last_sync_source']} sync)")
        return

    # Route to appropriate sync function
    if source == 'bear':
        sync_from_bear(state)
    else:
        sync_from_things(state)

    save_state(state)
```

### Process Management

The dual watcher creates two parallel processes. Considerations:
- Both write to same state file → File locking handles this (already implemented)
- Rapid changes in both apps → Cooldown prevents ping-pong
- One watcher crashes → Other continues working (graceful degradation)

## State Migration & Backward Compatibility

### Migration from v3 to v4

```python
def _migrate_to_v4(state: dict) -> None:
    """
    Migrate state from v3 (no cooldown tracking) to v4 (with cooldown).

    Adds global and per-todo timestamp/source tracking.

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
            for todo_id, todo_state in state[note_id]["synced_todos"].items():
                if "last_modified_time" not in todo_state:
                    todo_state["last_modified_time"] = 0
                    todo_state["last_modified_source"] = "bear"
                    migrated_todos += 1

    if migrated_todos > 0:
        log(f"Migrated {migrated_todos} todos to v4 format with timestamp tracking")
```

### Backward Compatibility

Users who update will experience:
1. **Seamless upgrade**: Existing synced todos continue working
2. **No re-sync**: Migration creates no duplicates
3. **Feature activation**: Bi-directional sync starts working immediately

### Config Addition

Add configuration option to disable bi-directional sync if users want the old behavior:

```python
# In config.py
BIDIRECTIONAL_SYNC = True  # Set to False for one-way sync only
```

### Installation Changes

Update installation instructions:
1. Stop old daemon: `launchctl unload ~/Library/LaunchAgents/com.andyhite.bear-things-sync.plist`
2. Update script path in plist: `watch_bear.sh` → `watch_sync.sh`
3. Reload daemon: `launchctl load ~/Library/LaunchAgents/com.andyhite.bear-things-sync.plist`

## Error Handling & Edge Cases

### Things 3 Database Schema Validation

Similar to Bear's schema validation:

```python
def validate_things_schema() -> tuple[bool, Optional[str]]:
    """
    Validate Things 3 database schema compatibility.

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check for required tables/columns
    # Cache validation result
    # Provide helpful error messages if schema changes
```

### Edge Cases

1. **Todo deleted in one app**
   - Things 3 todo deleted → Remove from state, ignore
   - Bear todo deleted → `cleanup_state()` already handles this

2. **Note modified while syncing**
   - Use fuzzy matching to find moved todos
   - Update `todo_id` in state if text changed

3. **Both apps unavailable**
   - Bear not running → Cannot complete todos in Bear
   - Things 3 not running → Already handled, show notification
   - Solution: Queue changes in state, retry on next sync

4. **Rapid completion/un-completion**
   - User completes in Things, immediately uncompletes in Bear
   - Cooldown prevents immediate sync back
   - After cooldown, Bear's state wins (last write wins within same todo)

5. **Database locked during sync**
   - Bear already handled with retry logic
   - Apply same retry pattern to Things 3 queries

### Conflict Resolution

```python
def resolve_completion_conflict(state, note_id, todo_id, bear_completed, things_completed):
    """
    Resolve conflicts when completion status differs between apps.

    Logic:
    - If within cooldown: skip (we probably caused this)
    - If outside cooldown: use last_modified_time to determine winner
    - If times equal: completion takes precedence (complete wins)
    """
    todo_state = state[note_id]["synced_todos"][todo_id]

    # Check if this is our own echo
    time_since_modification = time.time() - todo_state.get("last_modified_time", 0)
    if time_since_modification < SYNC_COOLDOWN:
        return "skip"

    # Outside cooldown - there's a real conflict
    # Default: completion wins over incompletion
    if bear_completed or things_completed:
        return "complete"
    else:
        return "incomplete"
```

### Logging & Debugging

- Log all bi-directional syncs with source indicator
- Track conflict resolutions in logs
- Add debug mode to show cooldown decisions

## Testing Strategy

### New Test Coverage

1. **Things 3 Database Operations**
   - Mock Things 3 database queries
   - Test schema validation
   - Test completion status detection
   - Test database lock handling

2. **Bear AppleScript Modifications**
   - Mock AppleScript calls to Bear
   - Test todo text matching and replacement
   - Test fuzzy matching for modified todos
   - Test retry logic for unavailable Bear

3. **Cooldown Logic**
   - Test skip conditions (within cooldown window)
   - Test pass conditions (outside cooldown window)
   - Test per-todo modification tracking
   - Test opposite-source detection

4. **Dual Sync Flows**
   - Test `sync_from_bear()` (existing + enhanced)
   - Test `sync_from_things()` (new functionality)
   - Test orchestration with source parameter
   - Test state migration v3 → v4

5. **Edge Cases**
   - Test deleted todos in both apps
   - Test simultaneous completion in both apps
   - Test rapid completion/un-completion
   - Test database unavailability

### Test Structure

```python
# tests/test_things_db.py
class TestThingsDatabaseOps:
    def test_validate_things_schema(self, mocker):
        # Test schema validation

    def test_get_completed_things_todos(self, mocker):
        # Test querying completion status

# tests/test_bear_applescript.py
class TestBearAppleScript:
    def test_complete_todo_in_note(self, mocker):
        # Test marking complete via AppleScript

    def test_fuzzy_match_todo(self, mocker):
        # Test finding modified todos

# tests/test_bidirectional_sync.py
class TestBidirectionalSync:
    def test_sync_from_things(self, mocker):
        # Test Things → Bear flow

    def test_cooldown_logic(self, mocker):
        # Test conflict prevention

    def test_state_migration_v4(self, mocker):
        # Test v3 → v4 migration
```

### Integration Testing

Since we cannot touch real databases in tests:
- Manual testing checklist in docs
- Script to generate test scenarios
- Detailed logging for user bug reports

## Implementation Phases

### Phase 1: Things 3 Database Discovery
- Auto-detect Things 3 database path
- Implement schema validation
- Create query functions for completion status

### Phase 2: Bear AppleScript Integration
- Implement `complete_todo_in_note()`
- Add fuzzy matching for todo location
- Add retry logic and error handling

### Phase 3: State Management
- Implement v4 state schema
- Add migration logic from v3 to v4
- Implement cooldown tracking

### Phase 4: Sync Orchestration
- Split `sync()` into `sync_from_bear()` and `sync_from_things()`
- Add source parameter to CLI
- Implement cooldown checks

### Phase 5: Dual Watcher
- Create `watch_sync.sh` with dual fswatch
- Update LaunchAgent configuration
- Test parallel process handling

### Phase 6: Testing & Documentation
- Write comprehensive test suite
- Update README with new features
- Create manual testing checklist
- Update installation instructions

## Success Criteria

1. **Functionality**: Completing a Bear-sourced todo in Things 3 marks it complete in Bear within 5 seconds
2. **No duplicates**: Bi-directional sync creates no duplicate todos
3. **No ping-pong**: Cooldown prevents infinite sync loops
4. **Backward compatible**: Existing users upgrade without issues
5. **Tests pass**: All new functionality has test coverage
6. **Documentation**: Clear instructions for installation and troubleshooting
