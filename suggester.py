import asyncio
import json
from pathlib import Path
from agents.suggester import SuggesterAgent
from agents.context import Context, Locations
from settings import settings
from utils.dock import prepared_testbed
from utils.artifacts import project_relative_output


class AgentOrchestrator:
    def __init__(self):
        self.suggester = SuggesterAgent()
        self.context = Context()
        self.context.issue = settings.PROBLEM_STATEMENT
        loc_file = Path(f"results/locations/{settings.INSTANCE_ID}.json")
        if loc_file.exists():
            data = json.loads(loc_file.read_text(encoding="utf-8"))
            self.context.locations = project_relative_output(Locations(**data))

    async def run(self) -> None:
        print("=" * 60)
        print("\nRunning Suggester Agent...")
        print(f"Using the docker image :{settings.DOCKER_IMAGE}")
        suggester_instruction = (
            """Propose structured fix suggestions based on the issue description."""
        )

        result = await self.suggester.run(suggester_instruction, context=self.context)
        result = project_relative_output(result)
        print(f"Suggester result: {result}")

        output_file = Path(f"results/suggestions/{settings.INSTANCE_ID}.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=4)
        print(f"Suggestions saved to {output_file}")


async def main():
    settings.validate_runtime()
    with prepared_testbed(settings.INSTANCE_ID):
        await AgentOrchestrator().run()


if __name__ == "__main__":
    asyncio.run(main())
