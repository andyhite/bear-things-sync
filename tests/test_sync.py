"""Tests for sync module."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from bear_things_sync.sync import execute


class TestSync:
    """Test main sync orchestration."""

    def test_sync_new_todo(self, mocker, tmp_path):
        # Mock subprocess (Things 3 calls)
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "things-id-123"
        mock_subprocess.return_value = mock_result

        # Mock is_things_available
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 (Bear database)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # get_notes_with_todos, tags query, get_projects (3 queries)
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [ ] Test todo", 123)],  # Notes
            [("Fitness",)],  # Tags for note-123
            [("🏃 Fitness",)],  # Projects query - areas
            [(None,)],  # Projects query - inbox
            [(None,)],  # Projects query - projects
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Verify Things API was called
        assert mock_subprocess.called
        # Verify state was saved
        assert state_file.exists()

    def test_sync_no_notes(self, mocker, tmp_path):
        # Mock sqlite3 - return no notes
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should not save state when no notes
        assert not state_file.exists()

    def test_sync_skips_already_synced(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [ ] Test todo", 123)],
            [],  # No tags
            [(None,)],  # get_projects - areas
            [(None,)],  # get_projects - inbox
            [(None,)],  # get_projects - projects
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O with existing state
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "_version": 3,
                    "note-123": {
                        "title": "Test Note",
                        "synced_todos": {
                            "note-123:c3e9be0a": {  # Hash of "Test todo"
                                "things_id": "existing-id",
                                "completed": False,
                                "text": "Test todo",
                            }
                        },
                    },
                }
            )
        )
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should NOT call Things create API since already synced
        # get_projects calls subprocess once, but create_todo should not
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        assert len(create_calls) == 0

    def test_sync_completes_todo(self, mocker, tmp_path):
        # Mock subprocess - get_projects returns empty, complete_todo succeeds
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")

        def subprocess_side_effect(*args, **kwargs):
            result = MagicMock()
            result.stdout = ""  # Empty projects, successful complete
            return result

        mock_subprocess.side_effect = subprocess_side_effect
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 - note has completed todo
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [x] Test todo", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O with existing incomplete todo
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "_version": 3,
                    "note-123": {
                        "title": "Test Note",
                        "synced_todos": {
                            "note-123:c3e9be0a": {
                                "things_id": "things-id-123",
                                "completed": False,
                                "text": "Test todo",
                            }
                        },
                    },
                }
            )
        )
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should call Things API to complete the todo
        applescript_calls = [str(call) for call in mock_subprocess.call_args_list]
        assert any("status of theTodo to completed" in call for call in applescript_calls)

        # Verify state was updated
        state = json.loads(state_file.read_text())
        assert state["note-123"]["synced_todos"]["note-123:c3e9be0a"]["completed"] is True

    def test_sync_with_project_matching(self, mocker, tmp_path):
        # Mock subprocess with different returns for get_projects vs create_todo
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")

        def subprocess_side_effect(*args, **kwargs):
            result = MagicMock()
            cmd = args[0]
            # get_projects AppleScript returns comma-separated project names
            if "repeat with aProject in projects" in str(cmd):
                result.stdout = "🏃 Fitness"
            # create_todo returns Things ID
            elif "make new to do" in str(cmd):
                result.stdout = "things-id-123"
            else:
                result.stdout = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [ ] Test todo", 123)],
            [("Fitness",), ("ExtraTag",)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Verify create was called with project
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        assert len(create_calls) == 1
        assert 'project whose name is "🏃 Fitness"' in str(create_calls[0])

    def test_sync_pascal_case_tag_conversion(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "things-id-123"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [ ] Test todo", 123)],
            [("TrainingTools",), ("MyProject",)],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Verify tags were converted
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        assert "Training Tools" in str(create_calls[0])
        assert "My Project" in str(create_calls[0])

    def test_sync_skips_completed_todos(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 - only completed todos
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [x] Completed todo", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should not create any todos
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        assert len(create_calls) == 0

    def test_sync_state_migration(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [ ] Test todo", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O with old state format
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "note-123": {
                        "title": "Test Note",
                        "synced_todos": ["note-123:0"],  # Old format: list
                    }
                }
            )
        )
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Verify state was migrated
        migrated_state = json.loads(state_file.read_text())
        assert isinstance(migrated_state["note-123"]["synced_todos"], dict)
        assert migrated_state["_version"] == 5  # Now at v5 with bi-directional sync tracking

    def test_sync_creates_bear_callback_url(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "things-id-123"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-abc-123", "Test Note", "- [ ] Test todo", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Verify Bear callback URL in notes
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        assert "bear://x-callback-url/open-note?id=note-abc-123" in str(create_calls[0])

    def test_sync_multiple_notes(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "things-id"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 - multiple notes
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [
                ("note-1", "Note 1", "- [ ] Todo 1", 1),
                ("note-2", "Note 2", "- [ ] Todo 2", 2),
            ],
            [],  # Tags for note 1
            [],  # Tags for note 2
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should create 2 todos
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        assert len(create_calls) == 2

    def test_sync_handles_create_failure(self, mocker, tmp_path):
        # Mock subprocess to fail for create_todo
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        import subprocess

        def subprocess_side_effect(*args, **kwargs):
            # Let get_projects succeed, but create_todo fails
            cmd = args[0]
            if "make new to do" in str(cmd):
                raise subprocess.CalledProcessError(1, cmd, stderr="Things not available")
            # get_projects queries
            result = MagicMock()
            result.stdout = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mocker.patch("bear_things_sync.things.time.sleep")  # Speed up retries

        # Mock sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [ ] Test todo", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should not save failed todo in state
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        if "note-123" in state:
            assert len(state["note-123"]["synced_todos"]) == 0

    def test_sync_handles_complete_failure(self, mocker, tmp_path):
        # Mock subprocess to fail on complete
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        import subprocess

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            if "status of theTodo to completed" in str(cmd):
                raise subprocess.CalledProcessError(1, cmd, stderr="Complete failed")
            # get_projects queries
            result = MagicMock()
            result.stdout = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mocker.patch("bear_things_sync.things.time.sleep")

        # Mock sqlite3 - completed todo
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [x] Test todo", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O with existing todo
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "_version": 3,
                    "note-123": {
                        "title": "Test Note",
                        "synced_todos": {
                            "note-123:c3e9be0a": {
                                "things_id": "things-id-123",
                                "completed": False,
                                "text": "Test todo",
                            }
                        },
                    },
                }
            )
        )
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should not mark as complete in state
        state = json.loads(state_file.read_text())
        assert state["note-123"]["synced_todos"]["note-123:c3e9be0a"]["completed"] is False

    def test_sync_summary_message(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "things-id"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 - 2 notes
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [
                ("note-1", "Note 1", "- [ ] Todo 1", 1),
                ("note-2", "Note 2", "- [ ] Todo 2", 2),
            ],
            [],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Check log for summary
        if log_file.exists():
            log_content = log_file.read_text()
            assert "2 new todos synced" in log_content

    def test_sync_no_projects(self, mocker, tmp_path):
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "things-id"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note-123", "Test Note", "- [ ] Test todo", 123)],
            [("Fitness",)],
            [(None,)],  # No projects in any query
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        execute()

        # Should create todo without project
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        # Should NOT have "project whose name" since no project matched
        assert "project whose name" not in str(create_calls[0])


# Replacement text for the deduplication tests


class TestDeduplication:
    """Test embedding-based deduplication logic."""

    def test_sync_with_duplicate_found(self, mocker, tmp_path):
        """Test that duplicate todo is merged instead of created."""
        # Mock subprocess for Things
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "EXISTING123"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 (Bear database)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note1", "Note Title", "- [ ] Review slides", 123)],
            [],  # No tags
            [(None,)],  # get_projects - areas
            [(None,)],  # get_projects - inbox
            [(None,)],  # get_projects - projects
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock get_incomplete_todos to return existing todo
        mocker.patch(
            "bear_things_sync.sync.get_incomplete_todos",
            return_value=[{"id": "EXISTING123", "name": "Review presentation slides"}],
        )

        # Mock embedding functions to find a match
        mocker.patch("bear_things_sync.sync.EMBEDDINGS_AVAILABLE", True)
        mocker.patch(
            "bear_things_sync.sync.find_most_similar",
            return_value=("EXISTING123", 0.92),
        )
        mocker.patch(
            "bear_things_sync.sync.generate_embedding",
            return_value=[0.1, 0.2, 0.3],
        )

        # Mock state file
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        from bear_things_sync.sync import execute

        execute()

        # Verify subprocess was called to update notes (not create todo)
        applescript_calls = [str(call) for call in mock_subprocess.call_args_list]
        update_calls = [call for call in applescript_calls if "currentNotes" in call]
        create_calls = [call for call in applescript_calls if "make new to do" in call]

        assert len(update_calls) > 0  # Should have updated notes
        assert len(create_calls) == 0  # Should NOT have created new todo

    def test_sync_with_no_duplicate(self, mocker, tmp_path):
        """Test that todo is created when no duplicate found."""
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "NEW123"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 (Bear database)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note1", "Note Title", "- [ ] Unique task", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock get_incomplete_todos
        mocker.patch(
            "bear_things_sync.sync.get_incomplete_todos",
            return_value=[{"id": "OTHER123", "name": "Completely different"}],
        )

        # Mock embeddings to return no match
        mocker.patch("bear_things_sync.sync.EMBEDDINGS_AVAILABLE", True)
        mocker.patch("bear_things_sync.sync.find_most_similar", return_value=None)
        mocker.patch("bear_things_sync.sync.generate_embedding", return_value=[0.5, 0.5, 0.0])

        # Mock state file
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        from bear_things_sync.sync import execute

        execute()

        # Verify subprocess was called to create todo
        applescript_calls = [str(call) for call in mock_subprocess.call_args_list]
        create_calls = [call for call in applescript_calls if "make new to do" in call]
        assert len(create_calls) > 0  # Should have created new todo

    def test_sync_with_embeddings_disabled(self, mocker, tmp_path):
        """Test fallback behavior when embeddings unavailable."""
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "NEW123"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock sqlite3 (Bear database)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note1", "Note Title", "- [ ] Some task", 123)],
            [],
            [(None,)],
            [(None,)],
            [(None,)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock embeddings as unavailable
        mocker.patch("bear_things_sync.sync.EMBEDDINGS_AVAILABLE", False)

        # Mock get_incomplete_todos (should NOT be called when embeddings disabled)
        mock_get_incomplete = mocker.patch("bear_things_sync.sync.get_incomplete_todos")

        # Mock state file
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        from bear_things_sync.sync import execute

        execute()

        # Should create todo without checking for duplicates
        applescript_calls = [str(call) for call in mock_subprocess.call_args_list]
        create_calls = [call for call in applescript_calls if "make new to do" in call]
        assert len(create_calls) > 0
        assert not mock_get_incomplete.called

    def test_sync_with_project_scoped_deduplication(self, mocker, tmp_path):
        """Test that deduplication is scoped to matched project."""
        # Mock subprocess
        mock_subprocess = mocker.patch("bear_things_sync.things.subprocess.run")
        mock_result = MagicMock()
        mock_result.stdout = "NEW123"
        mock_subprocess.return_value = mock_result
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock get_projects to return Work project
        mocker.patch("bear_things_sync.sync.get_projects", return_value={"work": "Work"})

        # Mock sqlite3 (Bear database) with tag that matches a project
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = [
            [("note1", "Note Title", "- [ ] Review slides", 123)],
            [("Work",)],  # Tags for this note
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock get_incomplete_todos
        mock_get_incomplete = mocker.patch(
            "bear_things_sync.sync.get_incomplete_todos",
            return_value=[{"id": "WORK123", "name": "Review presentation"}],
        )

        # Mock embeddings
        mocker.patch("bear_things_sync.sync.EMBEDDINGS_AVAILABLE", True)
        mocker.patch("bear_things_sync.sync.find_most_similar", return_value=None)
        mocker.patch("bear_things_sync.sync.generate_embedding", return_value=[0.1, 0.2, 0.3])

        # Mock state file
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        from bear_things_sync.sync import execute

        execute()

        # Verify get_incomplete_todos was called with project="Work"
        mock_get_incomplete.assert_called_with(project="Work")

    def test_cache_cleanup_removes_old_entries(self, mocker):
        """Test that old cache entries are removed."""
        from datetime import datetime, timedelta

        from bear_things_sync.sync import _cleanup_embedding_cache

        # Create state with old and new cache entries
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        recent_date = datetime.now().isoformat()

        state = {
            "_embedding_cache": {
                "old_todo": {
                    "text": "Old todo",
                    "embedding": [0.1, 0.2],
                    "last_seen": old_date,
                },
                "recent_todo": {
                    "text": "Recent todo",
                    "embedding": [0.3, 0.4],
                    "last_seen": recent_date,
                },
                "no_timestamp": {
                    "text": "No timestamp",
                    "embedding": [0.5, 0.6],
                },
            }
        }

        removed_count = _cleanup_embedding_cache(state)

        # Should remove old_todo and no_timestamp
        assert removed_count == 2
        assert "old_todo" not in state["_embedding_cache"]
        assert "no_timestamp" not in state["_embedding_cache"]
        assert "recent_todo" in state["_embedding_cache"]

    def test_state_v4_migration(self, mocker):
        """Test migration from v3 to v4 adds embedding cache."""
        from bear_things_sync.sync import _migrate_to_v4

        state = {
            "note1": {
                "title": "Note",
                "synced_todos": {
                    "todo1": {
                        "things_id": "ABC123",
                        "completed": False,
                        "text": "Test todo",
                    }
                },
            }
        }

        _migrate_to_v4(state)

        # Should add embedding cache
        assert "_embedding_cache" in state
        assert state["_embedding_cache"] == {}

        # Should add merged_with field to existing todos
        assert "merged_with" in state["note1"]["synced_todos"]["todo1"]
        assert state["note1"]["synced_todos"]["todo1"]["merged_with"] is None
