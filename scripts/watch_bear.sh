#!/bin/bash
#
# Bear to Things 3 Sync - File Watcher
# Monitors Bear's database for changes and triggers todo sync
# This script is installed to ~/.bear-things-sync/ by the installer
#

set -e

# Configuration
# Get Bear database directory dynamically (avoids hard-coding container ID)
BEAR_DIR=$(bear-things-sync --get-bear-path)
# Get installation directory dynamically (respects BEAR_THINGS_SYNC_DIR env var)
INSTALL_DIR=$(bear-things-sync --get-install-dir)
LOG_FILE="$INSTALL_DIR/watcher_log.txt"

# Minimum seconds between syncs to avoid thrashing
MIN_SYNC_INTERVAL=10
LAST_SYNC_TIME=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_dependencies() {
    if ! command -v fswatch &> /dev/null; then
        log "ERROR: fswatch not found. Install with: brew install fswatch"
        exit 1
    fi

    if ! command -v bear-things-sync &> /dev/null; then
        log "ERROR: bear-things-sync command not found. Is the package installed?"
        exit 1
    fi

    # Validate Bear directory
    if [ -z "$BEAR_DIR" ]; then
        log "ERROR: Bear directory could not be determined."
        log "Bear database discovery failed. Please check your Bear installation."
        log "Troubleshooting:"
        log "  1. Ensure Bear is installed and launched at least once"
        log "  2. Check ~/.bear-things-sync/config.json for 'bear_database_path' setting"
        log "  3. Run 'bear-things-sync --get-bear-path' to see what path is detected"
        exit 1
    fi

    if [ ! -d "$BEAR_DIR" ]; then
        log "ERROR: Bear directory not found at $BEAR_DIR"
        log "The directory path was determined but does not exist."
        log "Is Bear installed and have you launched it at least once?"
        exit 1
    fi

    # Validate installation directory
    if [ -z "$INSTALL_DIR" ]; then
        log "ERROR: Installation directory could not be determined."
        exit 1
    fi
}

run_sync() {
    local current_time=$(date +%s)
    local time_diff=$((current_time - LAST_SYNC_TIME))

    if [ $time_diff -lt $MIN_SYNC_INTERVAL ]; then
        log "Skipping sync (too soon since last sync: ${time_diff}s)"
        return
    fi

    log "Database changed, triggering sync..."
    if bear-things-sync; then
        LAST_SYNC_TIME=$current_time
    else
        log "ERROR: Sync failed"
    fi
}

main() {
    log "========================================="
    log "Bear to Things 3 Sync Watcher Starting"
    log "========================================="
    log "Monitoring: $BEAR_DIR"
    log "Minimum sync interval: ${MIN_SYNC_INTERVAL}s"
    log ""

    check_dependencies

    # Run initial sync
    log "Running initial sync..."
    bear-things-sync
    LAST_SYNC_TIME=$(date +%s)

    # Start monitoring
    log "Starting file watcher..."
    log "Press Ctrl+C to stop"
    log ""

    # Monitor Bear's database directory
    # -r = recursive, -e Updated = only file update events
    fswatch -r -e ".*" -i "database\\.sqlite.*" --event Updated "$BEAR_DIR" | while read -r file
    do
        log "File changed: $file"
        run_sync
    done
}

# Handle Ctrl+C gracefully
trap 'log "Watcher stopped"; exit 0' SIGINT SIGTERM

main
