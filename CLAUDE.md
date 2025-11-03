# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bear Things Sync is a macOS daemon that automatically syncs uncompleted todos from Bear notes to Things 3. It uses `fswatch` to monitor Bear's SQLite database for changes and triggers syncs via AppleScript.

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
# Format code (required before commits)
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

1. **File Watcher** (`watch_bear.sh`) → Monitors Bear database with `fswatch`
2. **Sync Trigger** → Calls `bear-things-sync` on database changes
3. **Bear Module** (`bear.py`) → Reads Bear's SQLite database (read-only)
4. **Sync Logic** (`sync.py`) → Orchestrates the sync process
5. **Things Module** (`things.py`) → Creates/completes todos via AppleScript

### Key Modules

**bear.py** - Bear database operations
- `get_notes_with_todos()`: Queries Bear's SQLite database for notes containing todos
- `extract_todos()`: Parses note content for todo patterns (`- [ ]` or `* [ ]`)
- Uses read-only SQLite connection to prevent corruption
- Extracts tags from `ZSFNOTETAG` table via join

**things.py** - Things 3 integration via AppleScript
- `get_projects()`: Fetches all Things 3 projects, strips emojis for matching
- `create_todo()`: Creates todos with proper escaping for AppleScript
- `complete_todo()`: Marks todos as complete by Things ID
- All operations use `subprocess.run()` with AppleScript

**sync.py** - Main orchestration logic
- Maintains state in `~/.bear-things-sync/sync_state.json`
- Tracks synced todos by unique ID: `{note_id}:{line_number}`
- Handles state migration from old list format to dict format
- Syncs new incomplete todos to Things 3
- Detects completed todos in Bear and marks them complete in Things 3
- Cleans up state for deleted notes

**config.py** - Configuration
- Paths: Bear database, state file, log file
- Todo patterns (regex for incomplete/completed)
- Default tag: "Bear Sync"

**utils.py** - Utility functions
- `pascal_to_title_case()`: Converts `TrainingTools` → `Training Tools`
- `strip_emojis()`: Removes emojis for project name matching
- `log()`: Writes to both console and log file
- `load_state()` / `save_state()`: JSON state persistence
- `cleanup_state()`: Removes entries for deleted notes

### State Management

The sync state is stored in `~/.bear-things-sync/sync_state.json`:

```python
{
  "note_id_123": {
    "title": "Note Title",
    "synced_todos": {
      "note_id_123:5": {  # unique todo ID (note:line)
        "things_id": "ABC123",
        "completed": false
      }
    }
  }
}
```

This allows:
- Duplicate prevention (don't re-sync same todo)
- Completion tracking (mark complete in Things when completed in Bear)
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
- **Dev dependencies**: pytest, pytest-mock, ruff, pyright

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
