from agents.base import BaseAgent
from tools import tool_registry
from tools.registry import AgentType
from pydantic_ai.models import Model


class TesterAgent(BaseAgent[str]):
    def __init__(self, model: Model | None = None, enable_monitoring: bool = True):
        tools = tool_registry.get_tools(AgentType.TESTER)
        super().__init__(
            tools=tools,
            output_type=str,
            model=model,
            enable_monitoring=enable_monitoring,
        )

    def get_system_prompt(self) -> str:
        return "assist user"
