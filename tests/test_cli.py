"""Tests for CLI module."""

import sys

from bear_things_sync.cli import main


class TestCLI:
    """Test CLI command routing."""

    def test_no_subcommand_runs_sync(self, mocker):
        """When no subcommand is provided, should default to sync."""
        # Mock sys.argv to simulate running without a subcommand
        mocker.patch.object(sys, "argv", ["bear-things-sync"])

        # Mock the execute function in the sync module (where it's defined)
        mock_execute = mocker.patch("bear_things_sync.sync.execute")

        # Run the CLI
        main()

        # Verify execute was called
        assert mock_execute.called

    def test_explicit_sync_command(self, mocker):
        """Explicit sync command should still work."""
        mocker.patch.object(sys, "argv", ["bear-things-sync", "sync"])
        mock_execute = mocker.patch("bear_things_sync.sync.execute")

        main()

        assert mock_execute.called

    def test_install_command(self, mocker):
        """Install command should call install."""
        mocker.patch.object(sys, "argv", ["bear-things-sync", "install"])
        mock_install = mocker.patch("bear_things_sync.install.install")

        main()

        assert mock_install.called

    def test_uninstall_command(self, mocker):
        """Uninstall command should call uninstall."""
        mocker.patch.object(sys, "argv", ["bear-things-sync", "uninstall"])
        mock_uninstall = mocker.patch("bear_things_sync.uninstall.uninstall")

        main()

        assert mock_uninstall.called

    def test_reset_command(self, mocker):
        """Reset command should call reset."""
        mocker.patch.object(sys, "argv", ["bear-things-sync", "reset"])
        mock_reset = mocker.patch("bear_things_sync.reset.reset")

        main()

        assert mock_reset.called
