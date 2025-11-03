"""Uninstallation script for bear-things-sync launchd daemon."""

import shutil
import subprocess
from pathlib import Path

from .config import DAEMON_LABEL, DAEMON_PLIST_NAME, get_install_directory


def uninstall() -> None:
    """Uninstall the bear-things-sync daemon."""
    print("=" * 50)
    print("Bear to Things 3 Sync - Uninstallation")
    print("=" * 50)
    print()

    launch_agents_dir = Path.home() / "Library/LaunchAgents"
    plist_path = launch_agents_dir / DAEMON_PLIST_NAME

    # Check if plist exists
    if not plist_path.exists():
        print("✓ Daemon is not installed (plist not found)")
        print()
        return

    # Check if daemon is running
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)

    if DAEMON_LABEL in result.stdout:
        print("Stopping daemon...")
        try:
            subprocess.run(
                ["launchctl", "unload", str(plist_path)], check=True, capture_output=True
            )
            print("✓ Daemon stopped")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to stop daemon: {e.stderr.decode()}")

    # Remove plist
    print("Removing plist...")
    plist_path.unlink()
    print(f"✓ Removed: {plist_path}")
    print()

    # Ask about data directory - use centralized config
    install_dir = get_install_directory()
    if install_dir.exists():
        print(f"Data directory exists: {install_dir}")
        print("Contents:")
        print("  - Logs (sync_log.txt, watcher_log.txt, etc.)")
        print("  - State file (sync_state.json)")
        print("  - Watcher script and plist")
        print()
        while True:
            try:
                response = input("Remove data directory? (y/n) ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nKeeping data directory.")
                response = "n"
                break

            if response in ("y", "yes", "n", "no"):
                break
            print("Please enter 'y' or 'n'")

        if response in ("y", "yes"):
            shutil.rmtree(install_dir)
            print(f"✓ Removed: {install_dir}")
        else:
            print(f"Kept data directory: {install_dir}")

    print()
    print("=" * 50)
    print("Uninstallation complete!")
    print("=" * 50)
    print()

    # Check if package is still installed
    result = subprocess.run(
        ["pip", "show", "bear-things-sync"], capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        print("To completely remove the package:")
        print("  pip uninstall bear-things-sync")
        print("  # or")
        print("  uv pip uninstall bear-things-sync")
        print()
