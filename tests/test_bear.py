"""Tests for bear module."""

from pathlib import Path
from unittest.mock import MagicMock

from bear_things_sync.bear import extract_todos, get_notes_with_todos


class TestExtractTodos:
    """Test todo extraction from note content."""

    def test_extract_incomplete_todos(self):
        content = """
Some text here
- [ ] First todo
- [ ] Second todo
More text
"""
        todos = extract_todos(content)
        assert len(todos) == 2
        assert todos[0]["text"] == "First todo"
        assert todos[0]["completed"] is False
        assert todos[1]["text"] == "Second todo"
        assert todos[1]["completed"] is False

    def test_extract_completed_todos(self):
        content = """
- [x] Completed todo
- [X] Also completed
"""
        todos = extract_todos(content)
        assert len(todos) == 2
        assert todos[0]["text"] == "Completed todo"
        assert todos[0]["completed"] is True
        assert todos[1]["text"] == "Also completed"
        assert todos[1]["completed"] is True

    def test_extract_mixed_todos(self):
        content = """
- [ ] Not done
- [x] Done
- [ ] Also not done
"""
        todos = extract_todos(content)
        assert len(todos) == 3
        assert todos[0]["completed"] is False
        assert todos[1]["completed"] is True
        assert todos[2]["completed"] is False

    def test_asterisk_format(self):
        content = """
* [ ] Asterisk todo
* [x] Completed asterisk
"""
        todos = extract_todos(content)
        assert len(todos) == 2
        assert todos[0]["text"] == "Asterisk todo"
        assert todos[1]["text"] == "Completed asterisk"

    def test_mixed_formats(self):
        content = """
- [ ] Dash incomplete
* [ ] Asterisk incomplete
- [x] Dash complete
* [X] Asterisk complete
"""
        todos = extract_todos(content)
        assert len(todos) == 4

    def test_line_numbers(self):
        content = "First line\n- [ ] Todo\nThird line"
        todos = extract_todos(content)
        assert todos[0]["line"] == 1

    def test_no_todos(self):
        content = "Just some text\nNo todos here"
        todos = extract_todos(content)
        assert len(todos) == 0

    def test_empty_content(self):
        todos = extract_todos("")
        assert len(todos) == 0

    def test_whitespace_handling(self):
        content = "   - [ ]    Todo with spaces   "
        todos = extract_todos(content)
        assert len(todos) == 1
        assert todos[0]["text"] == "Todo with spaces"

    def test_todos_in_list(self):
        content = """
Regular list:
- Not a todo
- [ ] This is a todo
- Also not a todo
"""
        todos = extract_todos(content)
        assert len(todos) == 1
        assert todos[0]["text"] == "This is a todo"


class TestGetNotesWithTodos:
    """Test getting notes from Bear database."""

    def test_database_not_found(self, mocker):
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/nonexistent"))
        mock_log = mocker.patch("bear_things_sync.bear.log")

        notes = get_notes_with_todos()

        assert notes == []
        mock_log.assert_called_once()
        assert "ERROR" in mock_log.call_args[0][0]

    def test_successful_query(self, mocker):
        # Mock schema validation to pass
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))

        # Mock database path
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", mock_path)

        # Mock sqlite3 connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock note data
        mock_cursor.fetchall.side_effect = [
            [("note-id-1", "Test Note", "- [ ] Todo item", 123)],  # Notes query
            [("tag1",), ("tag2",)],  # Tags query for first note
        ]

        mock_connect = mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.log")

        notes = get_notes_with_todos()

        assert len(notes) == 1
        assert notes[0]["id"] == "note-id-1"
        assert notes[0]["title"] == "Test Note"
        assert notes[0]["content"] == "- [ ] Todo item"
        assert notes[0]["tags"] == ["tag1", "tag2"]

        # Verify database opened in read-only mode
        mock_connect.assert_called_once()
        assert "mode=ro" in mock_connect.call_args[0][0]

        mock_conn.close.assert_called_once()

    def test_multiple_notes(self, mocker):
        # Mock schema validation to pass
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", mock_path)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock multiple notes
        mock_cursor.fetchall.side_effect = [
            [
                ("note-1", "First Note", "- [ ] Todo 1", 1),
                ("note-2", "Second Note", "* [ ] Todo 2", 2),
            ],
            [("tag1",)],  # Tags for note 1
            [("tag2",), ("tag3",)],  # Tags for note 2
        ]

        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.log")

        notes = get_notes_with_todos()

        assert len(notes) == 2
        assert notes[0]["id"] == "note-1"
        assert notes[1]["id"] == "note-2"

    def test_note_without_title(self, mocker):
        # Mock schema validation to pass
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", mock_path)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Note with None as title
        mock_cursor.fetchall.side_effect = [
            [(None, None, "- [ ] Todo", 1)],
            [],  # No tags
        ]

        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.log")

        notes = get_notes_with_todos()

        assert notes[0]["title"] == "Untitled"

    def test_filters_non_todo_notes(self, mocker):
        # Mock schema validation to pass
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", mock_path)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mix of notes with and without todos
        mock_cursor.fetchall.side_effect = [
            [
                ("note-1", "With Todo", "- [ ] Todo", 1),
                ("note-2", "No Todo", "Just regular text", 2),
                ("note-3", "Also Todo", "* [x] Done", 3),
            ],
            [("tag1",)],  # Tags for note-1
            [("tag3",)],  # Tags for note-3
        ]

        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.log")

        notes = get_notes_with_todos()

        assert len(notes) == 2
        assert notes[0]["id"] == "note-1"
        assert notes[1]["id"] == "note-3"

    def test_database_error_handling(self, mocker):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", mock_path)

        mocker.patch(
            "bear_things_sync.bear.sqlite3.connect", side_effect=Exception("Database error")
        )
        mock_log = mocker.patch("bear_things_sync.bear.log")

        notes = get_notes_with_todos()

        assert notes == []
        # Should log error and traceback (2 calls)
        assert mock_log.call_count >= 1
        assert any("ERROR" in str(call) for call in mock_log.call_args_list)

    def test_tags_with_none_values(self, mocker):
        # Mock schema validation to pass
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", mock_path)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Tags query returns some None values
        mock_cursor.fetchall.side_effect = [
            [("note-1", "Note", "- [ ] Todo", 1)],
            [("tag1",), (None,), ("tag2",)],  # Mixed with None
        ]

        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.log")

        notes = get_notes_with_todos()

        # Should filter out None tags
        assert notes[0]["tags"] == ["tag1", "tag2"]
