import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from agents.fixer import FixerAgent
from agents.context import Context, Locations, Suggestions
from settings import settings
from utils.dock import prepared_testbed, run_in_docker
from utils.artifacts import project_relative_output
from utils.validation import validate_project


async def _run_project_operation[T](operation: Callable[[], T]) -> T:
    """Keep the workspace alive until a bounded blocking operation has exited."""
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Cancellation cannot stop a Python thread. Drain it before main() lets
        # prepared_testbed remove its mounted directory or restore configuration.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()
        raise


class AgentOrchestrator:
    """Apply a repair, validate it, then export the patch."""

    def __init__(self):
        self.fixer = FixerAgent()
        self.context = Context(issue=settings.PROBLEM_STATEMENT)
        for folder, field, output_type in [
            ("locations", "locations", Locations),
            ("suggestions", "suggestions", Suggestions),
        ]:
            path = Path("results") / folder / f"{settings.INSTANCE_ID}.json"
            if path.exists():
                setattr(
                    self.context,
                    field,
                    project_relative_output(
                        output_type.model_validate_json(path.read_text())
                    ),
                )

    def _save_git_diff(self, output_file: Path) -> None:
        # Git can invoke repository-configured filters. It belongs inside the
        # same Docker boundary as all other target-project execution.
        result = run_in_docker(
            "git -c core.fsmonitor=false add --intent-to-add . && "
            "git -c core.fsmonitor=false diff --binary --no-ext-diff --no-textconv HEAD",
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Patch export failed: {result.stderr}")
        if not result.stdout.strip():
            raise RuntimeError("The fixer produced no patch")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(result.stdout, encoding="utf-8")

    async def run(self) -> None:
        if not settings.TEST_COMMAND.strip():
            raise ValueError("Set TEST_COMMAND before running the fixer")
        stem = f"{settings.DATASET}_{settings.INSTANCE_ID}"
        patch_path = Path("results/patch_diff") / f"{stem}.patch"
        report_path = Path("results/validation") / f"{stem}.json"
        # A failed rerun must not leave artifacts that look like its successful output.
        patch_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        await self.fixer.run(
            "Verify the issue, apply the minimal repair, and run the regression tests.",
            context=self.context,
        )
        validation = await _run_project_operation(validate_project)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(validation.to_dict(), ensure_ascii=False, indent=2)
        )
        if not validation.passed:
            raise RuntimeError(f"Regression tests failed; see {report_path}")
        await _run_project_operation(lambda: self._save_git_diff(patch_path))
        print(f"Validated patch saved to {patch_path}")


async def main():
    settings.validate_runtime()
    if not settings.TEST_COMMAND.strip():
        raise ValueError("Set TEST_COMMAND before running the fixer")
    with prepared_testbed(settings.INSTANCE_ID):
        await AgentOrchestrator().run()


if __name__ == "__main__":
    asyncio.run(main())
