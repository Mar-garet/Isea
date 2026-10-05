import json
import re
import shlex
from pathlib import Path

from tools.registry import tool_registry, AgentType
from tools.retriever_tools import invalidate_retriever
from utils.apply_check import ruff_check_file
from utils.dock import run_in_docker
from utils.paths import project_root, resolve_project_path
from utils.validation import validate_project


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    invalidate_retriever()


@tool_registry.register(agents=[AgentType.FIXER])
def create_file(file_path: str, code: str, timeout: int = 60) -> str:
    """Create a Python file inside the project and execute it only in Docker."""
    try:
        if timeout <= 0:
            return "Error: timeout must be positive"
        path = resolve_project_path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_file(path, code)
        relative = path.relative_to(project_root())
        result = run_in_docker(
            f"python {shlex.quote('./' + str(relative))}", timeout=timeout
        )
        return f"Exit code: {result.returncode}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    except Exception as exc:
        return f"Error: Could not create or execute file: {exc}"


@tool_registry.register(agents=[AgentType.FIXER])
def edit_file_by_lineno(
    file_path: str, content: str, start_line: int, end_line: int
) -> str:
    """Replace inclusive, one-based lines inside the project; empty content deletes."""
    try:
        path = resolve_project_path(file_path)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not 1 <= start_line <= end_line <= len(lines):
            return f"Error: Invalid line range. File has {len(lines)} lines."
        if content and not content.endswith("\n"):
            content += "\n"
        _write_file(
            path, "".join(lines[: start_line - 1] + [content] + lines[end_line:])
        )
        return f"Successfully edited {file_path}\n{ruff_check_file(str(path))}"
    except Exception as exc:
        return f"Error: Could not edit file: {exc}"


@tool_registry.register(agents=[AgentType.FIXER])
def insert(file_path: str, content: str, insert_line: int) -> str:
    """Insert before a one-based line, including one position past the file's end."""
    try:
        path = resolve_project_path(file_path)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not 1 <= insert_line <= len(lines) + 1:
            return f"Error: Invalid insert line. File has {len(lines)} lines."
        if content and not content.endswith("\n"):
            content += "\n"
        lines[insert_line - 1 : insert_line - 1] = [content]
        _write_file(path, "".join(lines))
        return f"Successfully inserted content in {file_path}\n{ruff_check_file(str(path))}"
    except Exception as exc:
        return f"Error: Could not insert content: {exc}"


@tool_registry.register(agents=[AgentType.FIXER])
def edit_file_by_content(file_path: str, old_content: str, new_content: str) -> str:
    """Replace one unambiguous regex match inside the project."""
    try:
        path = resolve_project_path(file_path)
        content = path.read_text(encoding="utf-8")
        matches = list(re.finditer(old_content, content, re.MULTILINE | re.DOTALL))
        if len(matches) != 1:
            return (
                f"Error: Pattern must match exactly once; found {len(matches)} matches."
            )
        # Use a callable so replacement code containing backslashes stays literal.
        updated = re.sub(
            old_content,
            lambda _: new_content,
            content,
            count=1,
            flags=re.MULTILINE | re.DOTALL,
        )
        _write_file(path, updated)
        return f"Successfully edited {file_path}\n{ruff_check_file(str(path))}"
    except Exception as exc:
        return f"Error: Could not edit file: {exc}"


@tool_registry.register(agents=[AgentType.FIXER])
def run_tests() -> str:
    """Run the configured regression tests in Docker and return their exit status."""
    return json.dumps(validate_project().to_dict(), ensure_ascii=False)
