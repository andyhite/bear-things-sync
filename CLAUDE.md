# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bear Things Sync is a macOS daemon that provides bi-directional todo synchronization between Bear and Things 3. It monitors both Bear's and Things 3's SQLite databases using `fswatch` and syncs changes:

- **Bear → Things 3**: New uncompleted todos from Bear notes are created in Things 3
- **Things 3 → Bear**: Completed todos in Things 3 are marked complete in Bear via AppleScript
- **Cooldown mechanism**: Prevents circular updates with a 5-second cooldown window

## Development Commands

### Testing
```bash
# Run all tests with virtual environment
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_sync.py -v

# Run specific test
uv run pytest tests/test_sync.py::TestSync::test_sync_new_todo -v

# Run with coverage
uv run pytest tests/ --cov=bear_things_sync --cov-report=term-missing
```

### Code Quality
```bash
# Format code
uv run ruff format src/ tests/

# Check formatting (used in CI)
uv run ruff format --check src/ tests/

# Lint code
uv run ruff check src/ tests/

# Auto-fix linting issues
uv run ruff check --fix src/ tests/

# Type check
uv run pyright src/
```

### Pre-commit Hooks
Pre-commit hooks automatically run quality checks before each commit. This ensures code is always formatted and passes linting/type checking.

**First-time setup:**
```bash
# Install dependencies (including pre-commit)
uv sync

# Install the git hooks
pre-commit install
```

**Usage:**
Once installed, hooks run automatically on `git commit`:
- **Ruff format**: Auto-formats code and stages changes
- **Ruff check**: Lints code with auto-fix where possible
- **Pyright**: Type checks the codebase

**Manual hook execution:**
```bash
# Run hooks on all files (useful after updating .pre-commit-config.yaml)
pre-commit run --all-files

# Update hook versions
pre-commit autoupdate
```

**Bypass hooks (use sparingly):**
```bash
# Skip hooks for WIP commits
git commit --no-verify
```

**Note:** Hooks intentionally skip tests for speed. CI runs the full test suite.

### Manual Testing
```bash
# Run sync once manually (uses Python from virtual environment)
.venv/bin/python -m bear_things_sync

# Or with activated venv
python -m bear_things_sync

# View logs
tail -f ~/.bear-things-sync/sync_log.txt
```

## Architecture

### Core Data Flow

**Bear → Things 3 Sync:**
1. **File Watcher** (`watch_sync.sh`) → Monitors Bear database with `fswatch`
2. **Sync Trigger** → Calls `bear-things-sync --source bear` on database changes
3. **Bear Module** (`bear.py`) → Reads Bear's SQLite database (read-only)
4. **Sync Logic** (`sync.py`) → Orchestrates the sync process
5. **Things Module** (`things.py`) → Creates/completes todos via AppleScript

**Things 3 → Bear Sync:**
1. **File Watcher** (`watch_sync.sh`) → Monitors Things 3 database with `fswatch`
2. **Sync Trigger** → Calls `bear-things-sync --source things` on database changes
3. **Things DB Module** (`things_db.py`) → Queries Things 3's SQLite database for completed todos
4. **Sync Logic** (`sync.py`) → Checks cooldown, finds completed todos
5. **Bear AppleScript** (`bear.py`) → Marks todos complete in Bear notes via AppleScript

### Key Modules

**bear.py** - Bear database and AppleScript operations
- `get_notes_with_todos()`: Queries Bear's SQLite database for notes containing todos
- `extract_todos()`: Parses note content for todo patterns (`- [ ]` or `* [ ]`)
- `complete_todo_in_note()`: Marks todos complete in Bear via AppleScript (for bi-directional sync)
- Uses read-only SQLite connection to prevent corruption
- Extracts tags from `ZSFNOTETAG` table via join

**things.py** - Things 3 integration via AppleScript
- `get_projects()`: Fetches all Things 3 projects, strips emojis for matching
- `create_todo()`: Creates todos with proper escaping for AppleScript
- `complete_todo()`: Marks todos as complete by Things ID
- All operations use `subprocess.run()` with AppleScript

**things_db.py** - Things 3 database operations (read-only)
- `get_completed_things_todos()`: Queries Things 3's SQLite database for completion status
- `validate_things_schema()`: Validates database compatibility
- Uses read-only connection with retry logic for lock handling

**sync.py** - Main orchestration logic
- Maintains state in `~/.bear-things-sync/sync_state.json` (version 5)
- Tracks synced todos by content-based ID with timestamp tracking
- Handles state migration through v5 (bi-directional sync support)
- Routes syncs based on `source` parameter (bear or things)
- Implements cooldown logic to prevent circular updates
- **Bear → Things**: Syncs new incomplete todos, marks completed todos
- **Things → Bear**: Marks completed todos in Bear via AppleScript
- Cleans up state for deleted notes

**config.py** - Configuration
- Paths: Bear database, Things 3 database, state file, log file
- Todo patterns (regex for incomplete/completed)
- Default tag: "Bear Sync"
- Bi-directional sync configuration (enabled by default)
- Sync cooldown setting (5 seconds default)
- Auto-discovery for both Bear and Things 3 databases

**utils.py** - Utility functions
- `pascal_to_title_case()`: Converts `TrainingTools` → `Training Tools`
- `strip_emojis()`: Removes emojis for project name matching
- `log()`: Writes to both console and log file
- `load_state()` / `save_state()`: JSON state persistence
- `cleanup_state()`: Removes entries for deleted notes

### State Management

The sync state is stored in `~/.bear-things-sync/sync_state.json` (version 5):

```python
{
  "_version": 5,
  "_last_sync_time": 1234567890.123,  # Unix timestamp
  "_last_sync_source": "bear",  # or "things"
  "note_id_123": {
    "title": "Note Title",
    "synced_todos": {
      "note_id_123:hash": {  # content-based unique ID
        "things_id": "ABC123",
        "completed": false,
        "text": "Todo text",
        "last_modified_time": 1234567890.123,
        "last_modified_source": "bear"
      }
    }
  }
}
```

This allows:
- Duplicate prevention (don't re-sync same todo)
- Bi-directional completion tracking with cooldown to prevent circular updates
- Content-based IDs that survive text edits
- Timestamp tracking for conflict resolution
- State cleanup when notes are deleted

### Tag and Project Matching

1. Bear tags are extracted from note (e.g., `#TrainingTools`)
2. Tags are converted to Title Case (`Training Tools`)
3. Things projects are fetched and emojis stripped (`🏋️ Training Tools` → `training tools`)
4. Case-insensitive matching finds project (`TrainingTools` matches `🏋️ Training Tools`)
5. Matched tag is excluded from todo tags to avoid redundancy
6. Unmatched tags are added to the todo

### Testing Strategy

All tests use mocks to avoid touching real Bear database or Things 3:
- **SQLite operations**: Mocked with `pytest-mock`
- **AppleScript calls**: Mocked `subprocess.run()`
- **File I/O**: Mocked state file operations
- Tests run in <1 second and are fully isolated

## Python Environment

- **Minimum Python**: 3.9+
- **Package manager**: `uv` (preferred) or `pip`
- **Dependencies**: None in production (uses only stdlib)
- **Dev dependencies**: pytest, pytest-mock, ruff, pyright, pre-commit

## Important Constraints

- **macOS only**: Requires Bear, Things 3, and AppleScript
- **Read-only Bear access**: Database opened with `mode=ro` to prevent corruption
- **fswatch required**: Must be installed via Homebrew
- **Line length**: 100 characters max (enforced by ruff)
- **Type checking**: Basic mode (pyright)

## Common Tasks

### Running a single test
```bash
uv run pytest tests/test_sync.py::TestSync::test_sync_new_todo -v
```

### Testing after changes
```bash
# Full quality check (same as CI)
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run pyright src/
uv run pytest tests/ -v
```

### Manual sync for debugging
```bash
# Run once and check logs
.venv/bin/python -m bear_things_sync
cat ~/.bear-things-sync/sync_log.txt
```

### Resetting state (for testing)
```bash
# Remove state file to force re-sync
rm ~/.bear-things-sync/sync_state.json
```
