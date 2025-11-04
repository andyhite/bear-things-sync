"""Bear to Things 3 Todo Sync.

Automatically syncs uncompleted todos from Bear notes to Things 3.
"""

from importlib.metadata import PackageNotFoundError, version

from .sync import execute as sync

try:
    __version__ = version("bear-things-sync")
except PackageNotFoundError:
    # Package is not installed (development mode)
    __version__ = "0.0.0+dev"

__all__ = ["sync"]
