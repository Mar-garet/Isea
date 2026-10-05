from collections import defaultdict
import subprocess
from typing import List

from agents.context import Patch
from utils.paths import resolve_project_path


def ruff_check_file(file_path: str, select_rules: str = "E9,F821") -> str:
    """
    Use ruff to check a single file for code quality issues,
    particularly focusing on indentation and undefined variables.

    :param file_path: Path to the Python file to check
    :param select_rules: Comma-separated list of rule prefixes to check (default: common rules)

    :return: Raw output from ruff check command
    """
    try:
        cmd = ["ruff", "check", file_path, "--isolated", f"--select={select_rules}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return f"No issues found in {file_path} for rules: {select_rules}"
        else:
            output = result.stdout.strip()
            if result.stderr.strip():
                output += f"\nStderr: {result.stderr.strip()}"
            return output

    except subprocess.TimeoutExpired:
        return f"Ruff check timed out for {file_path}"
    except FileNotFoundError:
        return "Ruff is not installed or not found in PATH. Please install ruff first with 'pip install ruff'"
    except Exception as e:
        return f"Error running ruff check on {file_path}: {str(e)}"


def apply_patches(patches: List[Patch]) -> str:
    results = []
    patches_by_file = defaultdict(list)

    for patch in patches:
        patches_by_file[patch.path].append(patch)

    for file_path, file_patches in patches_by_file.items():
        try:
            # Check if the file path is relative and needs to be converted to absolute
            path_obj = resolve_project_path(file_path)

            if path_obj.exists():
                text = path_obj.read_text(encoding="utf-8")
                lines = text.splitlines(keepends=True)
            else:
                lines = []

            file_patches.sort(key=lambda p: p.start_line, reverse=True)

            for patch in file_patches:
                if patch.start_line < 1 or patch.end_line < patch.start_line:
                    raise ValueError("Invalid patch line range")
                if patch.operation == "replace" and patch.end_line > len(lines):
                    raise ValueError("Replacement extends past the end of the file")
                if patch.operation == "insert" and patch.start_line > len(lines) + 1:
                    raise ValueError("Insertion extends past the end of the file")
                start = patch.start_line - 1
                end = patch.end_line

                if patch.operation == "insert":
                    if patch.content:
                        new_lines = patch.content.splitlines(keepends=True)
                        if not new_lines[-1].endswith("\n"):
                            new_lines[-1] += "\n"
                        lines[start:start] = new_lines

                elif patch.operation == "replace":
                    if patch.content is None or patch.content.strip() == "":
                        lines[start:end] = []
                    else:
                        new_lines = patch.content.splitlines(keepends=True)
                        if not new_lines[-1].endswith("\n"):
                            new_lines[-1] += "\n"
                        lines[start:end] = new_lines

            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text("".join(lines), encoding="utf-8")
            from tools.retriever_tools import invalidate_retriever

            invalidate_retriever()
            results.append(f"Applied {len(file_patches)} patches to {file_path}")

        except Exception as e:
            results.append(f"Failed to process {file_path}: {e}")

    return "\n".join(results)
