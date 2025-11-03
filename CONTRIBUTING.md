# Contributing to Bear Things Sync

Thank you for your interest in contributing to Bear Things Sync! This document provides guidelines and instructions for contributing.

## Code of Conduct

Be respectful and constructive in all interactions. We're all here to make this project better.

## How to Contribute

### Reporting Bugs

If you find a bug, please create an issue with:
- A clear, descriptive title
- Steps to reproduce the problem
- Expected vs actual behavior
- Your environment (macOS version, Bear version, Things 3 version)
- Relevant log files from `~/.bear-things-sync/`

### Suggesting Features

Feature requests are welcome! Please create an issue with:
- A clear description of the feature
- Why this feature would be useful
- Examples of how it would work

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Set up your development environment:**
   ```bash
   cd bear-things-sync
   uv venv
   uv pip install -e .
   uv pip install pytest pytest-mock ruff pyright
   ```

3. **Make your changes** following our coding standards:
   - Write clear, descriptive commit messages
   - Add tests for new functionality
   - Update documentation as needed

4. **Run quality checks** before submitting:
   ```bash
   # Format code
   uv run ruff format src/ tests/

   # Check linting
   uv run ruff check src/ tests/

   # Type check
   uv run pyright src/

   # Run tests
   uv run pytest tests/ -v
   ```

5. **Create a pull request** with:
   - A clear title and description
   - Reference to any related issues
   - Screenshots/logs if relevant

## Development Guidelines

### Code Style

- **Python 3.9+** compatibility required
- **Line length:** 100 characters max
- **Formatting:** Use `ruff format`
- **Linting:** Must pass `ruff check`
- **Type checking:** Must pass `pyright` (basic mode)

### Testing

- **All tests must pass** before merging
- **Add tests** for new features and bug fixes
- **Mock external I/O** (database, AppleScript, file system)
- Tests should run in < 1 second

### Commit Messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated versioning and changelog generation.

**Format**: `<type>: <description>`

**Required types**:
- `feat:` - New feature (minor version bump: 1.0.0 → 1.1.0)
- `fix:` - Bug fix (patch version bump: 1.0.0 → 1.0.1)
- `docs:` - Documentation only changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring without feature changes
- `perf:` - Performance improvements
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks, dependency updates, etc.
- `ci:` - CI/CD configuration changes
- `build:` - Build system changes

**Examples**:
```
Good: feat: add support for nested todo lists
Good: fix: handle emoji stripping for complex emojis
Good: docs: update installation instructions
Good: chore: bump dependencies
Bad: fix bug
Bad: update
```

**Breaking changes**: Add `BREAKING CHANGE:` in the commit body/footer for major version bumps (1.0.0 → 2.0.0):
```
feat: redesign CLI with subcommands

BREAKING CHANGE: The install command now requires explicit flags.
Use `bear-things-sync install --daemon` instead of `install.sh`.
```

### Documentation

- Update README.md for user-facing changes
- Add docstrings for new functions/classes
- Update type hints as needed

## Project Structure

```
bear-things-sync/
├── src/bear_things_sync/   # Main package
│   ├── bear.py             # Bear database operations
│   ├── things.py           # Things 3 AppleScript operations
│   ├── sync.py             # Main sync logic
│   ├── config.py           # Configuration
│   └── utils.py            # Utility functions
├── tests/                  # Test suite
├── scripts/                # Helper scripts
│   ├── install.sh          # Installation script
│   └── watch_bear.sh       # File watcher
└── .github/workflows/      # CI/CD

```

## Running Locally

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/bear-things-sync.git
cd bear-things-sync

# Set up environment
uv venv
uv pip install -e .

# Run once
python -m bear_things_sync

# Run tests
uv run pytest tests/ -v

# Run quality checks
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run pyright src/
```

## Questions?

Feel free to open an issue with the `question` label if you need help or clarification.

Thank you for contributing! 🎉
