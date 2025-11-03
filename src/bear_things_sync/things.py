"""Things 3 operations via AppleScript."""

import subprocess
import time
import traceback
from functools import wraps
from typing import Any, Optional

from .config import (
    APPLESCRIPT_INITIAL_DELAY,
    APPLESCRIPT_MAX_RETRIES,
    APPLESCRIPT_TIMEOUT,
)
from .utils import log, strip_emojis


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


def retry_with_backoff(
    max_attempts: int = 3, initial_delay: float = 1.0, default_return: Any = None
):
    """
    Decorator to retry a function with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (doubles each retry)
        default_return: Value to return if all attempts fail
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except subprocess.CalledProcessError as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        log(
                            f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}, "
                            f"retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        delay *= 2
                    else:
                        log(f"All {max_attempts} attempts failed for {func.__name__}")
                        # Log the final error for debugging
                        log(f"Final error: {last_exception}")

            # If all attempts failed, return the specified default value
            return default_return

        return wrapper

    return decorator


def is_things_available() -> bool:
    """
    Check if Things 3 is installed and running.

    Returns:
        True if Things 3 is available, False otherwise
    """
    applescript = """
    tell application "System Events"
        return exists application process "Things3"
    end tell
    """

    try:
        output = _run_applescript(applescript)
        return output.lower() == "true"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def get_projects() -> dict[str, str]:
    """
    Get list of all project names from Things 3.

    Returns:
        Dict mapping lowercase cleaned names (no emojis) to actual project names
    """
    if not is_things_available():
        log("WARNING: Things 3 is not running. Please launch Things 3 and try again.")
        return {}

    applescript = """
    tell application "Things3"
        set projectList to {}
        repeat with aProject in projects
            set end of projectList to name of aProject
        end repeat
        return projectList
    end tell
    """

    try:
        output = _run_applescript(applescript)
        # Validate output
        if not output:
            log("WARNING: No projects found in Things 3")
            return {}

        # Parse comma-separated list from AppleScript
        project_names = output.split(", ")

        # Return dict for case-insensitive matching with emojis stripped
        projects = {}
        for name in project_names:
            if name:
                cleaned = strip_emojis(name).lower()
                if cleaned:  # Only add if there's text after removing emojis
                    projects[cleaned] = name
        return projects
    except subprocess.CalledProcessError as e:
        log(f"ERROR getting Things projects (AppleScript error): {e.stderr}")
        log(traceback.format_exc())
        return {}
    except OSError as e:
        log(f"ERROR getting Things projects (process error): {e}")
        log(traceback.format_exc())
        return {}


@retry_with_backoff(
    max_attempts=APPLESCRIPT_MAX_RETRIES,
    initial_delay=APPLESCRIPT_INITIAL_DELAY,
    default_return=None,
)
def create_todo(
    title: str, notes: str = "", tags: Optional[list[str]] = None, project: Optional[str] = None
) -> Optional[str]:
    """
    Create a todo in Things 3 using AppleScript.

    Args:
        title: Todo title
        notes: Todo notes
        tags: List of tag names
        project: Project name to add todo to (optional)

    Returns:
        Things 3 todo ID if successful, None otherwise
    """

    # Escape special characters for AppleScript
    def escape_applescript(text: str) -> str:
        """
        Escape special characters for AppleScript string.

        Handles: backslashes, quotes, newlines, tabs, carriage returns.
        """
        # Order matters: escape backslashes first
        text = text.replace("\\", "\\\\")  # Backslash
        text = text.replace('"', '\\"')  # Double quote
        text = text.replace("\n", "\\n")  # Newline
        text = text.replace("\r", "\\r")  # Carriage return
        text = text.replace("\t", "\\t")  # Tab
        return text

    title_escaped = escape_applescript(title)
    notes_escaped = escape_applescript(notes)

    # Build properties dictionary
    properties = [f'name:"{title_escaped}"', f'notes:"{notes_escaped}"']

    # Add tags if provided
    if tags and len(tags) > 0:
        tags_str = ", ".join([escape_applescript(tag) for tag in tags])
        properties.append(f'tag names:"{tags_str}"')

    # Build AppleScript
    if project:
        project_escaped = escape_applescript(project)
        # Create todo directly in the project
        applescript = f'''
        tell application "Things3"
            set targetProject to first project whose name is "{project_escaped}"
            set newToDo to make new to do at end of to dos of targetProject with properties {{{", ".join(properties)}}}
            return id of newToDo
        end tell
        '''
    else:
        applescript = f"""
        tell application "Things3"
            set newToDo to make new to do with properties {{{", ".join(properties)}}}
            return id of newToDo
        end tell
        """

    try:
        things_id = _run_applescript(applescript)
        if not things_id:
            log("ERROR: Things 3 returned empty ID for new todo")
            return None
        return things_id
    except subprocess.CalledProcessError as e:
        log(f"ERROR creating Things todo: {e.stderr}")
        log(traceback.format_exc())
        raise  # Re-raise for retry decorator
    except OSError as e:
        log(f"ERROR creating Things todo (process error): {e}")
        log(traceback.format_exc())
        return None


@retry_with_backoff(
    max_attempts=APPLESCRIPT_MAX_RETRIES,
    initial_delay=APPLESCRIPT_INITIAL_DELAY,
    default_return=False,
)
def complete_todo(things_id: str) -> bool:
    """
    Mark a todo as completed in Things 3 using its ID.

    Args:
        things_id: The Things 3 todo ID to complete

    Returns:
        True if successful, False otherwise
    """
    applescript = f'''
    tell application "Things3"
        set theTodo to to do id "{things_id}"
        set status of theTodo to completed
        return true
    end tell
    '''

    try:
        _run_applescript(applescript)
        return True
    except subprocess.CalledProcessError as e:
        log(f"ERROR completing Things todo: {e.stderr}")
        log(traceback.format_exc())
        raise  # Re-raise for retry decorator
    except OSError as e:
        log(f"ERROR completing Things todo (process error): {e}")
        log(traceback.format_exc())
        return False
