# Bear to Things 3 Todo Sync

[![CI](https://github.com/andyhite/bear-things-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/andyhite/bear-things-sync/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bear-things-sync.svg)](https://pypi.org/project/bear-things-sync/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Keep your todos in sync between Bear and Things 3. When you add a todo in Bear, it shows up in Things 3. When you complete it in Things 3, it gets checked off in Bear.

[Features](#how-it-works) • [Installation](#installation) • [Development](#development) • [Contributing](CONTRIBUTING.md) • [License](LICENSE)

## How It Works

The sync runs as a background daemon that watches both Bear and Things 3 databases for changes.

When you add a todo in Bear (using `- [ ]` or `* [ ]`), it gets created in Things 3 with all your tags. If a Bear tag matches one of your Things 3 projects, the todo goes straight into that project. The sync is smart about tag formatting too - `#TrainingTools` becomes "Training Tools" in Things 3.

When you complete a todo in Things 3, it gets marked as done in your Bear note automatically. There's a 5-second cooldown to prevent the apps from ping-ponging updates back and forth.

## Requirements

- macOS with Bear and Things 3 installed
- Python 3.9+ (built-in on macOS)

## Installation

### Quick Install

```bash
pip install bear-things-sync
bear-things-sync install
```

That's it! The installer will check that you have Bear and Things 3, then set up a background daemon to keep everything in sync.

### Manual Installation

If you want more control over the process:

```bash
# Install the package
pip install bear-things-sync

# Try a manual sync first to make sure everything works
bear-things-sync

# Check the logs if you're curious
cat ~/.bear-things-sync/sync_log.txt

# Install the background daemon
bear-things-sync install

# Verify it's running
launchctl list | grep bear-things-sync
```

For development, clone the repo and install in editable mode:

```bash
git clone https://github.com/andyhite/bear-things-sync.git
cd bear-things-sync
uv venv
uv pip install -e .
```

## Configuration

The defaults work for most people, but if you want to customize things, create `~/.bear-things-sync/config.json`:

```json
{
  "sync_tag": "Bear Sync",
  "bidirectional_sync": true,
  "sync_cooldown": 5,
  "bear_database_path": "/path/to/custom/database.sqlite",
  "things_database_path": "/path/to/custom/Things/main.sqlite"
}
```

Some useful options:
- `sync_tag` - Change the tag added to synced todos (default: "Bear Sync")
- `sync_cooldown` - Adjust the cooldown period in seconds (default: 5)
- `bidirectional_sync` - Turn off Things → Bear sync if you only want one-way (default: true)

Check `src/bear_things_sync/config.py` for the full list of options.

## Usage

Once the daemon is running, everything happens automatically in the background.

Add a todo in Bear using `- [ ] Task name` and it'll show up in Things 3 with your tags. If you have a tag like `#Fitness` and a Things project called "🏃 Fitness", the todo goes straight into that project. The sync ignores emojis and handles both PascalCase and regular tags.

Complete a todo in Things 3, and it gets checked off in your Bear note. There's a 5-second cooldown between updates to prevent the two apps from fighting over the same todo.

### Tag Formatting

Tags get converted from PascalCase to Title Case for Things 3. So `#TrainingTools` becomes "Training Tools" and `#MyProject` becomes "My Project".

### Project Assignment

If a Bear tag matches a Things 3 project name, the todo goes into that project automatically. The matching is case-insensitive and ignores emojis, so `#Fitness` will match a project called "🏃 Fitness" or "fitness" or "FITNESS".

When a tag matches a project, it won't be added as a tag on the todo (since it's already in that project). Other tags that don't match projects will still be added.

## Monitoring

Check if the daemon is running:

```bash
launchctl list | grep bear-things-sync
```

View the logs:

```bash
tail -f ~/.bear-things-sync/sync_log.txt
tail -f ~/.bear-things-sync/watcher_log.txt
tail -f ~/.bear-things-sync/daemon_stderr.log
```

## Uninstallation

Stop the daemon and remove the background service:

```bash
bear-things-sync uninstall
```

This stops the daemon and removes the launchd plist. It'll ask if you want to delete your sync state and logs too.

To completely remove the package:

```bash
pip uninstall bear-things-sync
```

## Troubleshooting

### Daemon won't start

Check the error log to see what's wrong:

```bash
cat ~/.bear-things-sync/daemon_stderr.log
```

Try running a manual sync to test things out:

```bash
bear-things-sync
```

### Todos not syncing

Make sure your todos are formatted as `- [ ] Task text` or `* [ ] Task text`. Check the logs for errors. If Things 3 doesn't have the right permissions, you might need to grant AppleScript access.

### Getting duplicates

If you're seeing duplicate todos, reset the sync state:

```bash
bear-things-sync reset
```

This clears all tracking and lets you start fresh.

### Daemon crashed

Check what happened:
```bash
cat ~/.bear-things-sync/daemon_stderr.log
```

Restart it:
```bash
launchctl unload ~/Library/LaunchAgents/com.bear-things-sync.plist
launchctl load ~/Library/LaunchAgents/com.bear-things-sync.plist
```

## Development

### Running Tests

All tests use mocks so they don't touch your real Bear or Things 3 databases.

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

Uses `ruff` for formatting/linting and `pyright` for type checking:

```bash
uv run ruff format src/ tests/
uv run ruff check --fix src/ tests/
uv run pyright src/
```

### Project Structure

```
bear-things-sync/
├── src/bear_things_sync/       # Main Python package
│   ├── bear.py                 # Bear database operations
│   ├── things.py               # Things 3 AppleScript operations
│   ├── things_db.py            # Things 3 database reading (for bi-directional sync)
│   ├── sync.py                 # Main sync logic
│   ├── watch.py                # File watcher using watchdog
│   ├── cli.py                  # Command-line interface
│   ├── install.py              # Daemon installation
│   ├── uninstall.py            # Daemon uninstallation
│   ├── reset.py                # State reset utility
│   ├── config.py               # Configuration
│   └── utils.py                # Utility functions
├── tests/                      # Unit tests
│   ├── test_bear.py            # Bear module tests
│   ├── test_things.py          # Things module tests
│   ├── test_things_db.py       # Things database tests
│   ├── test_sync.py            # Sync orchestration tests
│   └── test_utils.py           # Utility function tests
├── templates/
│   └── daemon.plist.template   # launchd configuration template
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

See [CONTRIBUTING.md](CONTRIBUTING.md) for details. Quick setup:

```bash
git clone https://github.com/YOUR_USERNAME/bear-things-sync.git
cd bear-things-sync
uv venv
uv pip install -e .
uv pip install pytest pytest-mock ruff pyright

# Run the checks
uv run ruff format src/ tests/
uv run ruff check src/ tests/
uv run pyright src/
uv run pytest tests/ -v
```

PRs need to pass all CI checks (format, lint, typecheck, tests).

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) for automated versioning:

```
feat: add uninstall command
fix: handle missing Bear database
docs: update installation instructions
```

Use `feat:` for new features and `fix:` for bug fixes. Add `BREAKING CHANGE:` in the footer for breaking changes.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Notes

The databases are opened in read-only mode, so there's no risk of corrupting your Bear or Things 3 data. Only incomplete todos get synced from Bear to Things 3. When you complete a todo in either app, it gets marked as complete in the other (with a 5-second cooldown to prevent the apps from bouncing updates back and forth).
