import subprocess

import pytest

from settings import settings
from utils import dock, validation


@pytest.mark.parametrize("returncode", [0, 1, 5])
def test_validation_uses_test_exit_status(monkeypatch, returncode):
    monkeypatch.setattr(
        validation,
        "run_in_docker",
        lambda command, timeout: subprocess.CompletedProcess(
            [], returncode, "out", "err"
        ),
    )
    result = validation.validate_project()
    assert result.passed == (returncode == 0)
    assert result.to_dict()["passed"] == (returncode == 0)
    assert result.stdout == "out" and result.stderr == "err"


def test_validation_requires_an_explicit_command(monkeypatch):
    monkeypatch.setattr(settings, "TEST_COMMAND", "")
    with pytest.raises(ValueError, match="TEST_COMMAND"):
        validation.validate_project()


def test_timeout_is_a_failed_validation(monkeypatch):
    def timeout(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout, output=b"partial")

    monkeypatch.setattr(validation, "run_in_docker", timeout)
    result = validation.validate_project()
    assert not result.passed and result.returncode == 124
    assert result.stdout == "partial"
    assert "timed out" in result.stderr


def test_missing_docker_is_recorded_as_failure(monkeypatch):
    def unavailable(command, timeout):
        raise FileNotFoundError("docker executable not found")

    monkeypatch.setattr(validation, "run_in_docker", unavailable)
    result = validation.validate_project()
    assert not result.passed and result.returncode == 127
    assert "docker executable not found" in result.stderr


def test_docker_timeout_removes_container_and_limits_access(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[1] == "run":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(dock.subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        dock.run_in_docker("pytest -q", timeout=1)
    assert calls[0][calls[0].index("--network") + 1] == "none"
    assert "--cap-drop" in calls[0] and "--security-opt" in calls[0]
    name = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ["docker", "rm", "-f", name]


def test_copy_failure_cleans_workspace_and_container(isolated_project, monkeypatch):
    scratch = isolated_project.parent / "scratch"
    scratch.mkdir()
    removed = []
    monkeypatch.setattr(dock, "find_image", lambda _: "image")
    monkeypatch.setattr(dock, "prepare_local_dir", lambda _: scratch)
    monkeypatch.setattr(dock, "create_container", lambda *args: "container")
    monkeypatch.setattr(dock, "cleanup_container", removed.append)

    def fail(*args):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(dock, "copy_testbed", fail)
    with pytest.raises(RuntimeError, match="copy failed"):
        with dock.prepared_testbed("unit-test"):
            pass
    assert not scratch.exists() and removed == ["container"]
    assert settings.TEST_BED == str(isolated_project)


def test_create_timeout_cleans_named_container(monkeypatch):
    attempted = []
    removed = []

    def fail(args):
        attempted.append(args)
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(dock, "run", fail)
    monkeypatch.setattr(dock, "cleanup_container", removed.append)
    with pytest.raises(subprocess.TimeoutExpired):
        dock.create_container("image", "instance")
    assert removed == [attempted[0][attempted[0].index("--name") + 1]]
