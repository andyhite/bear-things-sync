"""Bear note database operations."""

import sqlite3
import time
import traceback
from typing import Any, Optional

from .config import (
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
