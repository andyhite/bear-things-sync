"""Installation script for bear-things-sync launchd daemon."""

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from string import Template
from typing import Optional

from .config import (
    BEAR_DATABASE_PATH,
    COMMAND_TIMEOUT,
    DAEMON_LABEL,
    DAEMON_PLIST_NAME,
    DAEMON_STDERR_LOG,
    DAEMON_THROTTLE_INTERVAL,
    LOG_FILE,
    WATCHER_LOG_FILE,
    get_install_directory,
)


def validate_prerequisites() -> list[str]:
    """
    Validate all prerequisites for installation.

    Returns:
        List of error messages (empty if all prerequisites are met)
    """
    errors = []
    warnings = []

    # Check macOS version (requires 10.14+ for launchd features)
    try:
        import platform

        macos_version = platform.mac_ver()[0]
        if macos_version:
            major, minor, *_ = macos_version.split(".")
            if int(major) == 10 and int(minor) < 14:
                errors.append(
                    f"macOS version {macos_version} is too old. "
                    "Requires macOS 10.14 (Mojave) or later."
                )
    except (ValueError, IndexError, OSError):
        # If we can't determine version, just continue with a warning
        warnings.append("Could not determine macOS version")

    # Check for Bear database
    if not BEAR_DATABASE_PATH.exists():
        errors.append(
            f"Bear database not found at {BEAR_DATABASE_PATH}. "
            "Please launch Bear at least once to initialize the database."
        )

    # Check for Things 3 using system search
    things_found = False
    try:
        # Use mdfind to locate Things 3 by bundle identifier
        result = subprocess.run(
            ["mdfind", "kMDItemCFBundleIdentifier == 'com.culturedcode.ThingsMac'"],
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            things_found = True
        else:
            # Fallback: check common locations
            common_paths = [
                Path("/Applications/Things3.app"),
                Path.home() / "Applications/Things3.app",
            ]
            things_found = any(p.exists() for p in common_paths)
    except subprocess.TimeoutExpired:
        # If mdfind times out, check common locations as fallback
        common_paths = [
            Path("/Applications/Things3.app"),
            Path.home() / "Applications/Things3.app",
        ]
        things_found = any(p.exists() for p in common_paths)

    if not things_found:
        errors.append(
            "Things 3 not found. "
            "Please install Things 3 from the App Store or https://culturedcode.com/things/"
        )

    # Check for fswatch
    if not detect_command_path("fswatch"):
        errors.append("fswatch not found in PATH. Install with: brew install fswatch")

    # Check for bear-things-sync command
    if not detect_command_path("bear-things-sync"):
        errors.append(
            "bear-things-sync command not found in PATH. "
            "The package may not be installed correctly."
        )

    # Print warnings if any
    if warnings:
        for warning in warnings:
            print(f"⚠ WARNING: {warning}")
        print()

    return errors


def detect_command_path(command: str) -> Optional[str]:
    """
    Detect the full path to a command using 'which'.

    Args:
        command: Command name to find

    Returns:
        Full path to command if found, None otherwise
    """
    try:
        result = subprocess.run(
            ["which", command], capture_output=True, text=True, check=True, timeout=COMMAND_TIMEOUT
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def build_path_env() -> str:
    """
    Build a comprehensive PATH environment variable for launchd.

    Returns:
        PATH string with all necessary directories
    """
    paths = []

    # Add current user's PATH directories
    current_path = os.environ.get("PATH", "")
    if current_path:
        paths.extend(current_path.split(":"))

    # Ensure standard macOS paths are included
    standard_paths = [
        "/usr/local/bin",  # Homebrew on Intel
        "/opt/homebrew/bin",  # Homebrew on Apple Silicon
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]

    for path in standard_paths:
        if path not in paths:
            paths.append(path)

    # Remove empty strings and duplicates while preserving order
    seen = set()
    unique_paths = []
    for path in paths:
        if path and path not in seen:
            seen.add(path)
            unique_paths.append(path)

    return ":".join(unique_paths)


def get_package_root() -> Path:
    """Get the root directory of the installed package."""
    return Path(__file__).parent


def find_template_file(filename: str) -> Optional[Path]:
    """
    Find a template file using importlib.resources.

    Handles both installed packages and editable/development installs.

    Args:
        filename: Name of template file to find

    Returns:
        Path to template file if found, None otherwise
    """
    try:
        # Try to get the file from package resources
        # In Python 3.9+, resources.files() returns a traversable object
        package_files = resources.files("bear_things_sync")
        template_file = package_files / filename

        # Check if the resource exists and is readable
        if template_file.is_file():
            # For Python 3.9+, we need to use as_file() context manager
            # but for install we need a persistent path, so we'll extract it
            return Path(str(template_file))

        # Fallback for development: check project structure
        package_root = get_package_root()
        if filename == "watch_bear.sh":
            dev_path = package_root.parent.parent / "scripts" / filename
        else:  # daemon.plist.template
            dev_path = package_root.parent.parent / "templates" / filename

        if dev_path.exists():
            return dev_path

    except (ImportError, FileNotFoundError, AttributeError):
        # If importlib.resources fails, fall back to manual path construction
        package_root = get_package_root()
        installed_path = package_root / filename
        if installed_path.exists():
            return installed_path

        # Check development location (project root)
        if filename == "watch_bear.sh":
            dev_path = package_root.parent.parent / "scripts" / filename
        else:  # daemon.plist.template
            dev_path = package_root.parent.parent / "templates" / filename

        if dev_path.exists():
            return dev_path

    # Not found
    return None


def copy_installation_files(install_dir: Path) -> tuple[Path, Path]:
    """
    Copy template files to installation directory.

    Args:
        install_dir: Directory to install files to

    Returns:
        Tuple of (watcher_script_path, plist_path)
    """
    # Create install directory
    install_dir.mkdir(parents=True, exist_ok=True)
    print(f"Install directory: {install_dir}")
    print()

    # Find template files
    watcher_template = find_template_file("watch_bear.sh")
    plist_template = find_template_file("daemon.plist.template")

    # Check if templates exist
    if not watcher_template:
        print("ERROR: Watcher template not found")
        print("Searched in package and project scripts/ directory")
        sys.exit(1)
    if not plist_template:
        print("ERROR: Plist template not found")
        print("Searched in package and project templates/ directory")
        sys.exit(1)

    # Copy and configure watcher script
    print("Installing watcher script...")
    watcher_output = install_dir / "watch_bear.sh"
    shutil.copy(watcher_template, watcher_output)
    watcher_output.chmod(0o755)  # Make executable
    print(f"✓ Installed: {watcher_output}")
    print()

    return watcher_output, plist_template


def generate_plist_config(install_dir: Path, plist_template: Path) -> Path:
    """
    Generate launchd plist from template.

    Args:
        install_dir: Installation directory
        plist_template: Path to plist template file

    Returns:
        Path to generated plist file
    """
    print("Generating launchd plist...")

    # Dependencies already validated in prerequisites check
    print("Configuring installation...")
    fswatch_path = detect_command_path("fswatch")
    bear_sync_path = detect_command_path("bear-things-sync")
    print(f"✓ Using fswatch: {fswatch_path}")
    print(f"✓ Using bear-things-sync: {bear_sync_path}")
    print()

    # Build PATH environment
    path_env = build_path_env()
    print(f"Generated PATH for daemon: {path_env}")
    print()

    # Generate plist from template
    template_content = plist_template.read_text()
    template = Template(template_content)
    plist_content = template.substitute(
        DAEMON_LABEL=DAEMON_LABEL,
        INSTALL_DIR=str(install_dir),
        HOME=str(Path.home()),
        PATH=path_env,
        THROTTLE_INTERVAL=DAEMON_THROTTLE_INTERVAL,
    )
    plist_output = install_dir / DAEMON_PLIST_NAME
    plist_output.write_text(plist_content)
    print(f"✓ Generated: {plist_output}")
    print()

    return plist_output


def install_and_load_daemon(plist_path: Path) -> bool:
    """
    Install plist to LaunchAgents and load the daemon.

    Args:
        plist_path: Path to plist file to install

    Returns:
        True if installation succeeded, False otherwise
    """
    launch_agents_dir = Path.home() / "Library/LaunchAgents"
    plist_name = DAEMON_PLIST_NAME

    # Ask user if they want to install the daemon with input validation
    while True:
        try:
            response = (
                input("Install to ~/Library/LaunchAgents/ and start the daemon? (y/n) ")
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("\nInstallation cancelled.")
            return False

        if response in ("y", "yes", "n", "no"):
            break
        print("Please enter 'y' or 'n'")

    if response not in ("y", "yes"):
        print("Skipped installation. To install manually:")
        print(f"  cp {plist_path} ~/Library/LaunchAgents/")
        print(f"  launchctl load ~/Library/LaunchAgents/{plist_name}")
        return False

    # Check if daemon is already loaded
    try:
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
        if DAEMON_LABEL in result.stdout:
            print("Daemon is already running. Unloading first...")
            subprocess.run(
                ["launchctl", "unload", str(launch_agents_dir / plist_name)],
                check=False,
                capture_output=True,
            )
    except (subprocess.SubprocessError, OSError):
        pass

    # Copy plist
    print("Installing plist...")
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(plist_path, launch_agents_dir / plist_name)
    print(f"✓ Copied to: {launch_agents_dir / plist_name}")
    print()

    # Load daemon
    print("Loading daemon...")
    try:
        subprocess.run(
            ["launchctl", "load", str(launch_agents_dir / plist_name)],
            check=True,
            capture_output=True,
        )
        print("✓ Daemon loaded and running")
        print()
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to load daemon: {e.stderr.decode()}")
        print()
        return False


def verify_daemon_running(install_dir: Path) -> None:
    """
    Verify that the daemon is running.

    Args:
        install_dir: Installation directory for log file paths
    """
    print("Checking daemon status...")
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
    if DAEMON_LABEL in result.stdout:
        print("✓ Daemon is running!")
    else:
        print("✗ WARNING: Daemon may not be running. Check logs:")
        print(f"  tail -f {DAEMON_STDERR_LOG}")


def install() -> None:
    """Install the bear-things-sync daemon."""
    print("=" * 50)
    print("Bear to Things 3 Sync - Installation")
    print("=" * 50)
    print()

    # Validate prerequisites first
    print("Validating prerequisites...")
    prerequisite_errors = validate_prerequisites()
    if prerequisite_errors:
        print("✗ Prerequisites check failed:")
        print()
        for error in prerequisite_errors:
            print(f"  • {error}")
        print()
        print("Please resolve the above issues before installing.")
        sys.exit(1)
    print("✓ All prerequisites met")
    print()

    # Installation directory - use centralized config
    install_dir = get_install_directory()

    # Copy installation files
    _watcher_output, plist_template = copy_installation_files(install_dir)

    # Generate plist configuration
    plist_output = generate_plist_config(install_dir, plist_template)

    # Install and load daemon
    installed = install_and_load_daemon(plist_output)

    # Verify daemon is running if installation succeeded
    if installed:
        verify_daemon_running(install_dir)

    print()
    print("=" * 50)
    print("Installation complete!")
    print("=" * 50)
    print()
    print("View logs:")
    print(f"  tail -f {LOG_FILE}")
    print(f"  tail -f {WATCHER_LOG_FILE}")
    print()
    print("Check daemon status:")
    print("  launchctl list | grep bear-things-sync")
    print()
    print("Uninstall:")
    print("  bear-things-sync uninstall")
    print()
