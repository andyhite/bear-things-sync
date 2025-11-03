"""Tests for sync module."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from bear_things_sync.sync import sync


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
            [("Circuit",)],  # Tags for note-123
            [("🔋 Circuit",)],  # Projects query - areas
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

        sync()

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

        sync()

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

        sync()

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

        sync()

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
                result.stdout = "🔋 Circuit"
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
            [("Circuit",), ("ExtraTag",)],
        ]
        mocker.patch("bear_things_sync.bear.sqlite3.connect", return_value=mock_conn)
        mocker.patch("bear_things_sync.bear.validate_bear_schema", return_value=(True, None))
        mocker.patch("bear_things_sync.bear.BEAR_DATABASE_PATH", Path("/fake/path"))

        # Mock file I/O
        state_file = tmp_path / "state.json"
        mocker.patch("bear_things_sync.utils.STATE_FILE", state_file)
        log_file = tmp_path / "log.txt"
        mocker.patch("bear_things_sync.utils.LOG_FILE", log_file)

        sync()

        # Verify create was called with project
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        assert len(create_calls) == 1
        assert 'project whose name is "🔋 Circuit"' in str(create_calls[0])

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

        sync()

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

        sync()

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

        sync()

        # Verify state was migrated
        migrated_state = json.loads(state_file.read_text())
        assert isinstance(migrated_state["note-123"]["synced_todos"], dict)
        assert migrated_state["_version"] == 3

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

        sync()

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

        sync()

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

        sync()

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

        sync()

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

        sync()

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
            [("Circuit",)],
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

        sync()

        # Should create todo without project
        create_calls = [
            call for call in mock_subprocess.call_args_list if "make new to do" in str(call)
        ]
        # Should NOT have "project whose name" since no project matched
        assert "project whose name" not in str(create_calls[0])
