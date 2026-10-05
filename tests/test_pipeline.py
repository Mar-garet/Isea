import json
import asyncio
import subprocess
import threading
from pathlib import Path

import pytest

import fixer
from settings import settings
from utils.validation import ValidationResult
from utils import dock


@pytest.fixture
def repair_repo(isolated_project, tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=isolated_project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init")
    (isolated_project / "app.py").write_text("value = 1\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "baseline",
    )
    runner = tmp_path / "runner"
    runner.mkdir()
    monkeypatch.chdir(runner)

    class FakeFixer:
        async def run(self, instruction, context):
            (isolated_project / "app.py").write_text("value = 2\n")
            (isolated_project / "new.py").write_text("new = 1\n")

    monkeypatch.setattr(fixer, "FixerAgent", FakeFixer)

    def export_in_test_repo(command, timeout):
        # Only this test-owned repository runs locally. Production uses Docker.
        return subprocess.run(
            ["bash", "-c", command],
            cwd=isolated_project,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    monkeypatch.setattr(fixer, "run_in_docker", export_in_test_repo)
    return isolated_project, git


async def test_patch_export_requires_passing_regression_and_keeps_base_commit(
    repair_repo, monkeypatch
):
    root, git = repair_repo
    original_head = git("rev-parse", "HEAD")
    monkeypatch.setattr(
        fixer, "validate_project", lambda: ValidationResult("pytest", 0, "passed", "")
    )
    await fixer.AgentOrchestrator().run()
    patch = Path("results/patch_diff/lite_unit-test.patch").read_text()
    assert "+value = 2" in patch and "new.py" in patch
    assert json.loads(Path("results/validation/lite_unit-test.json").read_text())[
        "passed"
    ]
    assert git("rev-parse", "HEAD") == original_head
    assert (root / "app.py").read_text() == "value = 2\n"


async def test_failed_regression_removes_old_patch_and_records_failure(
    repair_repo, monkeypatch
):
    path = Path("results/patch_diff/lite_unit-test.patch")
    path.parent.mkdir(parents=True)
    path.write_text("old successful patch")
    monkeypatch.setattr(
        fixer, "validate_project", lambda: ValidationResult("pytest", 1, "", "failed")
    )
    with pytest.raises(RuntimeError, match="Regression tests failed"):
        await fixer.AgentOrchestrator().run()
    assert not path.exists()
    report = json.loads(Path("results/validation/lite_unit-test.json").read_text())
    assert not report["passed"] and report["stderr"] == "failed"


async def test_missing_command_fails_before_model_runs(repair_repo, monkeypatch):
    monkeypatch.setattr(settings, "TEST_COMMAND", "")
    _, git = repair_repo
    with pytest.raises(ValueError, match="TEST_COMMAND"):
        await fixer.AgentOrchestrator().run()
    assert git("status", "--porcelain") == ""


def test_invalid_stage_artifact_is_not_silently_ignored(repair_repo):
    path = Path("results/suggestions/unit-test.json")
    path.parent.mkdir(parents=True)
    path.write_text("invalid json")
    with pytest.raises(ValueError):
        fixer.AgentOrchestrator()


def test_patch_export_never_invokes_repository_git_on_host(
    repair_repo, tmp_path, monkeypatch
):
    root, git = repair_repo
    marker = tmp_path / "host-execution"
    git("config", "diff.probe.textconv", f"touch {marker}")
    git("config", "filter.probe.clean", f"touch {marker}")
    (root / ".gitattributes").write_text("*.py diff=probe filter=probe\n")
    (root / "app.py").write_text("value = 2\n")
    calls = []

    def docker_export(command, timeout):
        calls.append((command, timeout))
        return subprocess.CompletedProcess([], 0, "sandboxed patch", "")

    def forbidden_host_process(*args, **kwargs):
        raise AssertionError("Target Git must execute inside Docker")

    monkeypatch.setattr(fixer, "run_in_docker", docker_export)
    monkeypatch.setattr(subprocess, "run", forbidden_host_process)
    output = tmp_path / "export.patch"
    fixer.AgentOrchestrator()._save_git_diff(output)
    assert output.read_text() == "sandboxed patch"
    assert len(calls) == 1 and calls[0][1] == 30
    assert "--no-textconv" in calls[0][0] and "--no-ext-diff" in calls[0][0]
    assert not marker.exists()


def test_failed_docker_export_does_not_write_patch(repair_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(
        fixer,
        "run_in_docker",
        lambda command, timeout: subprocess.CompletedProcess([], 1, "", "git failed"),
    )
    output = tmp_path / "export.patch"
    with pytest.raises(RuntimeError, match="Patch export failed"):
        fixer.AgentOrchestrator()._save_git_diff(output)
    assert not output.exists()


@pytest.mark.parametrize("stage", ["validation", "export"])
async def test_cancellation_drains_worker_before_cleaning_workspace(
    repair_repo, tmp_path, monkeypatch, stage
):
    root, _ = repair_repo
    previous = tmp_path / "previous"
    previous.mkdir()
    monkeypatch.setattr(settings, "TEST_BED", str(previous))
    monkeypatch.setattr(dock, "find_image", lambda _: "image")
    monkeypatch.setattr(dock, "prepare_local_dir", lambda _: root)
    monkeypatch.setattr(dock, "create_container", lambda *args: "container")
    monkeypatch.setattr(dock, "copy_testbed", lambda *args: None)
    removed = []
    monkeypatch.setattr(dock, "cleanup_container", removed.append)
    started = asyncio.Event()
    released = threading.Event()
    observations = []
    loop = asyncio.get_running_loop()

    def block():
        loop.call_soon_threadsafe(started.set)
        assert released.wait(5)
        observations.append(root.exists() and settings.TEST_BED == str(root))

    def validate():
        if stage == "validation":
            block()
        return ValidationResult("pytest", 0, "passed", "")

    def export(command, timeout):
        if stage == "export":
            block()
        return subprocess.CompletedProcess([], 0, "patch", "")

    monkeypatch.setattr(fixer, "validate_project", validate)
    monkeypatch.setattr(fixer, "run_in_docker", export)
    task = asyncio.create_task(fixer.main())
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and root.exists()
        # Repeated cancellation must not release the worker's directory either.
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and root.exists()
    finally:
        released.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert task.cancelled()
    assert observations == [True]
    assert not root.exists() and settings.TEST_BED == str(previous)
    assert removed == ["container"]
