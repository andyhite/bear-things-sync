"""Utility functions for bear-things-sync."""

import fcntl
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .config import LOG_FILE, STATE_FILE, settings

# Configure rotating file handler for logs
_logger = None


def _reset_logger() -> None:
    """Reset the logger (useful for testing)."""
    global _logger
    if _logger is not None:
        for handler in _logger.handlers[:]:
            handler.close()
            _logger.removeHandler(handler)
        _logger = None


def _get_logger() -> logging.Logger:
    """Get or create the logger with rotating file handler."""
    global _logger
    if _logger is None:
        _logger = logging.getLogger("bear_things_sync")
        # Map string log level to logging constant
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        _logger.setLevel(level_map.get(settings.log_level.upper(), logging.INFO))
        _logger.handlers.clear()  # Clear any existing handlers

        # Ensure parent directory exists
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Add rotating file handler
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)

    return _logger


def log(message: str, level: str = "INFO") -> None:
    """
    Log message to file and stdout with automatic rotation.

    Args:
        message: Message to log
        level: Log level (INFO, WARNING, ERROR)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] {message}"
    print(log_message)

    # Write to file using logger with appropriate level
    logger = _get_logger()
    level_upper = level.upper()
    if level_upper == "ERROR":
        logger.error(log_message)
    elif level_upper == "WARNING":
        logger.warning(log_message)
    else:
        logger.info(log_message)


def load_state() -> dict[str, Any]:
    """
    Load sync state to track already synced todos.

    Uses file locking to prevent concurrent access issues.
    If main file is corrupted, attempts to restore from backup.

    Returns:
        State dictionary or empty dict if file doesn't exist
    """
    if not STATE_FILE.exists():
        return {}

    try:
        with open(STATE_FILE) as f:
            # Acquire shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                # Release lock
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (json.JSONDecodeError, OSError) as e:
        log(f"ERROR loading state file: {e}")
        # Try to restore from backup
        backup_file = STATE_FILE.with_suffix(".json.backup")
        if backup_file.exists():
            log("Attempting to restore from backup...")
            try:
                with open(backup_file) as f:
                    state = json.load(f)
                    log("Successfully restored state from backup")
                    # Save the restored state as the main file
                    save_state(state)
                    return state
            except (json.JSONDecodeError, OSError) as backup_error:
                log(f"ERROR: Backup file also corrupted: {backup_error}")
        return {}


def save_state(state: dict[str, Any]) -> None:
    """
    Save sync state using atomic write to prevent corruption.

    Uses temporary file and rename for atomicity, plus file locking
    to prevent concurrent modification. Creates a backup before overwriting.

    Args:
        state: State dictionary to save
    """
    try:
        # Ensure directory exists
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Create backup of existing state file before overwriting
        if STATE_FILE.exists():
            backup_file = STATE_FILE.with_suffix(".json.backup")
            try:
                import shutil

                shutil.copy2(STATE_FILE, backup_file)
            except OSError as backup_error:
                # Log but don't fail if backup creation fails
                log(f"WARNING: Failed to create backup: {backup_error}")

        # Write to temporary file first (atomic operation)
        temp_fd, temp_path = tempfile.mkstemp(
            dir=STATE_FILE.parent, prefix=".sync_state_", suffix=".tmp"
        )

        try:
            with open(temp_fd, "w") as f:
                # Acquire exclusive lock for writing
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(state, f, indent=2)
                    f.flush()
                    # Ensure data is written to disk
                    os.fsync(f.fileno())
                finally:
                    # Release lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Atomic rename (replaces old file)
            Path(temp_path).replace(STATE_FILE)
        except Exception:
            # Clean up temp file on error
            Path(temp_path).unlink(missing_ok=True)
            raise
    except OSError as e:
        log(f"ERROR saving state file: {e}")


def cleanup_state(state: dict[str, Any], current_note_ids: set[str]) -> tuple[dict[str, Any], int]:
    """
    Remove state entries for notes that no longer exist.

    Args:
        state: Current state dict
        current_note_ids: Set of note IDs that currently exist in Bear

    Returns:
        Cleaned state dict and count of removed entries
    """
    removed_count = 0
    notes_to_remove = []

    for note_id in state:
        # Skip special keys (metadata) that start with underscore
        if note_id.startswith("_"):
            continue
        if note_id not in current_note_ids:
            notes_to_remove.append(note_id)

    for note_id in notes_to_remove:
        del state[note_id]
        removed_count += 1

    return state, removed_count


def pascal_to_title_case(text: str) -> str:
    """
    Convert PascalCase to Title Case.

    Examples:
        "TrainingTools" -> "Training Tools"
        "Fitness" -> "Fitness"
        "MyProjectName" -> "My Project Name"
    """
    # Insert space before capital letters (except at the start)
    result = re.sub(r"(?<!^)(?=[A-Z])", " ", text)
    return result


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """
    Return singular or plural form based on count.

    Args:
        count: The count to check
        singular: Singular form of the word
        plural: Plural form (defaults to singular + 's')

    Returns:
        Appropriate form with count

    Examples:
        pluralize(1, "todo") -> "1 todo"
        pluralize(2, "todo") -> "2 todos"
        pluralize(1, "entry", "entries") -> "1 entry"
        pluralize(3, "entry", "entries") -> "3 entries"
    """
    if plural is None:
        plural = f"{singular}s"
    word = singular if count == 1 else plural
    return f"{count} {word}"


# Emoji regex pattern - compile once at module level for performance
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map symbols
    "\U0001f1e0-\U0001f1ff"  # flags (iOS)
    "\U00002702-\U000027b0"  # dingbats
    "\U000024c2-\U0001f251"
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols and pictographs extended-a
    "\U00002600-\U000026ff"  # miscellaneous symbols
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Remove emojis and extra whitespace from text."""
    # Remove emojis using pre-compiled pattern
    result = _EMOJI_PATTERN.sub("", text)
    # Remove zero-width joiners and other invisible characters
    result = result.replace("\u200d", "")  # Zero-width joiner
    result = result.replace("\ufe0f", "")  # Variation selector
    # Collapse multiple spaces into single space and strip
    result = re.sub(r"\s+", " ", result).strip()
    return result


def generate_todo_id(note_id: str, todo_text: str) -> str:
    """
    Generate a stable ID for a todo based on note ID and content hash.

    This replaces the old line-number based system which was fragile when
    notes were edited. Content-based hashing is more stable across edits.

    Args:
        note_id: The Bear note ID
        todo_text: The todo text content

    Returns:
        Unique todo ID in format: {note_id}:{hash}

    Examples:
        >>> generate_todo_id("ABC123", "Buy groceries")
        'ABC123:e8f3a2b1'
    """
    # Create hash of todo text (first 8 chars of SHA256)
    # Normalize text: strip whitespace and lowercase for consistent hashing
    normalized_text = todo_text.strip().lower()
    text_hash = hashlib.sha256(normalized_text.encode()).hexdigest()[:8]
    return f"{note_id}:{text_hash}"


def find_todo_by_fuzzy_match(
    todo_text: str, synced_todos: dict[str, dict], note_id: str
) -> str | None:
    """
    Find a synced todo by fuzzy matching when exact hash doesn't match.

    This helps recover from cases where todo text was slightly modified
    (e.g., whitespace changes, typo fixes).

    Args:
        todo_text: The todo text to find
        synced_todos: Dict of synced todos to search
        note_id: The note ID to scope the search

    Returns:
        Todo ID if found, None otherwise
    """
    normalized_target = todo_text.strip().lower()

    for todo_id, todo_state in synced_todos.items():
        # Skip todos from other notes
        if not todo_id.startswith(f"{note_id}:"):
            continue

        # Check if we have the original text stored
        if "text" in todo_state:
            normalized_stored = todo_state["text"].strip().lower()
            # Exact match after normalization
            if normalized_stored == normalized_target:
                return todo_id

    return None


def send_notification(title: str, message: str, sound: bool = False) -> bool:
    """
    Send a macOS notification using AppleScript.

    Args:
        title: Notification title
        message: Notification message body
        sound: Whether to play notification sound

    Returns:
        True if notification was sent successfully, False otherwise
    """
    # Check if notifications are enabled in config
    if not settings.enable_notifications:
        return False

    try:
        # Build AppleScript for notification
        sound_param = ' sound name "default"' if sound else ""
        applescript = f"""
        display notification "{message}" with title "{title}"{sound_param}
        """

        subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # Silently fail if notification can't be sent
        return False
