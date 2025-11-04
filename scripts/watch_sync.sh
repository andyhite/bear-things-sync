#!/bin/bash
#
# Bear to Things 3 Bi-directional Sync - File Watcher
# Monitors both Bear and Things 3 databases for changes and triggers syncs
# This script is installed to ~/.bear-things-sync/ by the installer
#

set -e

# Configuration
# Get Bear database directory dynamically (avoids hard-coding container ID)
BEAR_DIR=$(bear-things-sync --get-bear-path)
# Get installation directory dynamically (respects BEAR_THINGS_SYNC_DIR env var)
INSTALL_DIR=$(bear-things-sync --get-install-dir)
LOG_FILE="$INSTALL_DIR/watcher_log.txt"

# Things 3 database path
THINGS_DIR="$HOME/Library/Group Containers"
THINGS_DB=""

# Find Things 3 database
find_things_db() {
    for container in "$THINGS_DIR"/*.com.culturedcode.ThingsMac; do
        if [ -d "$container" ]; then
            for data_dir in "$container"/ThingsData-*; do
                if [ -d "$data_dir" ]; then
                    THINGS_DB="$data_dir/Things Database.thingsdatabase"
                    if [ -d "$THINGS_DB" ]; then
                        return 0
                    fi
                fi
            done
        fi
    done
    return 1
}

# Minimum seconds between syncs to avoid thrashing
MIN_SYNC_INTERVAL=10
LAST_BEAR_SYNC_TIME=0
LAST_THINGS_SYNC_TIME=0

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

    # Find Things 3 database
    if ! find_things_db; then
        log "WARNING: Things 3 database not found."
        log "Bi-directional sync will not be available."
        log "Only Bear → Things 3 sync will work."
        THINGS_DB=""
    elif [ ! -d "$THINGS_DB" ]; then
        log "WARNING: Things 3 database path found but directory does not exist: $THINGS_DB"
        log "Bi-directional sync will not be available."
        THINGS_DB=""
    else
        log "Things 3 database found at: $THINGS_DB"
    fi

    # Validate installation directory
    if [ -z "$INSTALL_DIR" ]; then
        log "ERROR: Installation directory could not be determined."
        exit 1
    fi
}

run_bear_sync() {
    local current_time=$(date +%s)
    local time_diff=$((current_time - LAST_BEAR_SYNC_TIME))

    if [ $time_diff -lt $MIN_SYNC_INTERVAL ]; then
        log "Skipping Bear sync (too soon since last sync: ${time_diff}s)"
        return
    fi

    log "Bear database changed, triggering sync..."
    if bear-things-sync --source bear; then
        LAST_BEAR_SYNC_TIME=$current_time
    else
        log "ERROR: Bear sync failed"
    fi
}

run_things_sync() {
    local current_time=$(date +%s)
    local time_diff=$((current_time - LAST_THINGS_SYNC_TIME))

    if [ $time_diff -lt $MIN_SYNC_INTERVAL ]; then
        log "Skipping Things sync (too soon since last sync: ${time_diff}s)"
        return
    fi

    log "Things 3 database changed, triggering sync..."
    if bear-things-sync --source things; then
        LAST_THINGS_SYNC_TIME=$current_time
    else
        log "ERROR: Things sync failed"
    fi
}

main() {
    log "========================================="
    log "Bear ↔ Things 3 Bi-directional Sync Watcher Starting"
    log "========================================="
    log "Monitoring Bear: $BEAR_DIR"
    if [ -n "$THINGS_DB" ]; then
        log "Monitoring Things 3: $THINGS_DB"
    else
        log "Things 3 monitoring: DISABLED"
    fi
    log "Minimum sync interval: ${MIN_SYNC_INTERVAL}s"
    log ""

    check_dependencies

    # Run initial sync
    log "Running initial sync..."
    bear-things-sync --source bear
    LAST_BEAR_SYNC_TIME=$(date +%s)

    # Start monitoring
    log "Starting file watchers..."
    log "Press Ctrl+C to stop"
    log ""

    # Monitor Bear's database directory
    # -r = recursive, -e = exclude pattern, -i = include pattern
    fswatch -r -e ".*" -i "database\\.sqlite.*" --event Updated "$BEAR_DIR" | while read -r file
    do
        log "Bear file changed: $file"
        run_bear_sync
    done &

    BEAR_PID=$!

    # Monitor Things 3 database if available
    if [ -n "$THINGS_DB" ]; then
        fswatch -r -e ".*" -i "main\\.sqlite.*" --event Updated "$THINGS_DB" | while read -r file
        do
            log "Things file changed: $file"
            run_things_sync
        done &

        THINGS_PID=$!
    fi

    # Wait for both watchers
    if [ -n "$THINGS_DB" ]; then
        wait $BEAR_PID $THINGS_PID
    else
        wait $BEAR_PID
    fi
}

# Handle Ctrl+C gracefully
cleanup() {
    log "Stopping watchers..."
    # Kill background processes
    jobs -p | xargs -r kill 2>/dev/null || true
    log "Watcher stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM

main
