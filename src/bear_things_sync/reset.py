"""Reset sync state functionality."""

from .config import STATE_FILE


def reset() -> None:
    """
    Reset the sync state by removing the state file.

    This will cause all todos to be re-synced on the next sync operation,
    as the system will have no record of previously synced todos.

    The state file is located at: ~/.bear-things-sync/sync_state.json
    (or the custom location specified by BEAR_THINGS_SYNC_DIR environment variable)
    """
    print(f"Resetting sync state at: {STATE_FILE}")

    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print("State file removed.")
    else:
        print("State file does not exist (already reset).")

    print("\nState has been reset successfully.")
    print("All todos will be re-synced on the next sync operation.")
