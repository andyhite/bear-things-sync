"""Configuration and constants for bear-things-sync."""

import os
import re
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import TomlConfigSettingsSource

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
CONFIG_FILE = DATA_DIR / "config.toml"


class Settings(BaseSettings):
    """
    Application settings loaded from TOML config file and environment variables.

    Environment variables take precedence over config file values.
    Use BEAR_THINGS_SYNC_ prefix for environment variables (e.g., BEAR_THINGS_SYNC_SYNC_TAG).
    """

    model_config = SettingsConfigDict(
        toml_file=CONFIG_FILE,
        env_prefix="BEAR_THINGS_SYNC_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """
        Define the settings sources and their priority.

        Priority (highest to lowest):
        1. Environment variables
        2. TOML config file
        3. Default values
        """
        return (
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            init_settings,
        )

    # Database paths
    bear_database_path: str | None = Field(
        default=None, description="Path to Bear's SQLite database"
    )
    things_database_path: str | None = Field(
        default=None, description="Path to Things 3's SQLite database"
    )

    # Sync configuration
    sync_tag: str = Field(default="Bear Sync", description="Tag to add to synced todos in Things 3")
    bidirectional_sync: bool = Field(
        default=True, description="Enable bi-directional sync (Things → Bear completion)"
    )
    sync_cooldown: int = Field(
        default=5, description="Cooldown in seconds to prevent ping-pong updates"
    )
    min_sync_interval: int = Field(
        default=10, description="Minimum seconds between sync operations"
    )

    # Daemon configuration
    daemon_throttle_interval: int = Field(
        default=30, description="Seconds to wait before restarting daemon"
    )

    # Logging configuration
    log_max_bytes: int = Field(default=5 * 1024 * 1024, description="Maximum bytes per log file")
    log_backup_count: int = Field(default=3, description="Number of backup log files to keep")
    log_level: str = Field(default="INFO", description="Logging level (INFO, WARNING, ERROR)")

    # Retry configuration
    applescript_max_retries: int = Field(
        default=3, description="Maximum retry attempts for AppleScript operations"
    )
    applescript_initial_delay: float = Field(
        default=1.0, description="Initial delay in seconds for AppleScript retries"
    )
    applescript_timeout: int = Field(
        default=5, description="Timeout in seconds for AppleScript operations"
    )

    # Database configuration
    sqlite_timeout: float = Field(default=5.0, description="SQLite connection timeout in seconds")
    sqlite_lock_max_retries: int = Field(
        default=3, description="Maximum retries for locked database"
    )
    sqlite_lock_initial_delay: float = Field(
        default=0.5, description="Initial delay for database lock retry"
    )

    # Command timeouts
    command_timeout: int = Field(default=5, description="General command timeout in seconds")

    # Embedding configuration for deduplication
    similarity_threshold: float = Field(
        default=0.85, description="Similarity threshold for duplicate detection"
    )
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Model name for generating embeddings",
    )
    embedding_cache_max_age_days: int = Field(
        default=7, description="Days to keep embedding cache before expiring"
    )

    # Notification configuration
    enable_notifications: bool = Field(
        default=True, description="Enable macOS notifications for sync events"
    )


def load_settings() -> Settings:
    """
    Load settings from config file and environment variables.

    Returns:
        Settings instance with loaded configuration
    """
    try:
        return Settings()
    except Exception:
        # If config file doesn't exist or is invalid, use defaults
        return Settings.model_construct()


def discover_bear_database(settings: Settings) -> Path | None:
    """
    Try to discover Bear database location by searching Group Containers.

    Args:
        settings: Settings instance with optional configured path

    Returns:
        Path to Bear database if found, None otherwise
    """
    # First, check if user has manually configured the path
    if settings.bear_database_path:
        manual_path = Path(settings.bear_database_path).expanduser()
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


def _prompt_for_bear_database() -> Path | None:
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

# Load settings once at module import
settings = load_settings()

# Daemon configuration
DAEMON_LABEL = "com.bear-things-sync"  # Unique identifier for the daemon
DAEMON_PLIST_NAME = f"{DAEMON_LABEL}.plist"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)


def discover_things_database(settings: Settings) -> Path | None:
    """
    Try to discover Things 3 database location.

    Args:
        settings: Settings instance with optional configured path

    Returns:
        Path to Things 3 database if found, None otherwise
    """
    # First, check if user has manually configured the path
    if settings.things_database_path:
        manual_path = Path(settings.things_database_path).expanduser()
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
_discovered_db = discover_bear_database(settings)
if _discovered_db:
    BEAR_DATABASE_PATH = _discovered_db
else:
    # If discovery fails, prompt user and provide placeholder
    _prompt_for_bear_database()
    # Use placeholder path that will fail with clear error message
    BEAR_DATABASE_PATH = Path.home() / ".bear-things-sync" / "BEAR_DATABASE_NOT_FOUND"

# Things 3 database - use discovery
_discovered_things_db = discover_things_database(settings)
if _discovered_things_db:
    THINGS_DATABASE_PATH = _discovered_things_db
else:
    # Use placeholder path (bi-directional sync will be disabled if Things DB not found)
    THINGS_DATABASE_PATH = Path.home() / ".bear-things-sync" / "THINGS_DATABASE_NOT_FOUND"

# Export settings instance for use throughout the application
__all__ = [
    "settings",
    "Settings",
    "BEAR_DATABASE_PATH",
    "THINGS_DATABASE_PATH",
    "DATA_DIR",
    "STATE_FILE",
    "LOG_FILE",
    "WATCHER_LOG_FILE",
    "DAEMON_STDOUT_LOG",
    "DAEMON_STDERR_LOG",
    "CONFIG_FILE",
    "TODO_PATTERNS",
    "DAEMON_LABEL",
    "DAEMON_PLIST_NAME",
]


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
    _discovered_db = discover_bear_database(settings)
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
