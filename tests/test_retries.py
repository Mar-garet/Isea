import pytest
from pydantic_ai import ModelResponse
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents.test import TesterAgent as HelperAgent


async def test_model_failure_does_not_restart_repair_and_replay_completed_tools():
    requests = 0
    effects = []

    def respond(messages, info):
        nonlocal requests
        requests += 1
        if requests == 1:
            return ModelResponse(parts=[ToolCallPart("append_marker", {})])
        raise ModelHTTPError(503, "offline-model")

    def append_marker() -> str:
        effects.append("applied")
        return "applied"

    agent = HelperAgent(model=FunctionModel(respond), enable_monitoring=False)
    agent.add_tool(append_marker)
    with pytest.raises(ModelHTTPError):
        await agent.run("repair")
    assert requests == 2
    assert effects == ["applied"]


async def test_authentication_failure_is_not_retried_as_a_new_agent_run():
    requests = 0

    def respond(messages, info):
        nonlocal requests
        requests += 1
        raise ModelHTTPError(401, "offline-model")

    agent = HelperAgent(model=FunctionModel(respond), enable_monitoring=False)
    with pytest.raises(ModelHTTPError):
        await agent.run("repair")
    assert requests == 1
