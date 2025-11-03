# Bear to Things 3 Todo Sync

[![CI](https://github.com/andyhite/bear-things-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/andyhite/bear-things-sync/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bear-things-sync.svg)](https://pypi.org/project/bear-things-sync/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Automatically syncs uncompleted todos from Bear notes to Things 3 when Bear syncs.

[Features](#how-it-works) • [Installation](#installation) • [Development](#development) • [Contributing](CONTRIBUTING.md) • [License](LICENSE)

## How It Works

1. **File Watcher**: Monitors Bear's database for changes using `fswatch`
2. **Todo Extraction**: Parses Bear notes for uncompleted checkboxes (`- [ ]` or `* [ ]`)
3. **Tag Sync**: Extracts tags from Bear notes, converts PascalCase to Title Case, and adds them to Things 3 todos
4. **Smart Project Assignment**: Automatically assigns todos to matching Things 3 projects based on Bear tags (ignores emojis)
5. **Things Integration**: Creates tasks in Things 3 via AppleScript
6. **Duplicate Prevention**: Tracks synced todos to avoid creating duplicates

## Requirements

- macOS with Bear and Things 3 installed
- Python 3.9+ (built-in on macOS)
- Homebrew (for installing fswatch)
- `fswatch` - File system monitoring tool

## Installation

### Quick Install (Recommended)

```bash
# 1. Install fswatch (required for file watching)
brew install fswatch

# 2. Install bear-things-sync
pip install bear-things-sync
# or with uv:
uv pip install bear-things-sync

# 3. Test it works
bear-things-sync

# 4. Install as a background daemon
bear-things-sync-install
```

That's it! The daemon will now run automatically in the background.

### Detailed Steps

#### 1. Install dependencies

```bash
# Install fswatch for file monitoring
brew install fswatch
```

#### 2. Install the package

```bash
# Install from PyPI (when published)
pip install bear-things-sync

# Or with uv (faster)
uv pip install bear-things-sync

# Or for development, clone and install:
git clone https://github.com/andyhite/bear-things-sync.git
cd bear-things-sync
uv venv
uv pip install -e .
```

#### 3. Test manually first

Run the sync script once to ensure everything works:

```bash
bear-things-sync
```

Check the logs:
```bash
cat ~/.bear-things-sync/sync_log.txt
```

#### 4. Install as a background daemon

Run the installer which will:
- Copy the watcher script to `~/.bear-things-sync/`
- Generate the launchd plist
- Install and start the daemon

```bash
bear-things-sync-install
```

Check if it's running:

```bash
launchctl list | grep bear-things-sync
```

## Configuration

The default configuration works for most users. If you need to customize:

- **Filter by tag**: Only sync notes with a specific tag
- **Custom todo patterns**: Recognize different checkbox formats
- **Change sync tag**: Modify the "Bear Sync" tag added to todos

For development/clone installations, edit `src/bear_things_sync/config.py`.

For pip installations, configuration isn't currently supported (coming soon: config file support).

## Usage

Once installed, the sync happens automatically when:
- Bear syncs with iCloud (typically within seconds of changes)
- You make local changes in Bear

Synced todos will:
- Appear in Things 3 (Inbox or matching project)
- Have tag `Bear Sync` plus any tags from the Bear note (converted to Title Case)
- Include a link back to the original Bear note
- Be automatically assigned to a project if a Bear tag matches a Things project name (case-insensitive, emoji-agnostic)

### Tag Formatting

Bear tags in PascalCase are automatically converted to Title Case for better readability in Things 3:

**Examples:**
- `#TrainingTools` → `Training Tools`
- `#MyProject` → `My Project`
- `#Circuit` → `Circuit` (unchanged)

### Smart Project Assignment

If a Bear note has a tag that matches a Things 3 project name, todos will be automatically added to that project:

**Examples:**
- Bear tag: `#Circuit` → Things project: `🔋 Circuit` ✓
- Bear tag: `#TrainingTools` → Things project: `🏋️ Training Tools` ✓

The matching:
- Is **case-insensitive** (`circuit` = `Circuit`)
- **Ignores emojis** (`Circuit` matches `🔋 Circuit`)
- **Handles PascalCase** (`TrainingTools` matches `Training Tools`)
- Uses the **first matching tag** if multiple tags match projects
- **Excludes the matched tag** from the todo's tags to avoid redundancy (no need for a "Circuit" tag when it's already in the Circuit project!)
- **Keeps unmatched tags** so you can still organize by tags that don't have corresponding projects

## Monitoring

### View logs

```bash
# Sync script logs
tail -f ~/.bear-things-sync/sync_log.txt

# Watcher logs
tail -f ~/.bear-things-sync/watcher_log.txt

# Daemon logs
tail -f ~/.bear-things-sync/daemon_stdout.log
tail -f ~/.bear-things-sync/daemon_stderr.log
```

### Check daemon status

```bash
launchctl list | grep bear-things-sync
```

## Uninstallation

Uninstall the daemon and optionally remove data:

```bash
# Uninstall the daemon (keeps data by default)
bear-things-sync-uninstall

# Completely remove the package
pip uninstall bear-things-sync
# or with uv:
uv pip uninstall bear-things-sync
```

The uninstaller will:
1. Stop the running daemon
2. Remove the launchd plist
3. Ask if you want to remove the data directory (`~/.bear-things-sync/`)

## Troubleshooting

### Daemon won't start

1. Check the error log: `cat ~/.bear-things-sync/daemon_stderr.log`
2. Verify fswatch is installed: `which fswatch`
3. Test scripts manually first

### Todos not syncing

1. Check logs for errors
2. Verify Bear database location exists
3. Ensure Things 3 is installed and has AppleScript access
4. Check that todos match the pattern: `- [ ] Task text`

### Too many duplicates

The script maintains state in `~/.bear-things-sync/sync_state.json`. If you want to resync everything:

```bash
rm ~/.bear-things-sync/sync_state.json
```

### Script crashes

View the full error:
```bash
cat ~/.bear-things-sync/daemon_stderr.log
```

Restart the daemon:
```bash
launchctl unload ~/Library/LaunchAgents/com.andyhite.bear-things-sync.plist
launchctl load ~/Library/LaunchAgents/com.andyhite.bear-things-sync.plist
```

## Development

### Running Tests

The project includes comprehensive unit tests with mocked I/O operations. All tests use mocks to avoid touching real Bear database or Things 3.

```bash
# Install test dependencies
uv pip install pytest pytest-mock

# Run all tests
uv run pytest tests/ -v

# Run tests with coverage
uv run pytest tests/ --cov=bear_things_sync --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_sync.py -v

# Run specific test
uv run pytest tests/test_sync.py::TestSync::test_sync_new_todo -v
```

### Code Quality

The project uses `ruff` for formatting and linting, and `pyright` for type checking:

```bash
# Install quality tools
uv pip install ruff pyright

# Format code
uv run ruff format src/ tests/

# Check formatting (for CI)
uv run ruff format --check src/ tests/

# Lint code
uv run ruff check src/ tests/

# Auto-fix linting issues
uv run ruff check --fix src/ tests/

# Type check
uv run pyright src/
```

### Test Coverage

Tests cover:
- **utils.py**: Pure functions (PascalCase conversion, emoji stripping, logging)
- **bear.py**: Database queries and todo extraction (mocked SQLite)
- **things.py**: AppleScript operations (mocked subprocess)
- **sync.py**: Main orchestration logic (all dependencies mocked)

All external I/O operations (database, AppleScript, file system) are mocked to ensure fast, isolated tests.

### Project Structure

```
bear-things-sync/
├── src/bear_things_sync/       # Main Python package
│   ├── bear.py                 # Bear database operations
│   ├── things.py               # Things 3 AppleScript operations
│   ├── sync.py                 # Main sync logic
│   ├── config.py               # Configuration
│   └── utils.py                # Utility functions
├── tests/                      # Unit tests
│   ├── test_bear.py            # Bear module tests
│   ├── test_things.py          # Things module tests
│   ├── test_sync.py            # Sync orchestration tests
│   └── test_utils.py           # Utility function tests
├── scripts/                    # Helper scripts
│   ├── install.sh              # Automated installation script
│   └── watch_bear.sh           # File watcher wrapper
├── launchd/
│   └── com.andyhite.bear-things-sync.plist.template  # launchd template
├── .github/workflows/
│   └── ci.yml                  # GitHub Actions CI/CD
├── pyproject.toml              # Package configuration
├── LICENSE                     # MIT License
├── CONTRIBUTING.md             # Contributing guidelines
└── README.md
```

### Runtime Data

Runtime data (logs and state) is stored in `~/.bear-things-sync/`:
- `sync_state.json` - Tracks synced todos to prevent duplicates
- `sync_log.txt` - Sync operation logs
- `watcher_log.txt` - File watcher logs
- `daemon_stdout.log` - Daemon standard output
- `daemon_stderr.log` - Daemon error logs

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Start for Contributors

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/bear-things-sync.git
cd bear-things-sync

# Set up development environment
uv venv
uv pip install -e .
uv pip install pytest pytest-mock ruff pyright

# Run quality checks
uv run ruff format src/ tests/        # Format code
uv run ruff check src/ tests/         # Lint code
uv run pyright src/                   # Type check
uv run pytest tests/ -v               # Run tests
```

All pull requests must pass the CI checks (formatting, linting, type checking, and tests).

### Commit Message Format

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated versioning and changelog generation.

**Format**: `<type>: <description>`

**Examples**:
```
feat: add uninstall command for daemon
fix: handle missing Bear database gracefully
docs: update installation instructions
chore: bump dependencies
```

**Types**:
- `feat:` - New feature (triggers minor version bump)
- `fix:` - Bug fix (triggers patch version bump)
- `docs:` - Documentation changes
- `chore:` - Maintenance tasks
- `test:` - Test changes
- `refactor:` - Code refactoring

**Breaking changes**: Add `BREAKING CHANGE:` in the commit footer to trigger a major version bump.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Notes

- The script reads Bear's database in read-only mode (safe)
- Completed todos in Bear won't be synced initially (only incomplete ones)
- Marking a todo as complete in Bear will complete it in Things 3
- Completing a todo in Things 3 won't mark it complete in Bear
- The sync is primarily one-way: Bear → Things 3
