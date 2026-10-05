"""Run the configured regression command inside the target Docker image."""

from dataclasses import asdict, dataclass
import subprocess

from settings import settings
from utils.dock import run_in_docker


@dataclass(frozen=True)
class ValidationResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict:
        return {**asdict(self), "passed": self.passed}


def validate_project() -> ValidationResult:
    command = settings.TEST_COMMAND.strip()
    if not command:
        raise ValueError("Set TEST_COMMAND to the project's regression test command")
    try:
        result = run_in_docker(command, timeout=settings.TEST_TIMEOUT)
    except OSError as exc:
        return ValidationResult(command, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return ValidationResult(
            command, 124, stdout, f"{stderr}\nTest execution timed out"
        )
    return ValidationResult(command, result.returncode, result.stdout, result.stderr)
