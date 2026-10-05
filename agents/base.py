from abc import ABC, abstractmethod
from typing import (
    TypeVar,
    Generic,
    Type,
    Callable,
    TypeAlias,
    Sequence,
)
from collections.abc import AsyncIterable
from pydantic_ai import Agent, UsageLimits, RunContext, FunctionToolset, AbstractToolset
from pydantic_ai.messages import (
    AgentStreamEvent,
    PartStartEvent,
    PartDeltaEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from agents.context import Context
from agents.messages import MessageHistory
from pydantic_ai.models import Model
from settings import settings
from agents.callbacks import update_context
from utils.logging import log_event_stream, record_api_call
from utils.metrics import (
    increment_tool_usage,
    increment_agent_run,
    print_tool_usage_stats,
)

Callback: TypeAlias = Callable[..., None]
T = TypeVar("T")


class BaseAgent(ABC, Generic[T]):
    def __init__(
        self,
        tools: list | None = None,
        output_type: Type[T] | None = None,
        enable_monitoring: bool = True,
        model: Model | None = None,
        history: MessageHistory | None = None,
    ):
        self.message_history = history if history is not None else MessageHistory()
        self.model = (
            model
            if model is not None
            else OpenAIChatModel(
                settings.model,
                provider=OpenAIProvider(
                    base_url=settings.base_url or None, api_key=settings.api_key
                ),
            )
        )
        self.agent_tools = tools
        self.enable_monitoring = enable_monitoring
        self.dynamic_toolset = FunctionToolset()

        self.event_stream_handler = (
            self._create_event_handler() if enable_monitoring else None
        )

        self.agent = Agent(
            model=self.model,
            system_prompt=self.get_system_prompt(),
            tools=self.agent_tools,
            toolsets=[self.dynamic_toolset],
            output_type=output_type,
            deps_type=Context,
            output_retries=3,
            event_stream_handler=self.event_stream_handler,
        )

        @self.agent.instructions
        async def inject_context(ctx: RunContext[Context]) -> str:
            return f"Context:\n{ctx.deps.model_dump_json(exclude_none=True)}\n"

    def _create_event_handler(self):
        async def handle_events(
            ctx: RunContext[Context], events: AsyncIterable[AgentStreamEvent]
        ):
            async for event in events:
                self._print_event(event)

        return handle_events

    def _print_event(self, event):
        if isinstance(event, PartStartEvent):
            self._current_content = ""
            print(f"Begin {event.index}: {type(event.part).__name__}")
            log_event_stream(
                "PART_START",
                {"index": event.index, "part_type": type(event.part).__name__},
            )

            if hasattr(event.part, "content") and event.part.content:
                self._current_content += event.part.content

        elif isinstance(event, PartDeltaEvent):
            if hasattr(event.delta, "content_delta"):
                self._current_content += event.delta.content_delta
                # Skip logging delta events to reduce log noise

        elif isinstance(event, PartEndEvent):
            if hasattr(self, "_current_content"):
                print(f"Content : {self._current_content}")
                log_event_stream("PART_END", {"content": self._current_content})

        elif isinstance(event, FunctionToolCallEvent):
            print(f"Tool Call: {event.part.tool_name}({event.part.args})")
            log_event_stream(
                "TOOL_CALL",
                {"tool_name": event.part.tool_name, "args": event.part.args},
            )
            # Increment tool usage counter
            increment_tool_usage(event.part.tool_name)

        elif isinstance(event, FunctionToolResultEvent):
            print(f"Tool Result: {event.result.content}")
            log_event_stream("TOOL_RESULT", {"content": event.result.content})

    @abstractmethod
    def get_system_prompt(self) -> str:
        pass

    def add_tool(self, func: Callable, name: str | None = None):
        self.dynamic_toolset.add_function(func, name=name)

    def create_toolset(self, tools: list[Callable]) -> FunctionToolset:
        return FunctionToolset(tools=tools)

    async def run(
        self,
        message: str,
        context: Context | None = None,
        use_shared_history: bool = True,
        callback: Callback = update_context,
        toolsets: Sequence[AbstractToolset[Context]] | None = None,
    ) -> T:
        # Increment agent run counter using class name
        agent_name = self.__class__.__name__
        increment_agent_run(agent_name)

        if context is None:
            context = Context()

        message_history = None
        if use_shared_history:
            message_history = self.message_history.get_raw_history()

        # The provider retries individual HTTP requests. Restarting a whole run
        # could replay file edits that already succeeded before a model failure.
        result = await self.agent.run(
            message,
            deps=context,
            message_history=message_history,
            usage_limits=UsageLimits(request_limit=150),
            toolsets=toolsets,
        )
        # Log API call usage (tokens)
        usage = result.usage()
        if usage and self.enable_monitoring:
            record_api_call(
                model=settings.model,
                usage=usage,
                prompt=message,
                response=str(result.output) if result.output else "",
            )

        if use_shared_history:
            messages = result.new_messages()
            self.message_history.add_model_messages(messages)

        if callback:
            callback(result.output, context)

        # Print tool usage statistics after each run
        if self.enable_monitoring:
            print_tool_usage_stats()

        return result.output
