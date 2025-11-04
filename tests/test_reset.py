"""Tests for reset module."""

from bear_things_sync.reset import reset


class TestReset:
    """Test state reset functionality."""

    def test_reset_removes_state_file(self, tmp_path, mocker, capsys):
        """Reset should remove the state file if it exists."""
        # Create a state file
        state_file = tmp_path / "sync_state.json"
        state_file.write_text('{"test": "data"}')
        assert state_file.exists()

        # Mock config to use our temp directory
        mocker.patch("bear_things_sync.reset.STATE_FILE", state_file)

        # Run reset
        reset()

        # Verify state file was deleted
        assert not state_file.exists()

        # Verify success message was printed
        captured = capsys.readouterr()
        assert "State has been reset successfully" in captured.out

    def test_reset_handles_nonexistent_state_file(self, tmp_path, mocker, capsys):
        """Reset should handle case when state file doesn't exist."""
        # Use a state file that doesn't exist
        state_file = tmp_path / "sync_state.json"
        assert not state_file.exists()

        # Mock config to use our temp directory
        mocker.patch("bear_things_sync.reset.STATE_FILE", state_file)

        # Run reset
        reset()

        # Verify it completes without error
        captured = capsys.readouterr()
        assert "State has been reset successfully" in captured.out
        assert not state_file.exists()

    def test_reset_with_confirmation(self, tmp_path, mocker, capsys):
        """Reset should display information about what will be reset."""
        # Create a state file
        state_file = tmp_path / "sync_state.json"
        state_file.write_text('{"test": "data"}')

        # Mock config to use our temp directory
        mocker.patch("bear_things_sync.reset.STATE_FILE", state_file)

        # Run reset
        reset()

        # Verify informative output
        captured = capsys.readouterr()
        assert "Resetting sync state" in captured.out
        assert str(state_file) in captured.out
