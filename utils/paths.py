"""Resolve agent paths and enumerate source files without leaving the project."""

import os
from collections.abc import Iterator
from pathlib import Path

from settings import settings

IGNORED_DIRECTORIES = {".git", ".venv", "venv", "__pycache__", ".worktrees"}


def project_root() -> Path:
    if not settings.TEST_BED:
        raise ValueError("TEST_BED must point to the prepared project directory")
    return (Path(settings.TEST_BED).expanduser() / settings.PROJECT_NAME).resolve()


def resolve_project_path(file_path: str | Path) -> Path:
    root = project_root()
    path = Path(file_path).expanduser()
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path must stay inside {root}: {file_path}")
    if ".git" in resolved.relative_to(root).parts:
        raise ValueError("Agent tools cannot access Git metadata")
    return resolved


def walk_source_tree(root: Path) -> Iterator[tuple[str, list[str], list[str]]]:
    """Exclude metadata, virtual environments and external symlink targets."""
    root = root.resolve()
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in IGNORED_DIRECTORIES
            and not (Path(directory) / name).is_symlink()
        )
        files = sorted(
            name
            for name in filenames
            if (Path(directory) / name).resolve().is_relative_to(root)
        )
        yield directory, directories, files


def python_files(root: Path) -> Iterator[Path]:
    for directory, _, filenames in walk_source_tree(root):
        for name in filenames:
            if name.endswith(".py"):
                yield Path(directory) / name
