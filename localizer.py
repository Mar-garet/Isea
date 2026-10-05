import asyncio
import json
from pathlib import Path
from agents.localizer import LocalizerAgent
from agents.context import Context
from settings import settings
from utils.dock import prepared_testbed
from utils.artifacts import project_relative_output


class AgentOrchestrator:
    """Orchestrates the single localizer agent system to locate the bug."""

    def __init__(self):
        self.localizer = LocalizerAgent()
        self.context = Context()
        self.context.issue = settings.PROBLEM_STATEMENT

    async def run(self) -> None:
        """
        Run the single localizer agent system.
        """
        print("=" * 60)
        print("\nRunning Localizer Agent...")
        print(f"Using the docker image :{settings.DOCKER_IMAGE}")
        localizer_instruction = (
            "Identify the locations of the bug based on the issue description."
        )

        result = await self.localizer.run(localizer_instruction, context=self.context)
        result = project_relative_output(result)
        print(f"Localizer result: {result}")

        # Save the locations to a file
        output_file = Path(f"results/locations/{settings.INSTANCE_ID}.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=4)
        print(f"Locations saved to {output_file}")


async def main():
    settings.validate_runtime()
    with prepared_testbed(settings.INSTANCE_ID):
        await AgentOrchestrator().run()


if __name__ == "__main__":
    asyncio.run(main())
