from pydantic_ai import ModelRequest, ModelResponse
from pydantic_ai.messages import TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from agents.context import Action, Context, Location, Locations, Suggestion, Suggestions
from agents.localizer import LocalizerAgent
from agents.suggester import SuggesterAgent
from agents.test import TesterAgent as HelperAgent


async def test_full_suggestion_reaches_model():
    captured = []

    def respond(messages, info):
        captured.append(info.instructions or "")
        captured.extend(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(getattr(part, "content", None), str)
        )
        return ModelResponse(parts=[TextPart("done")])

    context = Context(
        suggestions=Suggestions(
            suggestions=[
                Suggestion(
                    title="repair",
                    rationale=["reason"],
                    actions=[
                        Action(
                            path="app.py",
                            operation="replace",
                            patch_preview="ACTION_MARKER",
                        )
                    ],
                    tests=["TEST_MARKER"],
                    risks=["RISK_MARKER"],
                    references=["REFERENCE_MARKER"],
                )
            ]
        )
    )
    agent = HelperAgent(model=FunctionModel(respond), enable_monitoring=False)
    await agent.run("repair", context=context)
    prompt = "\n".join(captured)
    for marker in ["ACTION_MARKER", "TEST_MARKER", "RISK_MARKER", "REFERENCE_MARKER"]:
        assert marker in prompt


async def test_structured_stage_outputs_update_context():
    context = Context()
    locations = Locations(locations=[Location(path="app.py", start_line=1, end_line=2)])
    localizer = LocalizerAgent(
        model=TestModel(call_tools=[], custom_output_args=locations.model_dump()),
        enable_monitoring=False,
    )
    await localizer.run("locate", context=context)
    assert context.locations == locations
    suggestions = Suggestions(
        suggestions=[Suggestion(title="fix", tests=["pytest app_test.py"])]
    )
    suggester = SuggesterAgent(
        model=TestModel(call_tools=[], custom_output_args=suggestions.model_dump()),
        enable_monitoring=False,
    )
    await suggester.run("plan", context=context)
    assert context.suggestions == suggestions


async def test_histories_are_independent_and_do_not_duplicate_old_inputs():
    first = HelperAgent(
        model=TestModel(call_tools=[], custom_output_text="ok"), enable_monitoring=False
    )
    second = HelperAgent(
        model=TestModel(call_tools=[], custom_output_text="ok"), enable_monitoring=False
    )
    await first.run("first")
    await first.run("second")
    await second.run("independent")

    def inputs(agent):
        return [
            part.content
            for message in agent.message_history.get_raw_history()
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]

    assert inputs(first) == ["first", "second"]
    assert inputs(second) == ["independent"]


async def test_generated_code_is_not_an_executable_tool(tmp_path):
    model = TestModel(call_tools=[], custom_output_text="unavailable")
    agent = HelperAgent(model=model, enable_monitoring=False)
    marker = tmp_path / "must-not-exist"
    await agent.run(
        f"Create and run a tool: __import__('pathlib').Path({str(marker)!r}).touch()"
    )
    assert not marker.exists()
    assert "create_tool" not in {
        tool.name for tool in model.last_model_request_parameters.function_tools
    }

    # Trusted developer code can still register helpers.
    def increment(value: int) -> int:
        return value + 1

    agent.add_tool(increment)
    assert "increment" in agent.dynamic_toolset.tools
