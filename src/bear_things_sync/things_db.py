"""Things 3 database operations."""

import sqlite3
import time
import traceback
from typing import Optional

from .config import (
    SQLITE_LOCK_INITIAL_DELAY,
    SQLITE_LOCK_MAX_RETRIES,
    SQLITE_TIMEOUT,
    THINGS_DATABASE_PATH,
)
from .utils import log

# Cache schema validation result to avoid repeated checks
_schema_validated = False
_schema_validation_error: Optional[str] = None


def validate_things_schema() -> tuple[bool, Optional[str]]:
    """
    Validate that the Things database has the expected schema.

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

    if not THINGS_DATABASE_PATH.exists():
        error = f"Things database not found at {THINGS_DATABASE_PATH}"
        _schema_validation_error = error
        _schema_validated = True
        return (False, error)

    try:
        conn = sqlite3.connect(
            f"file:{THINGS_DATABASE_PATH}?mode=ro", uri=True, timeout=SQLITE_TIMEOUT
        )
        cursor = conn.cursor()

        # Check for required tables
        required_tables = {
            "TMTask": ["uuid", "status", "trashed", "title"],
        }

        for table, columns in required_tables.items():
            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                error = (
                    f"Things database schema incompatible: table '{table}' not found. "
                    f"This may be due to a Things 3 update. "
                    f"Please report this issue with your Things 3 version at: "
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
                    f"Things database schema incompatible: "
                    f"table '{table}' missing columns: {', '.join(missing_columns)}. "
                    f"This may be due to a Things 3 update. "
                    f"Please report this issue with your Things 3 version at: "
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
        log("Things database schema validation passed")
        return (True, None)

    except sqlite3.Error as e:
        error = f"Error validating Things database schema: {e}"
        _schema_validation_error = error
        _schema_validated = True
        return (False, error)


def get_completed_things_todos(synced_todo_ids: list[str]) -> set[str]:
    """
    Query Things 3 database for completion status of synced todos.

    Args:
        synced_todo_ids: List of Things 3 IDs we're tracking

    Returns:
        Set of Things 3 IDs that are now completed
    """
    if not synced_todo_ids:
        return set()

    # Validate schema before attempting to query
    is_valid, error_message = validate_things_schema()
    if not is_valid:
        log(f"ERROR: {error_message}")
        return set()

    max_retries = SQLITE_LOCK_MAX_RETRIES
    retry_delay = SQLITE_LOCK_INITIAL_DELAY

    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(
                f"file:{THINGS_DATABASE_PATH}?mode=ro", uri=True, timeout=SQLITE_TIMEOUT
            )
            cursor = conn.cursor()

            # Query for completed status
            # Status values: 0 = incomplete, 3 = completed
            placeholders = ",".join("?" * len(synced_todo_ids))
            query = f"""
            SELECT uuid
            FROM TMTask
            WHERE uuid IN ({placeholders})
            AND status = 3
            AND trashed = 0
            """

            cursor.execute(query, synced_todo_ids)
            completed_ids = {row[0] for row in cursor.fetchall()}

            conn.close()
            log(f"Found {len(completed_ids)} completed todos in Things 3")
            return completed_ids

        except sqlite3.OperationalError as e:
            # Check if it's a database locked error
            if "locked" in str(e).lower():
                if attempt < max_retries - 1:
                    log(
                        f"Things database is locked (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    log(f"ERROR: Things database is locked after {max_retries} attempts")
                    return set()
            else:
                # Other SQLite operational errors
                log(f"ERROR querying Things database (SQLite operational error): {e}")
                log(traceback.format_exc())
                return set()
        except sqlite3.Error as e:
            log(f"ERROR querying Things database (SQLite error): {e}")
            log(traceback.format_exc())
            return set()
        except OSError as e:
            log(f"ERROR accessing Things database (I/O error): {e}")
            log(traceback.format_exc())
            return set()
        except Exception as e:
            # Catch any other unexpected exceptions
            log(f"ERROR querying Things database (unexpected error): {e}")
            log(traceback.format_exc())
            return set()

    # Should never reach here, but return empty set as fallback
    return set()
