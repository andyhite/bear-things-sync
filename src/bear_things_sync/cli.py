"""Command-line interface for bear-things-sync."""

import argparse
import sys

from . import __version__


def main() -> None:
    """
    Main CLI entry point with subcommands.

    Handles command routing for bear-things-sync. Available commands:
    - sync: Run a one-time sync of todos from Bear to Things 3 (default)
    - install: Install the background daemon for automatic syncing
    - uninstall: Uninstall the background daemon

    If no subcommand is provided, defaults to 'sync' for convenience.
    """
    parser = argparse.ArgumentParser(
        prog="bear-things-sync",
        description="Automatically sync todos from Bear notes to Things 3",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--get-bear-path",
        action="store_true",
        help="Print Bear database directory path (for internal use)",
    )
    parser.add_argument(
        "--get-install-dir",
        action="store_true",
        help="Print installation directory path (for internal use)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
    )

    # Sync command
    subparsers.add_parser(
        "sync",
        help="Run a one-time sync of todos from Bear to Things 3",
    )

    # Install command
    subparsers.add_parser(
        "install",
        help="Install the background daemon for automatic syncing",
    )

    # Uninstall command
    subparsers.add_parser(
        "uninstall",
        help="Uninstall the background daemon",
    )

    args = parser.parse_args()

    # Handle utility flags
    if args.get_bear_path:
        from .config import get_bear_database_directory

        print(get_bear_database_directory())
        return

    if args.get_install_dir:
        from .config import get_install_directory

        print(get_install_directory())
        return

    # Default to sync if no subcommand provided
    if args.command is None:
        args.command = "sync"

    # Route to appropriate function
    if args.command == "sync":
        from .sync import sync

        try:
            sync()
        except Exception as e:
            from .utils import log

            log(f"FATAL ERROR: {e}")
            import traceback

            log(traceback.format_exc())
            sys.exit(1)

    elif args.command == "install":
        from .install import install

        install()

    elif args.command == "uninstall":
        from .uninstall import uninstall

        uninstall()


if __name__ == "__main__":
    main()
