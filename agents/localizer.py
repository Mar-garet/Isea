from agents.base import BaseAgent
from tools import tool_registry
from tools.registry import AgentType
from prompts.localizer import localizer
from settings import settings
from pathlib import Path
from typing import TypeAlias
from agents.context import Locations
from pydantic_ai.models import Model


Localize_output: TypeAlias = Locations


class LocalizerAgent(BaseAgent[Localize_output]):
    def __init__(self, model: Model | None = None, enable_monitoring: bool = True):
        tools = tool_registry.get_tools(AgentType.LOCALIZER)
        super().__init__(
            tools=tools,
            output_type=Localize_output,
            model=model,
            enable_monitoring=enable_monitoring,
        )

    def get_system_prompt(self) -> str:
        base_dir = Path(settings.TEST_BED) / settings.PROJECT_NAME
        combined_prompt = localizer.format(base_dir=str(base_dir))
        return combined_prompt
