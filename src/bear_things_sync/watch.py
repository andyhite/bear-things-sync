"""File watcher for continuous sync monitoring."""

import sys
import time

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import BEAR_DATABASE_PATH, BIDIRECTIONAL_SYNC, THINGS_DATABASE_PATH
from .sync import sync
from .utils import log


class DatabaseEventHandler(FileSystemEventHandler):
    """
    Handler for database file change events.

    Monitors specific database files and triggers syncs with appropriate throttling.
    """

    def __init__(self, source: str, min_sync_interval: float = 10.0):
        """
        Initialize event handler.

        Args:
            source: Which database this handler monitors ('bear' or 'things')
            min_sync_interval: Minimum seconds between syncs to avoid thrashing
        """
        super().__init__()
        self.source = source
        self.min_sync_interval = min_sync_interval
        self.last_sync_time = 0

    def should_sync(self, event: FileSystemEvent) -> bool:
        """
        Determine if this event should trigger a sync.

        Args:
            event: The filesystem event

        Returns:
            True if sync should be triggered
        """
        # Only respond to modifications
        if event.event_type != "modified":
            return False

        # Check file patterns
        if self.source == "bear":
            # Bear database files
            if "database.sqlite" not in event.src_path:
                return False
        else:  # things
            # Things 3 database files
            if "main.sqlite" not in event.src_path:
                return False

        # Check throttle interval
        current_time = time.time()
        time_since_last = current_time - self.last_sync_time

        if time_since_last < self.min_sync_interval:
            log(
                f"Skipping {self.source} sync (too soon since last: {time_since_last:.1f}s)",
                "DEBUG",
            )
            return False

        return True

    def on_modified(self, event: FileSystemEvent) -> None:
        """
        Handle file modification events.

        Args:
            event: The filesystem event
        """
        if not self.should_sync(event):
            return

        log(f"{self.source.title()} database changed: {event.src_path}")

        try:
            sync(source=self.source)
            self.last_sync_time = time.time()
        except Exception as e:
            log(f"ERROR: Sync from {self.source} failed: {e}", "ERROR")
            import traceback

            log(traceback.format_exc(), "ERROR")


def watch() -> None:
    """
    Start watching database files for changes.

    Monitors both Bear and Things 3 databases (if bi-directional sync is enabled)
    and triggers syncs automatically.
    """
    log("========================================")
    log("Bear Things Sync - File Watcher")
    log("========================================")

    # Validate Bear database
    if not BEAR_DATABASE_PATH.exists():
        log(f"ERROR: Bear database not found at {BEAR_DATABASE_PATH}", "ERROR")
        log("Please ensure Bear is installed and has been launched at least once.", "ERROR")
        sys.exit(1)

    bear_dir = BEAR_DATABASE_PATH.parent
    log(f"Monitoring Bear: {bear_dir}")

    # Check Things 3 database for bi-directional sync
    things_dir = None
    if BIDIRECTIONAL_SYNC:
        if THINGS_DATABASE_PATH.exists():
            things_dir = THINGS_DATABASE_PATH.parent
            log(f"Monitoring Things 3: {things_dir}")
        else:
            log("WARNING: Things 3 database not found", "WARNING")
            log("Bi-directional sync disabled - only Bear → Things 3 will work", "WARNING")

    log("")

    # Run initial sync
    log("Running initial sync...")
    try:
        sync(source="bear")
    except Exception as e:
        log(f"Initial sync failed: {e}", "ERROR")
        import traceback

        log(traceback.format_exc(), "ERROR")

    log("")
    log("Starting file watchers...")
    log("Press Ctrl+C to stop")
    log("")

    # Create observer and handlers
    observer = Observer()

    # Monitor Bear database
    bear_handler = DatabaseEventHandler(source="bear", min_sync_interval=10.0)
    observer.schedule(bear_handler, str(bear_dir), recursive=False)

    # Monitor Things 3 database if available
    if things_dir:
        things_handler = DatabaseEventHandler(source="things", min_sync_interval=10.0)
        observer.schedule(things_handler, str(things_dir), recursive=False)

    # Start watching
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Stopping watchers...")
        observer.stop()
        log("Watcher stopped")

    observer.join()
