"""Keep structured file paths portable across independent stage workspaces."""

from agents.context import Locations, Suggestions
from utils.paths import project_root, resolve_project_path


def project_relative_output[T: Locations | Suggestions](output: T) -> T:
    normalized = output.model_copy(deep=True)
    root = project_root()
    items = (
        normalized.locations
        if isinstance(normalized, Locations)
        else [
            action
            for suggestion in normalized.suggestions
            for action in suggestion.actions
        ]
    )
    for item in items:
        item.path = resolve_project_path(item.path).relative_to(root).as_posix()
    return normalized
