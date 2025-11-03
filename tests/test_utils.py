"""Tests for utils module."""

from bear_things_sync.utils import (
    _reset_logger,
    cleanup_state,
    log,
    pascal_to_title_case,
    strip_emojis,
)


class TestPascalToTitleCase:
    """Test PascalCase to Title Case conversion."""

    def test_basic_pascal_case(self):
        assert pascal_to_title_case("TrainingTools") == "Training Tools"
        assert pascal_to_title_case("MyProject") == "My Project"

    def test_single_word(self):
        assert pascal_to_title_case("Circuit") == "Circuit"
        assert pascal_to_title_case("Todo") == "Todo"

    def test_multiple_capitals(self):
        assert pascal_to_title_case("HTMLParser") == "H T M L Parser"
        assert pascal_to_title_case("XMLHttpRequest") == "X M L Http Request"

    def test_empty_string(self):
        assert pascal_to_title_case("") == ""

    def test_already_spaced(self):
        # If text already has spaces, it will add extra spaces before capitals
        assert pascal_to_title_case("Already Spaced") == "Already  Spaced"

    def test_lowercase(self):
        assert pascal_to_title_case("lowercase") == "lowercase"


class TestStripEmojis:
    """Test emoji stripping."""

    def test_emoji_at_start(self):
        assert strip_emojis("🔋 Circuit") == "Circuit"
        assert strip_emojis("🏋️ Training Tools") == "Training Tools"

    def test_emoji_at_end(self):
        assert strip_emojis("Circuit 🔋") == "Circuit"

    def test_emoji_in_middle(self):
        # Emoji removal collapses multiple spaces
        assert strip_emojis("My 🔥 Project") == "My Project"

    def test_multiple_emojis(self):
        assert strip_emojis("🔋 Circuit 🏋️") == "Circuit"
        assert strip_emojis("🔥🔥🔥 Hot Project") == "Hot Project"

    def test_no_emojis(self):
        assert strip_emojis("Plain Text") == "Plain Text"
        assert strip_emojis("Circuit") == "Circuit"

    def test_empty_string(self):
        assert strip_emojis("") == ""

    def test_only_emojis(self):
        assert strip_emojis("🔋🏋️🔥") == ""

    def test_complex_emojis(self):
        # Test with various emoji types including zero-width joiners
        assert strip_emojis("📱 iPhone") == "iPhone"
        assert strip_emojis("❤️ Love") == "Love"
        assert strip_emojis("👨‍💻 Developer") == "Developer"


class TestLog:
    """Test logging function."""

    def test_log_writes_message(self, mocker, tmp_path):
        # Reset logger before test
        _reset_logger()

        # Mock LOG_FILE to use tmp_path
        log_file = tmp_path / "test_log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        message = "Test log message"
        log(message)

        # Verify file was created and contains message
        assert log_file.exists()
        content = log_file.read_text()
        assert message in content
        assert content.startswith("[")  # Timestamp

        # Clean up
        _reset_logger()

    def test_log_appends_messages(self, mocker, tmp_path):
        # Reset logger before test
        _reset_logger()

        log_file = tmp_path / "test_log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        log("First message")
        log("Second message")

        content = log_file.read_text()
        assert "First message" in content
        assert "Second message" in content

        # Clean up
        _reset_logger()

    def test_log_creates_directory_if_not_exists(self, mocker, tmp_path):
        # Reset logger before test
        _reset_logger()

        log_file = tmp_path / "nested" / "dir" / "test_log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        log("Test message")

        assert log_file.exists()
        assert "Test message" in log_file.read_text()

        # Clean up
        _reset_logger()


class TestCleanupState:
    """Test state cleanup function."""

    def test_cleanup_removes_deleted_notes(self):
        state = {
            "note1": {"title": "Note 1", "synced_todos": {}},
            "note2": {"title": "Note 2", "synced_todos": {}},
            "note3": {"title": "Note 3", "synced_todos": {}},
        }
        current_note_ids = {"note1", "note3"}  # note2 was deleted

        cleaned_state, removed_count = cleanup_state(state, current_note_ids)

        assert "note1" in cleaned_state
        assert "note2" not in cleaned_state
        assert "note3" in cleaned_state
        assert removed_count == 1

    def test_cleanup_with_no_deletions(self):
        state = {
            "note1": {"title": "Note 1", "synced_todos": {}},
            "note2": {"title": "Note 2", "synced_todos": {}},
        }
        current_note_ids = {"note1", "note2"}

        cleaned_state, removed_count = cleanup_state(state, current_note_ids)

        assert len(cleaned_state) == 2
        assert removed_count == 0

    def test_cleanup_with_empty_state(self):
        state = {}
        current_note_ids = {"note1", "note2"}

        cleaned_state, removed_count = cleanup_state(state, current_note_ids)

        assert len(cleaned_state) == 0
        assert removed_count == 0

    def test_cleanup_removes_all_notes(self):
        state = {
            "note1": {"title": "Note 1", "synced_todos": {}},
            "note2": {"title": "Note 2", "synced_todos": {}},
        }
        current_note_ids = set()  # All notes deleted

        cleaned_state, removed_count = cleanup_state(state, current_note_ids)

        assert len(cleaned_state) == 0
        assert removed_count == 2

    def test_cleanup_preserves_synced_todos(self):
        state = {
            "note1": {
                "title": "Note 1",
                "synced_todos": {"note1:1": {"things_id": "123", "completed": False}},
            },
            "note2": {
                "title": "Note 2",
                "synced_todos": {"note2:1": {"things_id": "456", "completed": True}},
            },
        }
        current_note_ids = {"note1"}  # note2 deleted

        cleaned_state, removed_count = cleanup_state(state, current_note_ids)

        assert "note1" in cleaned_state
        assert cleaned_state["note1"]["synced_todos"]["note1:1"]["things_id"] == "123"
        assert removed_count == 1
