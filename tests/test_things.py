"""Tests for things module."""

import subprocess
from unittest.mock import MagicMock

from bear_things_sync.things import (
    complete_todo,
    create_todo,
    get_incomplete_todos,
    get_projects,
    update_todo_notes,
)


class TestGetProjects:
    """Test getting projects from Things 3."""

    def test_successful_query(self, mocker):
        # Mock is_things_available to return True
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)

        # Mock subprocess to return project names
        mock_result = MagicMock()
        mock_result.stdout = "🏃 Fitness, 🏋️ Training Tools, Personal"
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        projects = get_projects()

        assert len(projects) == 3
        assert projects["fitness"] == "🏃 Fitness"
        assert projects["training tools"] == "🏋️ Training Tools"
        assert projects["personal"] == "Personal"

    def test_empty_project_list(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        mock_result.stdout = ""
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)
        mocker.patch("bear_things_sync.things.log")  # Mock to suppress warning

        projects = get_projects()

        assert projects == {}

    def test_strips_emojis_for_matching(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        mock_result.stdout = "🔥🔥 Hot Project"
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        projects = get_projects()

        assert "hot project" in projects
        assert projects["hot project"] == "🔥🔥 Hot Project"

    def test_case_insensitive_keys(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        mock_result.stdout = "MyProject, UPPERCASE"
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        projects = get_projects()

        assert "myproject" in projects
        assert "uppercase" in projects

    def test_subprocess_error(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mocker.patch(
            "bear_things_sync.things.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "osascript", stderr="Error"),
        )
        mock_log = mocker.patch("bear_things_sync.things.log")

        projects = get_projects()

        assert projects == {}
        # Should log error and traceback
        assert mock_log.call_count >= 1
        assert any("ERROR" in str(call) for call in mock_log.call_args_list)

    def test_filters_only_emoji_projects(self, mocker):
        # If a project name is only emojis, it should be filtered out
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        mock_result.stdout = "Valid Project, 🔥🔥"
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        projects = get_projects()

        assert len(projects) == 1
        assert "valid project" in projects


class TestCreateTodo:
    """Test creating todos in Things 3."""

    def test_basic_todo_creation(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-123"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo("Test Todo")

        assert todo_id == "things-id-123"
        mock_run.assert_called_once()

    def test_todo_with_notes(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-456"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo("Test Todo", notes="Some notes")

        assert todo_id == "things-id-456"
        # Verify notes were included in AppleScript
        applescript = mock_run.call_args[0][0][2]
        assert 'notes:"Some notes"' in applescript

    def test_todo_with_tags(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-789"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo("Test Todo", tags=["Bear Sync", "Fitness"])

        assert todo_id == "things-id-789"
        applescript = mock_run.call_args[0][0][2]
        assert 'tag names:"Bear Sync, Fitness"' in applescript

    def test_todo_with_project(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-abc"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo("Test Todo", project="My Project")

        assert todo_id == "things-id-abc"
        applescript = mock_run.call_args[0][0][2]
        assert 'project whose name is "My Project"' in applescript
        assert "at end of to dos of targetProject" in applescript

    def test_escapes_quotes(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-def"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo('Todo with "quotes"', notes='Notes with "quotes"')

        assert todo_id == "things-id-def"
        applescript = mock_run.call_args[0][0][2]
        assert r"\"" in applescript  # Escaped quotes

    def test_escapes_backslashes(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-ghi"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo("Todo\\with\\backslashes")

        assert todo_id == "things-id-ghi"
        applescript = mock_run.call_args[0][0][2]
        assert "\\\\" in applescript  # Escaped backslashes

    def test_empty_tags_list(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-jkl"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo("Test Todo", tags=[])

        assert todo_id == "things-id-jkl"
        applescript = mock_run.call_args[0][0][2]
        assert "tag names" not in applescript

    def test_subprocess_error(self, mocker):
        # Mock time.sleep to speed up test
        mocker.patch("bear_things_sync.things.time.sleep")
        mocker.patch(
            "bear_things_sync.things.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "osascript", stderr="AppleScript error"),
        )
        mock_log = mocker.patch("bear_things_sync.things.log")

        todo_id = create_todo("Test Todo")

        assert todo_id is None
        # Should log errors for each retry attempt plus tracebacks
        assert mock_log.call_count >= 3  # At least 3 attempts
        # Check that retry messages were logged
        assert any("Attempt" in str(call) for call in mock_log.call_args_list)

    def test_full_todo_with_all_parameters(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "things-id-full"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todo_id = create_todo(
            "Full Todo", notes="With notes", tags=["Tag1", "Tag2"], project="My Project"
        )

        assert todo_id == "things-id-full"
        applescript = mock_run.call_args[0][0][2]
        assert 'name:"Full Todo"' in applescript
        assert 'notes:"With notes"' in applescript
        assert 'tag names:"Tag1, Tag2"' in applescript
        assert 'project whose name is "My Project"' in applescript


class TestCompleteTodo:
    """Test completing todos in Things 3."""

    def test_successful_completion(self, mocker):
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run")

        result = complete_todo("things-id-123")

        assert result is True
        mock_run.assert_called_once()
        applescript = mock_run.call_args[0][0][2]
        assert 'to do id "things-id-123"' in applescript
        assert "status of theTodo to completed" in applescript

    def test_subprocess_error(self, mocker):
        # Mock time.sleep to speed up test
        mocker.patch("bear_things_sync.things.time.sleep")
        mocker.patch(
            "bear_things_sync.things.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "osascript", stderr="Todo not found"),
        )
        mock_log = mocker.patch("bear_things_sync.things.log")

        result = complete_todo("nonexistent-id")

        assert result is False
        # Should log errors for each retry attempt plus tracebacks
        assert mock_log.call_count >= 3  # At least 3 attempts
        # Check that retry messages were logged
        assert any("Attempt" in str(call) for call in mock_log.call_args_list)

    def test_completes_with_valid_id_format(self, mocker):
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run")

        complete_todo("ABC123-DEF456")

        applescript = mock_run.call_args[0][0][2]
        assert '"ABC123-DEF456"' in applescript


class TestGetIncompleteTodos:
    """Test getting incomplete todos from Things 3."""

    def test_get_all_incomplete_todos(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        # Simulate output: |id~name~project|id~name~project
        mock_result.stdout = "|ABC123~Review slides~Work|XYZ789~Write report~Personal"
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todos = get_incomplete_todos()

        assert len(todos) == 2
        assert todos[0] == {"id": "ABC123", "name": "Review slides", "project": "Work"}
        assert todos[1] == {"id": "XYZ789", "name": "Write report", "project": "Personal"}

    def test_get_incomplete_todos_project_scoped(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        # Project-scoped query only returns id~name (no project)
        mock_result.stdout = "|ABC123~Review slides|DEF456~Update documentation"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todos = get_incomplete_todos(project="Work")

        assert len(todos) == 2
        assert todos[0] == {"id": "ABC123", "name": "Review slides"}
        assert todos[1] == {"id": "DEF456", "name": "Update documentation"}
        # Verify AppleScript contains project filter
        applescript = mock_run.call_args[0][0][2]
        assert 'project whose name is "Work"' in applescript

    def test_get_incomplete_todos_empty_result(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        mock_result.stdout = ""
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todos = get_incomplete_todos()

        assert todos == []

    def test_get_incomplete_todos_things_not_available(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=False)
        mocker.patch("bear_things_sync.things.log")

        todos = get_incomplete_todos()

        assert todos == []

    def test_get_incomplete_todos_subprocess_error(self, mocker):
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mocker.patch(
            "bear_things_sync.things.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "osascript", stderr="Error"),
        )
        mocker.patch("bear_things_sync.things.log")

        todos = get_incomplete_todos()

        assert todos == []

    def test_get_incomplete_todos_with_no_project(self, mocker):
        """Test todos that don't belong to any project."""
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        # Empty project field
        mock_result.stdout = "|ABC123~Buy groceries~"
        mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        todos = get_incomplete_todos()

        assert len(todos) == 1
        assert todos[0] == {"id": "ABC123", "name": "Buy groceries"}

    def test_escapes_project_name(self, mocker):
        """Test that project names with special characters are escaped."""
        mocker.patch("bear_things_sync.things.is_things_available", return_value=True)
        mock_result = MagicMock()
        mock_result.stdout = "|ABC~test"
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run", return_value=mock_result)

        get_incomplete_todos(project='Project "Special"')

        applescript = mock_run.call_args[0][0][2]
        assert r"\"" in applescript  # Should escape quotes


class TestUpdateTodoNotes:
    """Test updating todo notes in Things 3."""

    def test_successful_update(self, mocker):
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run")

        result = update_todo_notes("ABC123", "\n\nMerged with Bear todo")

        assert result is True
        mock_run.assert_called_once()
        applescript = mock_run.call_args[0][0][2]
        assert 'to do id "ABC123"' in applescript
        assert "currentNotes" in applescript
        assert "Merged with Bear todo" in applescript

    def test_escapes_special_characters(self, mocker):
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run")

        update_todo_notes("ABC123", 'Note with "quotes" and \\backslash')

        applescript = mock_run.call_args[0][0][2]
        assert r"\"" in applescript  # Escaped quotes
        assert r"\\" in applescript  # Escaped backslashes

    def test_subprocess_error_with_retry(self, mocker):
        mocker.patch("bear_things_sync.things.time.sleep")
        mocker.patch(
            "bear_things_sync.things.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "osascript", stderr="Todo not found"),
        )
        mocker.patch("bear_things_sync.things.log")

        result = update_todo_notes("INVALID", "Some note")

        assert result is False

    def test_escapes_newlines(self, mocker):
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run")

        update_todo_notes("ABC123", "Line 1\nLine 2\nLine 3")

        applescript = mock_run.call_args[0][0][2]
        assert "\\n" in applescript  # Escaped newlines

    def test_updates_with_empty_note(self, mocker):
        """Test updating with empty note (edge case)."""
        mock_run = mocker.patch("bear_things_sync.things.subprocess.run")

        result = update_todo_notes("ABC123", "")

        assert result is True
        mock_run.assert_called_once()
