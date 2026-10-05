"""Own temporary SWE-bench workspaces and Docker process lifetimes."""

from contextlib import contextmanager
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from uuid import uuid4

from settings import settings
from utils.paths import project_root


def run(cmd: str | list[str], timeout: int = 120) -> str:
    args = shlex.split(cmd) if isinstance(cmd, str) else cmd
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=True
    )
    return result.stdout.strip()


def find_image(instance_id: str) -> str:
    if not instance_id:
        raise ValueError("INSTANCE_ID is required")
    if settings.DOCKER_IMAGE:
        run(["docker", "image", "inspect", settings.DOCKER_IMAGE])
        return settings.DOCKER_IMAGE
    images = run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"]
    ).splitlines()
    candidates = [image for image in images if instance_id in image]
    latest = [image for image in candidates if image.endswith(":latest")]
    candidates = latest or candidates
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one local image for {instance_id}; set DOCKER_IMAGE explicitly"
        )
    return candidates[0]


def prepare_local_dir(instance_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", instance_id) or instance_id in {".", ".."}:
        raise ValueError("INSTANCE_ID must be a single safe directory name")
    base = Path.home() / "temp_container"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{instance_id}-", dir=base))


def create_container(image: str, instance_id: str) -> str:
    name = f"sgagent-{uuid4().hex}"
    created = False
    try:
        run(["docker", "create", "--name", name, image])
        created = True
        return name
    finally:
        if not created:
            cleanup_container(name)


def copy_testbed(container_name: str, local_dir: Path) -> None:
    run(["docker", "cp", f"{container_name}:/testbed/.", str(local_dir)])


def cleanup_container(container_name: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name], capture_output=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Could not clean up Docker container {container_name}: {exc}")


def cleanup_local_dir(local_dir: Path) -> None:
    shutil.rmtree(local_dir)


@contextmanager
def prepared_testbed(instance_id: str):
    """Copy the image's testbed, configure tools to use it, and clean up on failure."""
    image = find_image(instance_id)
    local_dir = prepare_local_dir(instance_id)
    container_name = None
    previous = (settings.TEST_BED, settings.PROJECT_NAME, settings.DOCKER_IMAGE)
    try:
        container_name = create_container(image, instance_id)
        copy_testbed(container_name, local_dir)
        settings.TEST_BED = str(local_dir)
        settings.PROJECT_NAME = ""
        settings.DOCKER_IMAGE = image
        from tools.retriever_tools import invalidate_retriever

        invalidate_retriever()
        yield local_dir
    finally:
        settings.TEST_BED, settings.PROJECT_NAME, settings.DOCKER_IMAGE = previous
        if container_name is not None:
            cleanup_container(container_name)
        cleanup_local_dir(local_dir)


def run_in_docker(command: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Execute only in the target container, with a bounded lifetime and no network."""
    if not settings.DOCKER_IMAGE:
        raise ValueError("DOCKER_IMAGE is required for target execution")
    name = f"sgagent-run-{uuid4().hex}"
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "-v",
        f"{project_root()}:/testbed",
        "-w",
        "/testbed",
        settings.DOCKER_IMAGE,
        "bash",
        "--login",
        "-i",
        "-c",
        command,
    ]
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    finally:
        # Also remove a timed-out container; killing the CLI alone does not stop it.
        cleanup_container(name)
