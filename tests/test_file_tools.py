import subprocess

import pytest

from agents.context import Patch
from tools import fixer_tools as edits
from tools import retriever_tools as reads
from utils.apply_check import apply_patches
from utils.paths import resolve_project_path


@pytest.mark.parametrize(
    "operation",
    [
        lambda path: edits.create_file(path, "modified = True"),
        lambda path: edits.edit_file_by_lineno(path, "modified = True", 1, 1),
        lambda path: edits.insert(path, "modified = True", 1),
        lambda path: edits.edit_file_by_content(path, "original", "modified"),
        lambda path: reads.read_file_lines(path, 1, 1),
        lambda path: reads.show_file_imports(path),
        lambda path: reads.extract_complete_method(path, "module.function"),
        lambda path: reads.get_code_relationships(path, "module.function"),
        lambda path: reads.analyze_file_structure(path),
        lambda path: reads.find_variable_usage(path, "original"),
        lambda path: reads.explore_directory(path),
        lambda path: reads.search_code_with_context("original", path),
    ],
)
@pytest.mark.parametrize("kind", ["relative", "absolute", "symlink"])
def test_tools_reject_paths_outside_project(operation, kind, isolated_project):
    outside = isolated_project.parent / "outside.py"
    outside.write_text("original = 'private-marker'\n")
    path = {
        "relative": "../outside.py",
        "absolute": str(outside),
        "symlink": "link.py",
    }[kind]
    if kind == "symlink":
        (isolated_project / "link.py").symlink_to(outside)
    result = operation(path)
    assert isinstance(result, str) and result.startswith("Error:")
    assert "private-marker" not in result
    assert outside.read_text() == "original = 'private-marker'\n"


def test_new_file_rejects_symlinked_parent_before_writing(isolated_project):
    external = isolated_project.parent / "external"
    external.mkdir()
    (isolated_project / "link").symlink_to(external, target_is_directory=True)
    assert edits.create_file("link/new.py", "value = 1").startswith("Error:")
    assert not (external / "new.py").exists()


def test_file_edits_validate_ranges_and_preserve_literal_backslashes(
    isolated_project, monkeypatch
):
    monkeypatch.setattr(edits, "ruff_check_file", lambda path: "ok")
    file = isolated_project / "app.py"
    file.write_text("value = 1\n")
    assert edits.edit_file_by_lineno("app.py", "bad", 0, 1).startswith("Error:")
    assert file.read_text() == "value = 1\n"
    replacement = 'value = r"\\d+\\1"\n'
    assert edits.edit_file_by_content("app.py", "value = 1\\n", replacement).startswith(
        "Successfully"
    )
    assert file.read_text() == replacement
    assert edits.insert("app.py", "other = 2", 2).startswith("Successfully")
    assert file.read_text().endswith("other = 2\n")


def test_create_file_executes_in_docker_with_quoted_filename(
    isolated_project, monkeypatch
):
    calls = []

    def execute(command, timeout):
        calls.append((command, timeout))
        return subprocess.CompletedProcess([], 0, "ok", "")

    monkeypatch.setattr(edits, "run_in_docker", execute)
    assert "Exit code: 0" in edits.create_file(
        "file with spaces.py", "value = 1", timeout=3
    )
    assert (isolated_project / "file with spaces.py").read_text() == "value = 1"
    assert calls == [("python './file with spaces.py'", 3)]


def test_patch_application_cannot_escape_project(isolated_project):
    outside = isolated_project.parent / "outside.py"
    outside.write_text("value = 1\n")
    result = apply_patches(
        [
            Patch(
                path="../outside.py",
                start_line=1,
                end_line=1,
                operation="replace",
                content="value = 2",
            )
        ]
    )
    assert result.startswith("Failed")
    assert outside.read_text() == "value = 1\n"


def test_path_normalizes_safe_parent_segments(isolated_project):
    assert resolve_project_path("sub/../app.py") == isolated_project / "app.py"


def test_agent_tools_cannot_modify_or_read_git_metadata(isolated_project):
    metadata = isolated_project / ".git"
    metadata.mkdir()
    config = metadata / "config"
    config.write_text("private-git-config")
    assert edits.edit_file_by_lineno(".git/config", "filter = unsafe", 1, 1).startswith(
        "Error:"
    )
    assert reads.read_file_lines(".git/config", 1, 1).startswith("Error:")
    assert config.read_text() == "private-git-config"
