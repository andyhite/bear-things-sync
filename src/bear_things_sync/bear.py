"""Bear note database operations."""

import re
import sqlite3
import subprocess
import time
import traceback
from typing import Any, Optional

from .config import (
    APPLESCRIPT_INITIAL_DELAY,
    APPLESCRIPT_MAX_RETRIES,
    APPLESCRIPT_TIMEOUT,
    BEAR_DATABASE_PATH,
    SQLITE_LOCK_INITIAL_DELAY,
    SQLITE_LOCK_MAX_RETRIES,
    SQLITE_TIMEOUT,
    TODO_PATTERNS,
)
from .utils import log

# Cache schema validation result to avoid repeated checks
_schema_validated = False
_schema_validation_error: Optional[str] = None


def validate_bear_schema() -> tuple[bool, Optional[str]]:
    """
    Validate that the Bear database has the expected schema.

    This checks for the existence of required tables and columns.
    Results are cached to avoid repeated validation.

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if schema is compatible, False otherwise
        - error_message: Description of the issue if invalid, None if valid
    """
    global _schema_validated, _schema_validation_error

    # Return cached result if already validated
    if _schema_validated:
        return (
            (True, None) if _schema_validation_error is None else (False, _schema_validation_error)
        )

    if not BEAR_DATABASE_PATH.exists():
        error = f"Bear database not found at {BEAR_DATABASE_PATH}"
        _schema_validation_error = error
        _schema_validated = True
        return (False, error)

    try:
        conn = sqlite3.connect(
            f"file:{BEAR_DATABASE_PATH}?mode=ro", uri=True, timeout=SQLITE_TIMEOUT
        )
        cursor = conn.cursor()

        # Check for required tables
        required_tables = {
            "ZSFNOTE": ["ZUNIQUEIDENTIFIER", "ZTITLE", "ZTEXT", "Z_PK", "ZTRASHED", "ZARCHIVED"],
            "Z_5TAGS": ["Z_5NOTES", "Z_13TAGS"],
            "ZSFNOTETAG": ["Z_PK", "ZTITLE"],
        }

        for table, columns in required_tables.items():
            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                error = (
                    f"Bear database schema incompatible: table '{table}' not found. "
                    f"This may be due to a Bear update. "
                    f"Please report this issue with your Bear version at: "
                    f"https://github.com/andyhite/bear-things-sync/issues"
                )
                conn.close()
                _schema_validation_error = error
                _schema_validated = True
                return (False, error)

            # Check if required columns exist
            cursor.execute(f"PRAGMA table_info({table})")
            existing_columns = {row[1] for row in cursor.fetchall()}

            missing_columns = set(columns) - existing_columns
            if missing_columns:
                error = (
                    f"Bear database schema incompatible: "
                    f"table '{table}' missing columns: {', '.join(missing_columns)}. "
                    f"This may be due to a Bear update. "
                    f"Please report this issue with your Bear version at: "
                    f"https://github.com/andyhite/bear-things-sync/issues"
                )
                conn.close()
                _schema_validation_error = error
                _schema_validated = True
                return (False, error)

        conn.close()

        # Schema is valid
        _schema_validated = True
        _schema_validation_error = None
        log("Bear database schema validation passed")
        return (True, None)

    except sqlite3.Error as e:
        error = f"Error validating Bear database schema: {e}"
        _schema_validation_error = error
        _schema_validated = True
        return (False, error)


def get_notes_with_todos() -> list[dict[str, Any]]:
    """
    Query Bear's SQLite database for notes containing todos.

    Returns:
        List of dicts with keys: id, title, content, tags
    """
    # Validate schema before attempting to query
    is_valid, error_message = validate_bear_schema()
    if not is_valid:
        log(f"ERROR: {error_message}")
        return []

    max_retries = SQLITE_LOCK_MAX_RETRIES
    retry_delay = SQLITE_LOCK_INITIAL_DELAY

    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(
                f"file:{BEAR_DATABASE_PATH}?mode=ro", uri=True, timeout=SQLITE_TIMEOUT
            )
            cursor = conn.cursor()

            # Query notes table
            # ZSFNOTE table contains notes, ZTEXT has content
            query = """
            SELECT ZUNIQUEIDENTIFIER, ZTITLE, ZTEXT, Z_PK
            FROM ZSFNOTE
            WHERE ZTRASHED = 0 AND ZARCHIVED = 0
            """

            cursor.execute(query)
            notes = []

            for row in cursor.fetchall():
                note_id, title, content, note_pk = row
                if content and any(
                    pattern in content for pattern in ["- [ ]", "* [ ]", "- [x]", "* [x]"]
                ):
                    # Get tags for this note
                    tags_query = """
                    SELECT ZSFNOTETAG.ZTITLE
                    FROM Z_5TAGS
                    JOIN ZSFNOTETAG ON Z_5TAGS.Z_13TAGS = ZSFNOTETAG.Z_PK
                    WHERE Z_5TAGS.Z_5NOTES = ?
                    """
                    cursor.execute(tags_query, (note_pk,))
                    tags = [tag[0] for tag in cursor.fetchall() if tag[0]]

                    notes.append(
                        {
                            "id": note_id,
                            "title": title or "Untitled",
                            "content": content,
                            "tags": tags,
                        }
                    )

            conn.close()
            log(f"Found {len(notes)} notes with todos")
            return notes

        except sqlite3.OperationalError as e:
            # Check if it's a database locked error
            if "locked" in str(e).lower():
                if attempt < max_retries - 1:
                    log(
                        f"Database is locked (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    log(f"ERROR: Bear database is locked after {max_retries} attempts")
                    return []
            else:
                # Other SQLite operational errors
                log(f"ERROR querying Bear database (SQLite operational error): {e}")
                log(traceback.format_exc())
                return []
        except sqlite3.Error as e:
            log(f"ERROR querying Bear database (SQLite error): {e}")
            log(traceback.format_exc())
            return []
        except OSError as e:
            log(f"ERROR accessing Bear database (I/O error): {e}")
            log(traceback.format_exc())
            return []
        except Exception as e:
            # Catch any other unexpected exceptions
            log(f"ERROR querying Bear database (unexpected error): {e}")
            log(traceback.format_exc())
            return []

    # Should never reach here, but return empty list as fallback
    return []


def extract_todos(content: str) -> list[dict[str, Any]]:
    """
    Extract todos from note content (both complete and incomplete).

    Args:
        content: Note content string

    Returns:
        List of dicts with keys: text, line, completed
    """
    todos = []
    lines = content.split("\n")

    for line_num, line in enumerate(lines):
        line_stripped = line.strip()

        # Check for incomplete todos
        match = TODO_PATTERNS["incomplete"].match(line_stripped)
        if match:
            todos.append({"text": match.group(1).strip(), "line": line_num, "completed": False})
            continue

        # Check for completed todos
        match = TODO_PATTERNS["completed"].match(line_stripped)
        if match:
            todos.append({"text": match.group(1).strip(), "line": line_num, "completed": True})

    return todos


def _run_applescript(script: str, timeout: int = APPLESCRIPT_TIMEOUT) -> str:
    """
    Execute an AppleScript and return the output.

    Args:
        script: AppleScript code to execute
        timeout: Timeout in seconds

    Returns:
        Script output as string

    Raises:
        subprocess.CalledProcessError: If script execution fails
    """
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def _escape_applescript(text: str) -> str:
    """
    Escape special characters for AppleScript string.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for AppleScript
    """
    # Order matters: escape backslashes first
    text = text.replace("\\", "\\\\")  # Backslash
    text = text.replace('"', '\\"')  # Double quote
    text = text.replace("\n", "\\n")  # Newline
    text = text.replace("\r", "\\r")  # Carriage return
    text = text.replace("\t", "\\t")  # Tab
    return text


def complete_todo_in_note(note_id: str, todo_text: str, note_content: str) -> bool:
    """
    Mark a todo as complete in a Bear note using x-callback-url.

    Args:
        note_id: Bear note unique identifier
        todo_text: The todo text to find and mark complete
        note_content: Current note content (from database)

    Returns:
        True if successful, False otherwise
    """
    max_attempts = APPLESCRIPT_MAX_RETRIES
    delay = APPLESCRIPT_INITIAL_DELAY

    for attempt in range(max_attempts):
        try:
            # Find and replace the todo in content
            lines = note_content.split("\n")
            modified = False
            new_lines = []

            for line in lines:
                line_stripped = line.strip()

                # Check if this line contains the todo we're looking for
                # Try both "- [ ]" and "* [ ]" patterns
                for prefix in ["-", "*"]:
                    pattern = rf"^{re.escape(prefix)}\s+\[ \]\s+(.+)$"
                    match = re.match(pattern, line_stripped)

                    if match and match.group(1).strip() == todo_text:
                        # Replace [ ] with [x]
                        new_line = re.sub(r"\[ \]", "[x]", line, count=1)
                        new_lines.append(new_line)
                        modified = True
                        break
                else:
                    # No match, keep original line
                    new_lines.append(line)

            if not modified:
                log(f"WARNING: Todo '{todo_text}' not found in note {note_id}")
                return False

            # Update note content via x-callback-url
            new_content = "\n".join(new_lines)

            # URL encode the content and note ID
            import urllib.parse

            encoded_text = urllib.parse.quote(new_content)
            encoded_id = urllib.parse.quote(note_id)

            # Use Bear's x-callback-url scheme to replace note content
            url = f"bear://x-callback-url/add-text?id={encoded_id}&mode=replace_all&text={encoded_text}&open_note=no"

            # Open the URL to trigger Bear (use -g to not activate/focus Bear)
            subprocess.run(["open", "-g", url], check=True, timeout=APPLESCRIPT_TIMEOUT)

            # Give Bear a moment to process
            time.sleep(0.5)

            log(f"Marked todo complete in Bear: '{todo_text}' in note {note_id}")
            return True

        except subprocess.CalledProcessError as e:
            if attempt < max_attempts - 1:
                log(
                    f"Attempt {attempt + 1}/{max_attempts} failed for complete_todo_in_note, "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
            else:
                log(f"ERROR: Failed to complete todo in Bear after {max_attempts} attempts: {e}")
                log(traceback.format_exc())
                return False
        except subprocess.TimeoutExpired:
            if attempt < max_attempts - 1:
                log(
                    f"URL scheme timeout (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
            else:
                log(f"ERROR: URL scheme timeout after {max_attempts} attempts")
                return False
        except Exception as e:
            log(f"ERROR completing todo in Bear: {e}")
            log(traceback.format_exc())
            return False

    return False


def uncomplete_todo_in_note(note_id: str, todo_text: str, note_content: str) -> bool:
    """
    Mark a todo as incomplete in a Bear note using x-callback-url.

    Args:
        note_id: Bear note unique identifier
        todo_text: The todo text to find and mark incomplete
        note_content: Current note content (from database)

    Returns:
        True if successful, False otherwise
    """
    max_attempts = APPLESCRIPT_MAX_RETRIES
    delay = APPLESCRIPT_INITIAL_DELAY

    for attempt in range(max_attempts):
        try:
            # Find and replace the todo in content
            lines = note_content.split("\n")
            modified = False
            new_lines = []

            for line in lines:
                line_stripped = line.strip()

                # Check if this line contains the completed todo we're looking for
                # Try both "- [x]" and "* [x]" patterns
                for prefix in ["-", "*"]:
                    pattern = rf"^{re.escape(prefix)}\s+\[x\]\s+(.+)$"
                    match = re.match(pattern, line_stripped)

                    if match and match.group(1).strip() == todo_text:
                        # Replace [x] with [ ]
                        new_line = re.sub(r"\[x\]", "[ ]", line, count=1)
                        new_lines.append(new_line)
                        modified = True
                        break
                else:
                    # No match, keep original line
                    new_lines.append(line)

            if not modified:
                log(f"WARNING: Completed todo '{todo_text}' not found in note {note_id}")
                return False

            # Update note content via x-callback-url
            new_content = "\n".join(new_lines)

            # URL encode the content and note ID
            import urllib.parse

            encoded_text = urllib.parse.quote(new_content)
            encoded_id = urllib.parse.quote(note_id)

            # Use Bear's x-callback-url scheme to replace note content
            url = f"bear://x-callback-url/add-text?id={encoded_id}&mode=replace_all&text={encoded_text}&open_note=no"

            # Open the URL to trigger Bear (use -g to not activate/focus Bear)
            subprocess.run(["open", "-g", url], check=True, timeout=APPLESCRIPT_TIMEOUT)

            # Give Bear a moment to process
            time.sleep(0.5)

            log(f"Marked todo incomplete in Bear: '{todo_text}' in note {note_id}")
            return True

        except subprocess.CalledProcessError as e:
            if attempt < max_attempts - 1:
                log(
                    f"Attempt {attempt + 1}/{max_attempts} failed for uncomplete_todo_in_note, "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
            else:
                log(f"ERROR: Failed to uncomplete todo in Bear after {max_attempts} attempts: {e}")
                log(traceback.format_exc())
                return False
        except subprocess.TimeoutExpired:
            if attempt < max_attempts - 1:
                log(
                    f"URL scheme timeout (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
            else:
                log(f"ERROR: URL scheme timeout after {max_attempts} attempts")
                return False
        except Exception as e:
            log(f"ERROR uncompleting todo in Bear: {e}")
            log(traceback.format_exc())
            return False

    return False
