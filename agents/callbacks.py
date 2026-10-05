from typing import Any
from agents.context import Context, Locations, Patches, Suggestions


def update_context(result: Any, context: Context) -> None:
    if isinstance(result, Locations):
        context.locations = result
    elif isinstance(result, Suggestions):
        context.suggestions = result
    elif isinstance(result, Patches):
        context.update_patches(result)
    elif isinstance(result, str):
        pass
    else:
        pass
