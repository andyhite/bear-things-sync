"""Configuration and constants for bear-things-sync."""

import os
import re
import sys
from pathlib import Path
from typing import Optional

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Data directory - configurable via environment variable
_data_dir_env = os.getenv("BEAR_THINGS_SYNC_DIR")
DATA_DIR = Path(_data_dir_env).expanduser() if _data_dir_env else Path.home() / ".bear-things-sync"

STATE_FILE = DATA_DIR / "sync_state.json"
LOG_FILE = DATA_DIR / "sync_log.txt"
WATCHER_LOG_FILE = DATA_DIR / "watcher_log.txt"
DAEMON_STDOUT_LOG = DATA_DIR / "daemon_stdout.log"
DAEMON_STDERR_LOG = DATA_DIR / "daemon_stderr.log"

# Configuration file
CONFIG_FILE = DATA_DIR / "config.json"


def load_user_config() -> dict:
    """
    Load user configuration from config file if it exists.

    Returns:
        Dictionary with user configuration, or empty dict if file doesn't exist
    """
    if not CONFIG_FILE.exists():
        return {}

    try:
        import json

        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # If config file is invalid, ignore it and use defaults
        return {}


def discover_bear_database() -> Optional[Path]:
    """
    Try to discover Bear database location by searching Group Containers.

    Returns:
        Path to Bear database if found, None otherwise
    """
    # First, check if user has manually configured the path
    user_config = load_user_config()
    if "bear_database_path" in user_config:
        manual_path = Path(user_config["bear_database_path"]).expanduser()
        if manual_path.exists():
            return manual_path
        else:
            print(
                f"WARNING: Configured Bear database path does not exist: {manual_path}",
                file=sys.stderr,
            )

    # Auto-discovery: search Group Containers
    group_containers = Path.home() / "Library/Group Containers"
    if not group_containers.exists():
        return None

    # Search for Bear's container (should match *.net.shinyfrog.bear pattern)
    for container in group_containers.glob("*.net.shinyfrog.bear"):
        db_path = container / "Application Data/database.sqlite"
        if db_path.exists():
            return db_path

    return None


def _prompt_for_bear_database() -> Optional[Path]:
    """
    Prompt user to locate Bear database manually.

    Returns:
        Path provided by user, or None if skipped
    """
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None

    print("\n" + "=" * 70, file=sys.stderr)
    print("Bear database could not be automatically discovered.", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print("\nTroubleshooting steps:", file=sys.stderr)
    print("1. Ensure Bear is installed from the App Store or https://bear.app", file=sys.stderr)
    print("2. Launch Bear at least once to initialize the database", file=sys.stderr)
    print("3. Check that Bear is not sandboxed differently on your system", file=sys.stderr)
    print("\nYou can manually configure the database path in:", file=sys.stderr)
    print(f"  {CONFIG_FILE}", file=sys.stderr)
    print('\nAdd: {"bear_database_path": "/path/to/database.sqlite"}', file=sys.stderr)
    print("=" * 70 + "\n", file=sys.stderr)

    return None


# Todo patterns to match
TODO_PATTERNS = {
    "incomplete": re.compile(r"^[-*]\s+\[ \]\s+(.+)$"),  # Matches "- [ ] task" or "* [ ] task"
    "completed": re.compile(
        r"^[-*]\s+\[x\]\s+(.+)$", re.IGNORECASE
    ),  # Matches "- [x] task" (case-insensitive)
}

# Load user configuration (already defined above)
_user_config = load_user_config()

# Things 3 sync tag (configurable)
THINGS_SYNC_TAG = _user_config.get("sync_tag", "Bear Sync")

# Daemon configuration
DAEMON_LABEL = "com.bear-things-sync"  # Unique identifier for the daemon
DAEMON_PLIST_NAME = f"{DAEMON_LABEL}.plist"
MIN_SYNC_INTERVAL = _user_config.get("min_sync_interval", 10)  # Minimum seconds between syncs
DAEMON_THROTTLE_INTERVAL = _user_config.get(
    "daemon_throttle_interval", 30
)  # Seconds to wait before restarting

# Logging configuration
LOG_MAX_BYTES = _user_config.get("log_max_bytes", 5 * 1024 * 1024)  # 5MB per log file
LOG_BACKUP_COUNT = _user_config.get("log_backup_count", 3)  # Keep 3 backup log files
LOG_LEVEL = _user_config.get("log_level", "INFO")  # INFO, WARNING, ERROR

# Retry configuration
APPLESCRIPT_MAX_RETRIES = _user_config.get("applescript_max_retries", 3)  # Maximum retry attempts
APPLESCRIPT_INITIAL_DELAY = _user_config.get(
    "applescript_initial_delay", 1.0
)  # Initial delay in seconds
APPLESCRIPT_TIMEOUT = _user_config.get("applescript_timeout", 5)  # Timeout in seconds

# Database configuration
SQLITE_TIMEOUT = _user_config.get("sqlite_timeout", 5.0)  # SQLite connection timeout in seconds
SQLITE_LOCK_MAX_RETRIES = _user_config.get("sqlite_lock_max_retries", 3)  # Retries for locked DB
SQLITE_LOCK_INITIAL_DELAY = _user_config.get(
    "sqlite_lock_initial_delay", 0.5
)  # Initial delay for lock retry

# Command timeouts
COMMAND_TIMEOUT = _user_config.get("command_timeout", 5)  # General command timeout in seconds

# Embedding configuration for deduplication
SIMILARITY_THRESHOLD = _user_config.get("similarity_threshold", 0.85)  # Moderate threshold
EMBEDDING_MODEL = _user_config.get(
    "embedding_model", "sentence-transformers/all-MiniLM-L6-v2"
)  # Model for embeddings
EMBEDDING_CACHE_MAX_AGE_DAYS = _user_config.get(
    "embedding_cache_max_age_days", 7
)  # Expire old embeddings

# Bi-directional sync configuration
BIDIRECTIONAL_SYNC = _user_config.get("bidirectional_sync", True)  # Enable bi-directional sync
SYNC_COOLDOWN = _user_config.get("sync_cooldown", 5)  # Cooldown in seconds to prevent ping-pong

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)


def discover_things_database() -> Optional[Path]:
    """
    Try to discover Things 3 database location.

    Returns:
        Path to Things 3 database if found, None otherwise
    """
    # First, check if user has manually configured the path
    user_config = load_user_config()
    if "things_database_path" in user_config:
        manual_path = Path(user_config["things_database_path"]).expanduser()
        if manual_path.exists():
            return manual_path
        else:
            print(
                f"WARNING: Configured Things database path does not exist: {manual_path}",
                file=sys.stderr,
            )

    # Auto-discovery: search Group Containers for Things
    group_containers = Path.home() / "Library/Group Containers"
    if not group_containers.exists():
        return None

    # Search for Things container (JLMPQHK86H.com.culturedcode.ThingsMac)
    for container in group_containers.glob("*.com.culturedcode.ThingsMac"):
        # Look for ThingsData-* directories
        for data_dir in container.glob("ThingsData-*"):
            db_path = data_dir / "Things Database.thingsdatabase/main.sqlite"
            if db_path.exists():
                return db_path

    return None


# Bear database - use discovery as primary method
_discovered_db = discover_bear_database()
if _discovered_db:
    BEAR_DATABASE_PATH = _discovered_db
else:
    # If discovery fails, prompt user and provide placeholder
    _prompt_for_bear_database()
    # Use placeholder path that will fail with clear error message
    BEAR_DATABASE_PATH = Path.home() / ".bear-things-sync" / "BEAR_DATABASE_NOT_FOUND"

# Things 3 database - use discovery
_discovered_things_db = discover_things_database()
if _discovered_things_db:
    THINGS_DATABASE_PATH = _discovered_things_db
else:
    # Use placeholder path (bi-directional sync will be disabled if Things DB not found)
    THINGS_DATABASE_PATH = Path.home() / ".bear-things-sync" / "THINGS_DATABASE_NOT_FOUND"


def get_bear_database_directory() -> str:
    """
    Get the directory containing Bear's database.

    Used by shell scripts to avoid hard-coding paths.

    Returns:
        Full path to Bear's Application Data directory
    """
    if BEAR_DATABASE_PATH.exists():
        return str(BEAR_DATABASE_PATH.parent)

    # If database doesn't exist yet, return the expected directory
    # based on discovery or fallback path
    _discovered_db = discover_bear_database()
    if _discovered_db:
        return str(_discovered_db.parent)

    # Return empty string if not found (caller should handle)
    return ""


def get_install_directory() -> Path:
    """
    Get the installation directory for bear-things-sync.

    Can be configured via BEAR_THINGS_SYNC_DIR environment variable.

    Returns:
        Path to installation directory
    """
    return DATA_DIR
